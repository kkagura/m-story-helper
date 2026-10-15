export interface Rect { x: number; y: number; width: number; height: number }
export interface VisionProfile {
  schema_version: 1
  reference_size: [number, number]
  hp_text: Rect | null
  mp_text: Rect | null
  exp_text: Rect | null
  player_level: Rect | null
  player_job: Rect | null
  player_info: Rect | null
  player_name: Rect | null
  scene: Rect | null
  scene_exclusions: Rect[]
  scene_name_min_confidence: number
  player_name_min_confidence: number
  player_level_min_confidence: number
  numbers_min_confidence: number
  body_template: 'normal' | null
  body_min_score: number
  body_search_width: number
  body_search_height: number
}
export interface ImportedImage { image_id: string; width: number; height: number }
export interface NameReading {
  status: 'known' | 'unknown'
  text: string | null
  raw_text: string | null
  confidence: number | null
  bbox: [number, number, number, number] | null
  reason: string | null
  processing_ms: number
  backend: string
}
export interface NumericReading extends NameReading {
  current: number | null
  total: number | null
  ratio: number | null
}
export interface LevelReading extends NameReading { value: number | null }
export interface ExperienceReading extends NameReading {
  value: number | null
  percentage: number | null
}
export interface SceneNameCandidate { text: string; confidence: number; bbox: [number, number, number, number] }
export interface SceneNameReading {
  status: 'found' | 'not_found' | 'ambiguous' | 'unknown'
  target_name: string | null
  name_bbox: [number, number, number, number] | null
  candidates: SceneNameCandidate[]
  search_bbox: [number, number, number, number] | null
  reason: string | null
  text_count: number
  processing_ms: number
  backend: string
}
export interface BodyCandidate { bbox: [number, number, number, number]; score: number }
export interface BodyReading {
  status: 'found' | 'not_found' | 'ambiguous' | 'unknown'
  bbox: [number, number, number, number] | null
  bottom_center: [number, number] | null
  search_bbox: [number, number, number, number] | null
  score: number | null
  candidates: BodyCandidate[]
  template_id: string | null
  template_version: string | null
  reason: string | null
  processing_ms: number
  method: 'template_matching'
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
  hp_numbers: NumericReading
  mp_numbers: NumericReading
  player_name: NameReading
  player_level: LevelReading
  player_job: NameReading
  experience: ExperienceReading
  scene_name: SceneNameReading
  player_body: BodyReading
}

export async function visionRequest<T>(path: string, options: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  const data = await response.json()
  if (!response.ok) {
    throw new Error(typeof data.detail === 'string' ? data.detail : `请求失败（${response.status}），请检查区域参数。`)
  }
  return data as T
}
