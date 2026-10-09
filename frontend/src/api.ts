export type Health = {
  status: string
  version: string
  mqtt: {
    host: string
    port: number
    connected: boolean
  }
}

export async function fetchHealth(): Promise<Health> {
  const response = await fetch('/api/health')
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return response.json()
}
