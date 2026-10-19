/// <reference types="node" />
// Frontend audit (docs/AUDIT_2026-10-14.md, section F): each test failed before its fix.
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import conf from '../nginx.conf?raw'
import * as api from './api'
import App from './App'
import FailurePanel from './FailurePanel'
import { display, reducer, statusClass, stringList, useLiveFeed, type Feed, type MqttMessage, type Robot } from './live'
import MessageStream from './MessageStream'
import MissionSender from './MissionSender'
import PanelBoundary from './PanelBoundary'
import RecorderPanel from './RecorderPanel'
import ReplayBanner from './ReplayBanner'
import RobotTable from './RobotTable'
import ValidationPanel from './ValidationPanel'
import WarehouseMap from './WarehouseMap'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const hostile = { toString: 0 }
const throwing = {
  get boom(): never {
    throw new Error('getter')
  },
}

function robot(state: unknown, extra: Partial<Robot> = {}): Robot {
  return { key: 'v2/ActuNode/r1', robotId: 'r1', manufacturer: 'ActuNode', connection: 'ONLINE', lastSeen: null, state: state as Robot['state'], ...extra }
}

function msg(topic: string, payload: unknown, id = 1): MqttMessage {
  return { id, receivedAt: '2026-10-10T12:00:00Z', topic, retained: false, validJson: true, payload, issues: [] }
}

describe('F1/F2/F18 safe readers', () => {
  it('stringList keeps only strings of a list', () => {
    expect(stringList(['a', 1, null, 'b'])).toEqual(['a', 'b'])
    expect(stringList('X')).toEqual([])
    expect(stringList({ length: 3 })).toEqual([])
  })

  it('display never throws', () => {
    expect(display('x')).toBe('x')
    expect(display(1.5)).toBe('1.5')
    expect(display(true)).toBe('true')
    expect(display(hostile)).toBe('{"toString":0}')
    expect(display(throwing)).toBe('[unprintable]')
    expect(display(10n)).toBe('[unprintable]')
    expect(() => display(undefined)).not.toThrow()
  })
})

describe('F1/F2 hostile robot data does not take panels down', () => {
  const quiet = () => vi.spyOn(console, 'error').mockImplementation(() => {})

  it('RobotTable survives injectedFailures, _truncated.dropped and errors of the wrong kind', () => {
    quiet()
    const state = {
      actunode: { missionStatus: 'IDLE', injectedFailures: 'X' },
      _truncated: { dropped: 'abc', lists: 'nope', bytes: hostile },
      errors: [{ errorDescription: hostile, errorLevel: 'WARNING' }],
      loads: [{ loadId: hostile }],
    }
    expect(() => render(<RobotTable robots={[robot(state)]} />)).not.toThrow()
    expect(screen.getByText(/state trimmed/)).toBeTruthy()
  })

  it('FailurePanel survives injectedFailures as a string', () => {
    quiet()
    const state = { actunode: { missionStatus: 'MOVING', injectedFailures: 'X' } }
    expect(() => render(<FailurePanel robots={[robot(state)]} failures={[]} />)).not.toThrow()
  })

  it('MessageStream survives objects that cannot be turned into text', () => {
    quiet()
    const messages = [
      msg('uagv/v2/ActuNode/r1/state', { errors: [{ errorDescription: hostile }], actunode: { missionStatus: hostile } }, 1),
      msg('uagv/v2/ActuNode/r1/order', { orderId: hostile, nodes: [{ nodeId: hostile }] }, 2),
      msg('uagv/v2/ActuNode/r1/connection', { connectionState: hostile }, 3),
      msg('uagv/v2/ActuNode/r1/inject', { failure: hostile, action: hostile, injectionId: hostile }, 4),
    ]
    expect(() => render(<MessageStream messages={messages} />)).not.toThrow()
  })

  it('ValidationPanel survives non-text rule fields', () => {
    quiet()
    const validation = {
      since: '2026-10-10T12:00:00Z',
      checked: 1,
      withIssues: 1,
      byRule: [{ rule: 'r', description: hostile, severity: 'error', count: 1, last: { message: hostile, topic: hostile, at: 'x' } }],
    } as unknown as Parameters<typeof ValidationPanel>[0]['validation']
    expect(() => render(<ValidationPanel validation={validation} />)).not.toThrow()
  })
})

describe('PanelBoundary reset key', () => {
  function Bomb({ explode }: { explode: boolean }) {
    if (explode) throw new Error('bad data')
    return <p>fine</p>
  }

  it('renders the children again once the data changes, without Try again', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { rerender } = render(
      <PanelBoundary title="P" resetKey={1}>
        <Bomb explode />
      </PanelBoundary>,
    )
    expect(screen.getByText(/failed to render/)).toBeTruthy()
    rerender(
      <PanelBoundary title="P" resetKey={2}>
        <Bomb explode={false} />
      </PanelBoundary>,
    )
    expect(screen.getByText('fine')).toBeTruthy()
  })
})

describe('F8 status class', () => {
  it('maps only known statuses to a class', () => {
    expect(statusClass('MOVING')).toBe('status-moving')
    expect(statusClass('IDLE near offline')).toBe('status-unknown')
    expect(statusClass('')).toBe('status-unknown')
  })

  it('RobotTable and WarehouseMap do not pass robot text into class names', () => {
    const r = robot({ agvPosition: { x: 1, y: 1, theta: 0 }, actunode: { missionStatus: 'IDLE near offline' } })
    const table = render(<RobotTable robots={[r]} />)
    expect(table.container.querySelectorAll('.badge')[1]?.className).toBe('badge status-unknown')
    cleanup()
    const map = render(<WarehouseMap robots={[r]} locations={{}} />)
    expect(map.container.querySelector('g.robot')?.getAttribute('class')).not.toMatch(/near|offline/)
  })
})

describe('F19 robot table errors', () => {
  it('keeps one error per robot key and drops it when the robot is gone', async () => {
    vi.spyOn(api, 'cancelMission').mockRejectedValue(new Error('boom'))
    const a = robot({ actunode: { missionStatus: 'MOVING' } }, { key: 'v2/A/r1' })
    const b = robot({ actunode: { missionStatus: 'MOVING' } }, { key: 'v2/B/r1' })
    const { rerender } = render(<RobotTable robots={[a, b]} />)
    const buttons = screen.getAllByRole('button', { name: /Cancel mission/ })
    fireEvent.click(buttons[0])
    fireEvent.click(buttons[1])
    await waitFor(() => expect(screen.getAllByText('r1: boom')).toHaveLength(2)) // same text, two keys: no duplicate-key clash
    rerender(<RobotTable robots={[b]} />)
    expect(screen.getAllByText('r1: boom')).toHaveLength(1)
  })
})

describe('F5 failure panel target', () => {
  it('picks the default once and falls back to a listed robot when the chosen one is gone', () => {
    const moving = (id: string) => robot({ actunode: { missionStatus: 'MOVING' } }, { key: `v2/X/${id}`, robotId: id })
    const idle = (id: string) => robot({ actunode: { missionStatus: 'IDLE' } }, { key: `v2/X/${id}`, robotId: id })
    const { rerender } = render(<FailurePanel robots={[idle('a'), moving('b')]} failures={[]} />)
    const select = () => screen.getByLabelText('Robot') as HTMLSelectElement
    expect(select().value).toBe('b')
    rerender(<FailurePanel robots={[moving('a'), idle('b')]} failures={[]} />) // statuses change: no jump
    expect(select().value).toBe('b')
    rerender(<FailurePanel robots={[moving('a'), moving('c')]} failures={[]} />) // b evicted
    expect(select().value).toBe('a')
  })

  it('refuses a fractional number (the backend takes whole numbers)', () => {
    render(<FailurePanel robots={[robot({ actunode: { missionStatus: 'MOVING' } })]} failures={[]} />)
    fireEvent.change(screen.getByLabelText('Failure type'), { target: { value: 'LOW_BATTERY' } })
    fireEvent.change(screen.getByLabelText('Battery level'), { target: { value: '1.5' } })
    expect((screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText('Battery level'), { target: { value: '15' } })
    expect((screen.getByRole('button', { name: 'Inject' }) as HTMLButtonElement).disabled).toBe(false)
  })
})

describe('F15/F17 forms and accessibility', () => {
  it('limits the load id to the backend maximum', () => {
    render(<MissionSender robots={[]} locations={{}} />)
    expect(screen.getByLabelText('Load').getAttribute('maxlength')).toBe('64')
  })

  it('labels the topic filter and marks message rows expandable', () => {
    render(<MessageStream messages={[msg('uagv/v2/ActuNode/r1/state', {})]} />)
    expect(screen.getByLabelText('Filter by topic')).toBeTruthy()
    const row = screen.getByRole('button', { name: /state/ })
    expect(row.getAttribute('aria-expanded')).toBe('false')
    fireEvent.click(row)
    expect(row.getAttribute('aria-expanded')).toBe('true')
  })

  it('announces only the replay state, not its progress', () => {
    const replay = { sessionId: 's', state: 'running', speed: 1, includeCommands: false, sent: 1, total: 2, position: 1, duration: 2 } as const
    const { container } = render(<ReplayBanner replay={replay} />)
    const live = container.querySelectorAll('[role="status"]')
    expect(live).toHaveLength(1)
    expect(live[0].textContent).toBe('') // nothing announced until the state changes
    expect(container.textContent).toContain('▶ REPLAYING')
  })

  it('uses a muted grey with at least 4.5:1 contrast on the panel and page colours', () => {
    const css = readFileSync(`${process.cwd()}/src/index.css`, 'utf8')
    const color = (name: string) => css.match(new RegExp(`--${name}:\\s*(#[0-9a-f]{6})`, 'i'))![1]
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
    for (const background of ['panel', 'node-navy']) expect(ratio(color('industrial-gray'), color(background))).toBeGreaterThanOrEqual(4.5)
  })
})

describe('F6/F7/F3 live feed', () => {
  const empty: Feed = {
    connected: true, robots: {}, messages: [], failures: [], recording: null, recordingStopped: null,
    replay: null, validation: null, proximity: [], sessionsVersion: 3,
  }
  type FakeSocket = { onmessage: (m: { data: string }) => void; onclose: (e: { code: number }) => void; onopen: () => void; close: ReturnType<typeof vi.fn> }

  function setup(onSessionEnded?: () => void) {
    const sockets: FakeSocket[] = []
    vi.stubGlobal('WebSocket', function (this: FakeSocket) {
      this.close = vi.fn()
      sockets.push(this)
    })
    const hook = renderHook(() => useLiveFeed(onSessionEnded))
    const send = (event: unknown) => sockets.at(-1)!.onmessage({ data: JSON.stringify(event) })
    return { sockets, hook, send }
  }

  it('a snapshot bumps sessionsVersion', () => {
    const snapshot = { type: 'snapshot' as const, robots: [], messages: [], failures: [], recording: null, replay: null, validation: { since: '', checked: 0, withIssues: 0, byRule: [] } }
    expect(reducer(empty, { type: 'event', event: snapshot }).sessionsVersion).toBe(4)
  })

  it('flushes on a timer when animation frames never run (hidden tab)', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', () => 1) // never calls back
    vi.stubGlobal('cancelAnimationFrame', () => {})
    const { hook, send } = setup()
    act(() => send({ type: 'message', message: msg('uagv/v2/X/r1/state', {}), robot: null }))
    expect(hook.result.current.messages).toHaveLength(0)
    act(() => {
      vi.advanceTimersByTime(500)
    })
    expect(hook.result.current.messages).toHaveLength(1)
  })

  it('on queue overflow drops the queue, closes the socket and reconnects quickly for a snapshot', () => {
    vi.useFakeTimers()
    vi.stubGlobal('requestAnimationFrame', () => 1)
    vi.stubGlobal('cancelAnimationFrame', () => {})
    const { sockets, hook, send } = setup()
    act(() => {
      for (let i = 1; i <= 5001; i++) send({ type: 'message', message: msg('uagv/v2/X/r1/state', {}, i), robot: null })
    })
    expect(sockets[0].close).toHaveBeenCalled()
    act(() => {
      vi.advanceTimersByTime(5000) // nothing queued is applied late
    })
    expect(hook.result.current.messages).toHaveLength(0)
    act(() => sockets[0].onclose({ code: 1005 }))
    act(() => {
      vi.advanceTimersByTime(300)
    })
    expect(sockets).toHaveLength(2)
  })

  it('backs off exponentially with a 30 s cap, and starts over after an answer', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(1)
    const { sockets, send } = setup()
    const reconnectAfter = (ms: number) => {
      const before = sockets.length
      act(() => sockets.at(-1)!.onclose({ code: 1006 }))
      act(() => {
        vi.advanceTimersByTime(ms - 1)
      })
      expect(sockets).toHaveLength(before) // not yet
      act(() => {
        vi.advanceTimersByTime(1)
      })
      expect(sockets).toHaveLength(before + 1)
    }
    reconnectAfter(2000)
    reconnectAfter(4000)
    reconnectAfter(8000)
    reconnectAfter(16000)
    reconnectAfter(30000)
    reconnectAfter(30000)
    act(() => send({ type: 'sessions' })) // a good connection
    reconnectAfter(2000)
  })

  it('jitters the delay', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(0)
    const { sockets } = setup()
    act(() => sockets[0].onclose({ code: 1006 }))
    act(() => {
      vi.advanceTimersByTime(1000)
    })
    expect(sockets).toHaveLength(2)
  })

  it('stops retrying on close code 1008 and asks the app to re-check the session', () => {
    vi.useFakeTimers()
    const ended = vi.fn()
    const { sockets } = setup(ended)
    act(() => sockets[0].onclose({ code: 1008 }))
    act(() => {
      vi.advanceTimersByTime(60000)
    })
    expect(ended).toHaveBeenCalledTimes(1)
    expect(sockets).toHaveLength(1)
  })

  it('limits consecutive fast reconnects after 1013', () => {
    vi.useFakeTimers()
    vi.spyOn(Math, 'random').mockReturnValue(1)
    const { sockets } = setup()
    for (let i = 0; i < 5; i++) {
      act(() => sockets.at(-1)!.onclose({ code: 1013 }))
      act(() => {
        vi.advanceTimersByTime(250)
      })
      expect(sockets).toHaveLength(i + 2)
    }
    act(() => sockets.at(-1)!.onclose({ code: 1013 }))
    act(() => {
      vi.advanceTimersByTime(250)
    })
    expect(sockets).toHaveLength(6) // the sixth waits for the normal backoff
  })
})

describe('F10/F13/F14 app', () => {
  const answer = (body: unknown, ok = true) => Promise.resolve({ ok, status: ok ? 200 : 500, json: async () => body })
  function stubSocket() {
    vi.stubGlobal('WebSocket', function (this: object) {
      Object.assign(this, { close() {} })
    })
  }

  it('retries the locations fetch and shows the error meanwhile', async () => {
    vi.useFakeTimers()
    stubSocket()
    let locationCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session') return answer({ loginRequired: false, loggedIn: true })
        if (url === '/api/health') return answer({ version: '1', mqtt: { connected: true } })
        if (url === '/api/locations') return ++locationCalls === 1 ? answer({}, false) : answer({ DOCK: { x: 1, y: 1, zone: 'Z' } })
        return new Promise(() => {})
      }),
    )
    render(<App />)
    await act(() => vi.advanceTimersByTimeAsync(100))
    expect(screen.getByRole('alert').textContent).toMatch(/Could not load/)
    await act(() => vi.advanceTimersByTimeAsync(3100))
    expect(locationCalls).toBe(2)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('shows a failed logout instead of an unhandled rejection', async () => {
    stubSocket()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session') return answer({ loginRequired: true, loggedIn: true })
        if (url === '/api/logout') return answer({ detail: 'nope' }, false)
        if (url === '/api/health') return answer({ version: '1', mqtt: { connected: true } })
        return new Promise(() => {})
      }),
    )
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Log out' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Log out failed: nope/)
  })

  it('stays on the login screen while the backend is unreachable after a login was required', async () => {
    vi.useFakeTimers()
    stubSocket()
    let up = true
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session') return up ? answer({ loginRequired: true, loggedIn: false }) : Promise.reject(new TypeError('down'))
        return new Promise(() => {})
      }),
    )
    render(<App />)
    await act(() => vi.advanceTimersByTimeAsync(10))
    expect(screen.getByLabelText(/Access token/)).toBeTruthy()
    up = false
    await act(() => vi.advanceTimersByTimeAsync(3100))
    expect(screen.getByLabelText(/Access token/)).toBeTruthy()
  })

  it('keeps the page up when /api/health has an unexpected shape', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    stubSocket()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url === '/api/session') return answer({ loginRequired: false, loggedIn: true })
        if (url === '/api/health') return answer({ version: { x: 1 } })
        return new Promise(() => {})
      }),
    )
    render(<App />)
    expect(await screen.findByText('Warehouse')).toBeTruthy()
  })
})

describe('F15/F16 sessions panel', () => {
  beforeEach(() => {
    vi.spyOn(api, 'fetchSessionStorage').mockResolvedValue({ keepDays: 0, maxTotalMb: 0, usedMb: 0, sessions: 0 })
  })
  const session = (sessionId: string) => ({ sessionId, name: null, startedAt: null, messageCount: 1, recording: false, sizeBytes: 1 })
  const panel = (version = 0) => <RecorderPanel recording={null} recordingStopped={null} replay={null} sessionsVersion={version} />

  it('keeps the newest list when answers arrive out of order', async () => {
    const pending: ((list: ReturnType<typeof session>[]) => void)[] = []
    vi.spyOn(api, 'fetchSessions').mockImplementation(() => new Promise((resolve) => pending.push(resolve)))
    const { rerender } = render(panel(0))
    rerender(panel(1))
    await act(async () => pending[1]([session('new')]))
    await act(async () => pending[0]([session('old')]))
    expect(screen.getByText('new')).toBeTruthy()
    expect(screen.queryByText('old')).toBeNull()
  })

  it('says when the list could not be loaded', async () => {
    vi.spyOn(api, 'fetchSessions').mockRejectedValue(new Error('Could not list sessions: 500'))
    render(panel())
    expect(await screen.findByText(/Could not list sessions: 500/)).toBeTruthy()
    expect(screen.queryByText('No sessions recorded yet.')).toBeNull()
  })

  it('encodes the session id in the download link', async () => {
    vi.spyOn(api, 'fetchSessions').mockResolvedValue([session('a b/c')])
    render(panel())
    const link = await screen.findByText('Download')
    expect(link.getAttribute('href')).toBe('/api/sessions/a%20b%2Fc/download')
  })

  it('does not validate the same session twice at once', async () => {
    vi.spyOn(api, 'fetchSessions').mockResolvedValue([session('s1')])
    let finish: (value: unknown) => void = () => {}
    const validate = vi.spyOn(api, 'validateSession').mockReturnValue(new Promise((resolve) => (finish = resolve)) as never)
    render(panel())
    const button = await screen.findByRole('button', { name: /Validate session/ })
    fireEvent.click(button)
    fireEvent.click(button)
    expect(validate).toHaveBeenCalledTimes(1)
    await act(async () => finish('failed'))
  })

  it('refuses a file over the 200 MB limit without sending it', async () => {
    vi.spyOn(api, 'fetchSessions').mockResolvedValue([])
    const upload = vi.spyOn(api, 'uploadSession')
    render(panel())
    const input = screen.getByLabelText('Upload session file')
    const big = new File(['x'], 'big.jsonl')
    Object.defineProperty(big, 'size', { value: 201 * 1024 ** 2 })
    fireEvent.change(input, { target: { files: [big] } })
    expect(await screen.findByText(/limit is 200\.0 MB/)).toBeTruthy()
    expect(upload).not.toHaveBeenCalled()
  })

  it('shows a busy state during upload and ignores a second file', async () => {
    vi.spyOn(api, 'fetchSessions').mockResolvedValue([])
    let finish: (value: unknown) => void = () => {}
    const upload = vi.spyOn(api, 'uploadSession').mockReturnValue(new Promise((resolve) => (finish = resolve)) as never)
    render(panel())
    const input = screen.getByLabelText('Upload session file') as HTMLInputElement
    fireEvent.change(input, { target: { files: [new File(['{}'], 'a.jsonl')] } })
    expect(await screen.findByText('Uploading…')).toBeTruthy()
    expect(input.disabled).toBe(true)
    expect(upload).toHaveBeenCalledTimes(1)
    await act(async () => finish(session('up')))
    expect(screen.queryByText('Uploading…')).toBeNull()
  })
})

describe('F11/F12 nginx.conf', () => {
  const location = (header: string) => {
    const start = conf.indexOf(header)
    expect(start).toBeGreaterThan(-1)
    return conf.slice(start, conf.indexOf('\n  }', start))
  }

  it('caches hashed assets for good, answers a missing asset with 404 and keeps the security headers', () => {
    const assets = location('location /assets/')
    expect(assets).toContain('try_files $uri =404;')
    expect(assets).toContain('max-age=31536000, immutable')
    expect(assets).not.toMatch(/immutable"\s+always/) // a 404 must not be cached for a year
    for (const header of ['Content-Security-Policy', 'X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy']) expect(assets).toContain(header)
  })

  it('revalidates index.html, compresses text and keeps the security headers', () => {
    const root = location('location / {')
    expect(root).toContain('Cache-Control "no-cache"')
    expect(root).toContain('gzip on;')
    for (const header of ['Content-Security-Policy', 'X-Content-Type-Options', 'X-Frame-Options', 'Referrer-Policy']) expect(root).toContain(header)
    expect(conf).toMatch(/gzip_types[^;]*application\/javascript[^;]*image\/svg\+xml/)
  })

  it('sends Connection upgrade only for WebSocket requests', () => {
    expect(conf).toMatch(/map \$http_upgrade \$connection_upgrade \{[^}]*default upgrade;[^}]*'' +close;/)
    expect(conf).toContain('proxy_set_header Connection $connection_upgrade;')
    expect(conf).not.toContain('Connection "upgrade"')
  })

  it('has the long read timeout on the WebSocket only', () => {
    // An idle live feed may stay open for an hour; nothing else may. The upload gets a bounded 300 s to store
    // and check a 200 MB file after its body has arrived.
    expect(conf.match(/proxy_read_timeout 1h;/g)).toHaveLength(1)
    expect(location('location = /api/ws')).toContain('proxy_read_timeout 1h;')
    expect(location('location = /api/sessions/upload')).toContain('proxy_read_timeout 300s;')
    expect(conf.match(/proxy_read_timeout/g)).toHaveLength(2)
  })

  it('limits clients and the login endpoint, and hardens TLS', () => {
    expect(conf).toContain('limit_conn_zone $binary_remote_addr')
    expect(location('location = /api/login')).toContain('limit_req zone=login')
    expect(conf).toContain('ssl_session_tickets off;')
    expect(conf).toMatch(/ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305/)
    expect(conf).not.toMatch(/ssl_ciphers[^;]*(CBC|SHA:|SHA;)/)
  })
})

describe('visualization messages', () => {
  const row = (payload: unknown, topic = 'uagv/v2/ROS2/nav2_01/visualization') => {
    cleanup()
    render(<MessageStream messages={[msg(topic, payload)]} />)
    return screen.getByRole('button', { expanded: false })
  }

  it('summarise position and speed for 2.x and 3.0', () => {
    expect(row({ agvPosition: { x: 1.26, y: 2, theta: 0 }, velocity: { vx: 0.6, vy: 0.8 } }).textContent).toMatch(/vis.*\(1\.3, 2\.0\)\s+1\.0 m\/s/)
    expect(row({ mobileRobotPosition: { x: 3, y: 4 } }).textContent).toMatch(/vis.*\(3\.0, 4\.0\)/)
  })

  it('survive hostile values', () => {
    expect(() => row({ agvPosition: 'x', velocity: { vx: 'fast', vy: {} } })).not.toThrow()
    expect(row({ agvPosition: 'x', velocity: { vx: 'fast', vy: {} } }).textContent).not.toMatch(/m\/s/)
  })
})
