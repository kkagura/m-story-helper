export interface HealthResponse {
  status: 'ok'
  version: string
}

export interface StatusResponse {
  engine: {
    state: 'idle' | 'stopped'
    uptime_seconds: number
    capabilities: {
      capture: boolean
      vision: boolean
      planning: boolean
      input: boolean
    }
  }
  web_ui_ready: boolean
}

export async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, cache: 'no-store' })
  if (!response.ok) {
    throw new Error(`服务请求失败（HTTP ${response.status}）`)
  }
  return response.json() as Promise<T>
}
