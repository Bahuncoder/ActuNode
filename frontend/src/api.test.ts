import { afterEach, describe, expect, it, vi } from 'vitest'
import { uploadSession } from './api'

afterEach(() => vi.unstubAllGlobals())

describe('uploadSession errors', () => {
  it.each([
    [429, 'Another upload or validation is running'],
    [507, 'Session storage is full; delete sessions first'],
  ])('throws the server detail for %i', async (status, detail) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status })))
    await expect(uploadSession(new File(['x'], 'x.jsonl'))).rejects.toThrow(detail)
  })
})
