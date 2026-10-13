export interface Rect { x: number; y: number; width: number; height: number }
export interface VisionProfile {
  schema_version: 1
  reference_size: [number, number]
  hp: Rect | null
  mp: Rect | null
  exp: Rect | null
  min_channel: number
  min_color_difference: number
  min_column_fraction: number
  min_continuity: number
}
export interface ImportedImage { image_id: string; width: number; height: number }
export interface BarReading {
  status: 'known' | 'unknown'
  ratio: number | null
  bbox: [number, number, number, number] | null
  quality: number
  reason: string | null
}
export interface ObservationResult {
  observation_id: string
  session_id: string
  frame_id: number
  size_version: number
  source: 'screenshot' | 'webrtc'
  source_size: [number, number]
  profile_version: string
  processing_ms: number
  hp: BarReading
  mp: BarReading
}

export async function visionRequest<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  const data = await response.json()
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}），请检查区域参数。`)
  }
  return data as T
}
