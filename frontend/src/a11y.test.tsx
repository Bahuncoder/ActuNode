/// <reference types="node" />
// Accessibility acceptance (design brief, "Accessibility and feedback acceptance").
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'
import * as api from './api'
import FailurePanel from './FailurePanel'
import type { MqttMessage, RecordingStatus, ReplayStatus, Robot } from './live'
import MessageStream from './MessageStream'
import MissionSender from './MissionSender'
import RecorderPanel from './RecorderPanel'
import ReplayBanner from './ReplayBanner'

vi.mock('./api', async (importOriginal) => ({ ...(await importOriginal<typeof api>()), fetchSessions: vi.fn(), fetchSessionStorage: vi.fn(), fetchRecording: vi.fn() }))

afterEach(cleanup)

const css = readFileSync(`${process.cwd()}/src/index.css`, 'utf8')

describe('colour tokens', () => {
  const token = (name: string) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'))![1]
  const luminance = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const c = parseInt(hex.slice(i, i + 2), 16) / 255
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
    return (hi + 0.05) / (lo + 0.05)
  }

  it('form control borders have 3:1 against the panel and the page background', () => {
    expect(ratio(token('control-border'), token('panel'))).toBeGreaterThanOrEqual(3)
    expect(ratio(token('control-border'), token('node-navy'))).toBeGreaterThanOrEqual(3)
  })

  it('inputs and selects use the control border', () => {
    expect(css).not.toMatch(/(select|input)[^{]*\{[^}]*border: 1px solid var\(--border\)/)
  })
})

describe('reduced motion', () => {
  it('turns off animations, transitions and smooth scrolling', () => {
    const block = css.match(/@media \(prefers-reduced-motion: reduce\) \{([\s\S]*?\n)\}/)![1]
    expect(block).toMatch(/animation-duration: 0\.01ms/)
    expect(block).toMatch(/animation-iteration-count: 1/)
    expect(block).toMatch(/transition-duration: 0\.01ms/)
    expect(block).toMatch(/scroll-behavior: auto/)
  })

  it('has no JavaScript-driven animation or smooth scrolling', () => {
    for (const file of ['WarehouseMap.tsx', 'App.tsx', 'MessageStream.tsx', 'RobotTable.tsx']) {
      expect(readFileSync(`${process.cwd()}/src/${file}`, 'utf8')).not.toMatch(/scrollIntoView|behavior:\s*'smooth'|requestAnimationFrame/)
    }
  })
})

describe('screen reader announcements', () => {
  const recording = (sessionId: string, messageCount = 0): RecordingStatus => ({ sessionId, name: null, startedAt: '2026-10-10T12:00:00Z', messageCount, duration: 0, sizeBytes: 0 })
  const panel = (rec: RecordingStatus | null, stopped: { sessionId: string; reason: string } | null = null) => (
    <RecorderPanel recording={rec} recordingStopped={stopped as never} replay={null} />
  )

  it('announces recording start and stop, not the counters', () => {
    vi.mocked(api.fetchSessions).mockResolvedValue([])
    vi.mocked(api.fetchSessionStorage).mockResolvedValue({ keepDays: 0, maxTotalMb: 0, usedMb: 0, sessions: 0 })
    const { rerender, container } = render(panel(null))
    const region = () => container.querySelector('.sr-only[role="status"]')!.textContent
    expect(region()).toBe('')
    rerender(panel(recording('s1')))
    expect(region()).toBe('Recording started: s1')
    rerender(panel(recording('s1', 500)))
    expect(region()).toBe('Recording started: s1')
    rerender(panel(null, { sessionId: 's1', reason: 'sizeLimit' }))
    expect(region()).toMatch(/^Recording stopped: s1 \(.*size limit.*\)$/)
  })

  it('announces replay start and end, not progress', () => {
    const replay = (state: ReplayStatus['state'], sent: number): ReplayStatus =>
      ({ sessionId: 's', state, speed: 1, includeCommands: false, sent, total: 9, position: sent, duration: 9 }) as ReplayStatus
    const { rerender, container } = render(<ReplayBanner replay={null} />)
    const region = () => container.querySelector('.sr-only[role="status"]')!.textContent
    rerender(<ReplayBanner replay={replay('running', 1)} />)
    expect(region()).toBe('Replay started: s')
    rerender(<ReplayBanner replay={replay('running', 5)} />)
    expect(region()).toBe('Replay started: s')
    rerender(<ReplayBanner replay={replay('finished', 9)} />)
    expect(region()).toBe('Replay finished: s')
  })

  it('puts action results in status and errors in alert', async () => {
    const robot = { key: 'v2/X/r1', robotId: 'r1', manufacturer: 'ActuNode', connection: 'ONLINE', lastSeen: null, state: { errors: [], nodeStates: [], actunode: { missionStatus: 'MOVING' } } } as unknown as Robot
    const respond = (ok: boolean) =>
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 500, json: async () => (ok ? {} : { detail: 'nope' }) }))
    render(<FailurePanel robots={[robot]} failures={[]} />)
    respond(true)
    fireEvent.click(screen.getByRole('button', { name: 'Inject' }))
    await waitFor(() => expect(screen.getByRole('status').textContent).toMatch(/injected on/))
    respond(false)
    fireEvent.click(screen.getByRole('button', { name: 'Inject' }))
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/nope|500/))
    expect(screen.queryByRole('status')).toBeNull()
    vi.unstubAllGlobals()
  })

  it('announces a mission form hint as an alert', () => {
    render(<MissionSender robots={[]} locations={{}} />)
    for (const alert of screen.queryAllByRole('alert')) expect(alert.className).toContain('error')
  })
})

describe('message stream keyboard', () => {
  const messages: MqttMessage[] = [1, 2, 3].map((id) => ({
    id, receivedAt: '2026-10-10T12:00:00Z', topic: `uagv/v2/ActuNode/r${id}/state`, retained: false, validJson: true, payload: { id }, issues: [],
  }))

  it('is one Tab stop; arrows, Home and End move; Enter and Space select', () => {
    render(<MessageStream messages={messages} />)
    const list = screen.getByRole('listbox', { name: 'Messages' })
    const options = screen.getAllByRole('option')
    const tabStops = () => Array.from(list.querySelectorAll<HTMLElement>('[tabindex]')).filter((el) => el.tabIndex >= 0)
    const press = (key: string) => fireEvent.keyDown(document.activeElement!, { key })
    expect(tabStops()).toEqual([options[0]])

    options[0].focus()
    press('ArrowDown')
    expect(document.activeElement).toBe(options[1])
    expect(tabStops()).toEqual([options[1]])
    press('End')
    expect(document.activeElement).toBe(options[2])
    press('ArrowDown')
    expect(document.activeElement).toBe(options[2])
    press('ArrowUp')
    press('Home')
    expect(document.activeElement).toBe(options[0])

    press('Enter')
    expect(options[0].getAttribute('aria-selected')).toBe('true')
    expect(document.querySelector('pre.raw')).toBeTruthy()
    press(' ')
    expect(options[0].getAttribute('aria-selected')).toBe('false')
  })

  it('keeps the selected row as the Tab stop', () => {
    render(<MessageStream messages={messages} />)
    const options = screen.getAllByRole('option')
    fireEvent.click(options[2])
    expect(options.map((o) => o.tabIndex)).toEqual([-1, -1, 0])
  })
})
