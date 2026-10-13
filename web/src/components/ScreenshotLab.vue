<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { visionRequest } from '../vision'
import type { ImportedImage, ObservationResult, NumericReading, NameReading, Rect, VisionProfile } from '../vision'

const props = withDefaults(defineProps<{ mode?: 'analyze' | 'configure' }>(), { mode: 'analyze' })
const configuring = computed(() => props.mode === 'configure')
const savedProfile = ref('')
const regions = [
  'hp_text', 'mp_text', 'exp_text',
  'player_info', 'player_name', 'player_level', 'player_job',
] as const
type RegionKind = typeof regions[number]
const regionLabels: Record<RegionKind, string> = {
  hp_text: '血量数字（橙框）', mp_text: '蓝量数字（青框）',
  player_info: '角色信息栏（紫框）', player_name: '角色名称（绿框）',
  player_level: '角色等级（粉框）', player_job: '角色职业（棕框）',
  exp_text: '经验数字（浅黄框）',
}

const image = ref<ImportedImage | null>(null)
const profile = ref<VisionProfile | null>(null)
const result = ref<ObservationResult | null>(null)
const target = ref<RegionKind>('hp_text')
const editor = ref<SVGSVGElement | null>(null)
const busy = ref(false)
const analyzing = ref(false)
const ready = ref(false)
const error = ref('')
const notice = ref('')
let controller: AbortController | null = null
let disposed = false
let drag: { x: number; y: number; pointerId: number; target: RegionKind } | null = null

const mismatch = computed(() => image.value && profile.value && (
  image.value.width !== profile.value.reference_size[0]
  || image.value.height !== profile.value.reference_size[1]
))
const canAnalyze = computed(() => image.value && ready.value && profile.value && !busy.value && !mismatch.value)
const preview = computed(() => image.value ? `/api/images/${image.value.image_id}/preview` : '')
const nameRegion = computed(() => {
  const bbox = result.value?.player_name.bbox
  if (bbox) return { x: bbox[0], y: bbox[1], width: bbox[2], height: bbox[3] }
  return profile.value?.player_name ?? null
})
const nameReasons: Record<string, string> = {
  region_not_configured: '尚未配置角色名称区域，请前往设置。',
  reference_size_mismatch: '参考分辨率不匹配。', region_out_of_bounds: '姓名区域越界。',
  ocr_region_too_large: '姓名区域过大，请只框住姓名一行。',
  ocr_dependency_missing: 'OCR 依赖缺失，请安装后端依赖并重启服务。',
  ocr_initialization_failed: 'OCR 加载失败，请检查本地模型/运行库，处理后重启服务。',
  no_text: '未识别到文字，请检查姓名裁剪图。',
  multiple_text_regions: '区域内出现多个文字块，请避开职业、等级，只框住姓名一行。',
  low_confidence: '置信度不足，结果仅供核对，尚未确认为角色姓名。',
  ocr_invalid_output: 'OCR 输出异常。', ocr_failed: 'OCR 执行失败，请检查区域或本地运行环境。',
}
const numberReasons: Record<string, string> = {
  ...nameReasons,
  region_not_configured: '尚未配置数字区域，请前往设置。',
  region_out_of_bounds: '数字区域越界。',
  ocr_region_too_large: '数字区域过大，请只框住当前值/总值。',
  multiple_text_regions: '数字区域有多个文字块，请只框住当前值/总值。',
  low_confidence: '数字置信度不足，暂不采用。',
  invalid_number_format: '无法读取当前值/总值格式。',
  invalid_level: '等级格式异常，请只框住等级数字。',
  invalid_job: '职业文字异常，请只框住职业一行。',
  invalid_experience_format: '经验格式异常，需要经验值及括号内百分比。',
  invalid_experience_range: '经验值或百分比超出范围。',
  invalid_number_range: '数字范围异常，请核对截图。',
}
function numbers(value: NumericReading) {
  return value.status === 'known' ? `${value.current} / ${value.total}` : '未知 / 未知'
}
function numericRatio(value: NumericReading) {
  return value.ratio === null ? '未知' : `${(value.ratio * 100).toFixed(1)}%`
}
function numberReason(value: NumericReading) {
  return value.reason ? numberReasons[value.reason] || value.reason : ''
}
const characterReasons: Record<string, string> = {
  ...numberReasons,
  region_not_configured: '尚未配置该识别区域，请前往设置。',
  region_out_of_bounds: '识别区域越界。',
  ocr_region_too_large: '识别区域过大，请只框住对应一行。',
  no_text: '未读到文字，请检查详情中的裁剪图。',
  multiple_text_regions: '区域内有多个文字块，请调整范围。',
  low_confidence: '置信度不足，暂不采用。',
}
function characterReason(value: NameReading) {
  return value.reason ? characterReasons[value.reason] || value.reason : ''
}
const characterFields = [
  { key: 'player_level', label: '角色等级' },
  { key: 'player_job', label: '角色职业' },
  { key: 'experience', label: '经验值' },
] as const
const extraDiagnostics = computed(() => result.value ? characterFields.map(field => ({
  ...field, reading: result.value![field.key],
})) : [])
function characterValue(key: typeof characterFields[number]['key']) {
  if (!result.value) return analyzing.value ? '识别中…' : '待识别'
  if (result.value[key].status !== 'known') return '未知'
  if (key === 'player_level') return String(result.value.player_level.value)
  if (key === 'player_job') return result.value.player_job.text
  return `${result.value.experience.value}（${result.value.experience.percentage?.toFixed(2)}%）`
}
const dirty = computed(() => configuring.value && profile.value && JSON.stringify(profile.value) !== savedProfile.value)
watch(profile, () => { result.value = null; notice.value = '' }, { deep: true })

async function perform(work: (signal: AbortSignal) => Promise<void>, timeoutMs = 20000) {
  if (busy.value || disposed) return
  busy.value = true
  error.value = ''
  notice.value = ''
  const request = new AbortController()
  controller = request
  const timer = window.setTimeout(() => request.abort(), timeoutMs)
  try { await work(request.signal) }
  catch (cause) {
    if (!disposed) error.value = cause instanceof Error && cause.name === 'AbortError'
      ? '请求超时，请确认后端运行。' : cause instanceof Error ? cause.message : '操作失败。'
  } finally {
    window.clearTimeout(timer)
    if (!disposed) busy.value = false
  }
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (file.size > 10 * 1024 * 1024) { error.value = '请选择不超过 10 MiB 的截图。'; return }
  await perform(async signal => {
    const next = await visionRequest<ImportedImage>('/api/images', {
      method: 'POST', body: file, headers: { 'Content-Type': 'application/octet-stream' }, signal,
    })
    if (disposed) return
    image.value = next
    ready.value = false
    result.value = null
    notice.value = configuring.value
      ? '请选择目标，只框住对应文字一行。'
      : '截图已导入，点击“开始识别”使用已保存的区域配置。'
  })
}

function adoptSize() {
  if (!configuring.value || !image.value || !profile.value) return
  const next: VisionProfile = { ...profile.value, reference_size: [image.value.width, image.value.height] }
  for (const kind of regions) next[kind] = null
  profile.value = next
}

function point(event: PointerEvent) {
  if (!editor.value || !image.value) return null
  const matrix = editor.value.getScreenCTM()
  if (!matrix) return null
  const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(matrix.inverse())
  return { x: Math.round(Math.max(0, Math.min(image.value.width, p.x))),
    y: Math.round(Math.max(0, Math.min(image.value.height, p.y))) }
}

function beginDrag(event: PointerEvent) {
  if (!configuring.value || busy.value || !ready.value || !profile.value || mismatch.value || event.button !== 0) return
  const start = point(event)
  if (!start) return
  editor.value?.setPointerCapture(event.pointerId)
  drag = { ...start, pointerId: event.pointerId, target: target.value }
}

function moveDrag(event: PointerEvent) {
  if (!drag || drag.pointerId !== event.pointerId || !profile.value) return
  const end = point(event)
  if (!end) return
  const width = Math.abs(end.x - drag.x), height = Math.abs(end.y - drag.y)
  if (width >= 2 && height >= 2) profile.value[drag.target] = {
    x: Math.min(drag.x, end.x), y: Math.min(drag.y, end.y), width, height,
  }
}

function endDrag(event: PointerEvent) {
  if (drag?.pointerId !== event.pointerId) return
  moveDrag(event)
  drag = null
  if (editor.value?.hasPointerCapture(event.pointerId)) editor.value.releasePointerCapture(event.pointerId)
}

function editField(kind: RegionKind, field: keyof Rect, event: Event) {
  const region = profile.value?.[kind]
  if (!configuring.value || !region || busy.value) return
  const value = (event.target as HTMLInputElement).valueAsNumber
  if (!Number.isInteger(value)) { error.value = '区域坐标和尺寸必须为整数。'; return }
  region[field] = value
}

function releaseImage() {
  const id = image.value?.image_id
  image.value = null
  ready.value = false
  result.value = null
  drag = null
  if (id) void fetch(`/api/images/${id}`, { method: 'DELETE', keepalive: true }).catch(() => {})
}

function pageExit() {
  controller?.abort()
  releaseImage()
}

async function analyze() {
  const current = image.value
  if (!current || !profile.value || !canAnalyze.value) return
  result.value = null
  analyzing.value = true
  const body = JSON.stringify(profile.value)
  await perform(async signal => {
    const next = await visionRequest<ObservationResult>(`/api/images/${current.image_id}/analyze`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body, signal,
    })
    if (!disposed && image.value?.image_id === next.session_id) result.value = next
  }, 60000)
  analyzing.value = false
}

async function save() {
  if (!configuring.value || !profile.value || !image.value || mismatch.value) return
  const body = JSON.stringify(profile.value)
  await perform(async signal => {
    const saved = await visionRequest<VisionProfile>('/api/vision/profile', {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body, signal,
    })
    if (!disposed) {
      savedProfile.value = JSON.stringify(saved)
      notice.value = '区域已保存。前往识别测试并重新选择截图即可使用。'
    }
  })
}

onMounted(() => {
  window.addEventListener('pagehide', pageExit)
  void perform(async signal => {
    const next = await visionRequest<VisionProfile>('/api/vision/profile', { signal })
    if (!disposed) {
      savedProfile.value = JSON.stringify(next)
      profile.value = next
    }
  })
})
onBeforeUnmount(() => {
  disposed = true
  controller?.abort()
  window.removeEventListener('pagehide', pageExit)
  releaseImage()
})
</script>

<template>
  <section class="screenshot-lab" :class="{ card: configuring }" aria-label="截图识别">
    <div v-if="configuring" class="workspace-heading">
      <h2>识别区域配置</h2>
      <span class="badge">{{ profile ? (dirty ? '有未保存更改' : '已保存配置') : '配置未加载' }}</span>
    </div>
    <div class="capture-actions recognition-toolbar">
      <label class="file-control">{{ configuring ? '参考截图' : '上传截图' }}<input type="file" accept="image/png,image/jpeg" :disabled="busy" @change="upload" /></label>
      <button :disabled="!canAnalyze" @click="analyze">{{ analyzing ? '识别中…' : configuring ? '试识别' : '开始识别' }}</button>
      <button v-if="configuring" class="secondary" :disabled="!image || !profile || busy || Boolean(mismatch)" @click="save">保存区域配置</button>
      <a v-else class="text-link" href="#settings">区域设置</a>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="configuring && notice" class="detail" role="status">{{ notice }}</p>
    <div v-if="mismatch" class="size-warning">
      <p>截图尺寸与配置不同，请重新设置区域。</p>
      <button v-if="configuring" :disabled="busy" @click="adoptSize">使用当前尺寸并清空区域</button>
      <a v-else class="text-link" href="#settings">前往设置</a>
    </div>
    <div class="recognition-layout" :class="{ 'configure-layout': configuring }">
      <div class="recognition-image">
        <div v-if="image && profile" class="roi-editor">
          <fieldset v-if="configuring" :disabled="busy || Boolean(mismatch)">
            <legend>框选目标（也可在下方输入像素坐标）</legend>
            <label v-for="kind in regions" :key="kind"><input v-model="target" type="radio" :value="kind" /> {{ regionLabels[kind] }}</label>
          </fieldset>
          <svg :key="image.image_id" ref="editor" class="screenshot-editor" :class="{ 'read-only': !configuring }" :viewBox="`0 0 ${image.width} ${image.height}`"
            role="img" aria-label="游戏截图与识别区域" @pointerdown="beginDrag" @pointermove="moveDrag"
            @pointerup="endDrag" @pointercancel="drag = null">
            <image :href="preview" :width="image.width" :height="image.height"
              @load="ready = true" @error="ready = false; error = '预览已失效，请重新上传。'" />
            <template v-for="kind in regions" :key="kind">
              <rect v-if="profile[kind]" :x="profile[kind]?.x" :y="profile[kind]?.y"
                :width="profile[kind]?.width" :height="profile[kind]?.height"
                :class="`roi-box roi-${kind}`" vector-effect="non-scaling-stroke" />
            </template>
          </svg>
          <p v-if="configuring" class="detail">{{ image.width }} × {{ image.height }}</p>
          <div v-if="configuring" class="roi-fields">
            <fieldset v-for="kind in regions" :key="kind" :disabled="busy || Boolean(mismatch)">
              <legend>{{ regionLabels[kind] }}</legend>
              <template v-if="profile[kind]">
                <label v-for="field in (['x', 'y', 'width', 'height'] as const)" :key="field">
                  {{ field }}<input :value="profile[kind]?.[field]" type="number" step="1"
                    :min="field === 'x' || field === 'y' ? 0 : 2" @input="editField(kind, field, $event)" />
                </label>
                <button class="secondary" @click="profile[kind] = null">清除</button>
              </template>
              <p v-else class="muted">请选择该目标并拖拽框选。</p>
            </fieldset>
          </div>
        </div>
        <div v-else class="recognition-empty">上传游戏截图</div>
        <fieldset v-if="configuring && profile" class="ocr-options" :disabled="busy">
          <legend>文字与数字 OCR</legend>
          <label>文字最低置信度（姓名/职业）
            <input v-model.number="profile.player_name_min_confidence" type="number" min="0" max="1" step="0.05" />
          </label>
          <label>等级最低置信度
            <input v-model.number="profile.player_level_min_confidence" type="number" min="0" max="1" step="0.05" />
          </label>
          <label>数字最低置信度（血蓝/经验）
            <input v-model.number="profile.numbers_min_confidence" type="number" min="0" max="1" step="0.05" />
          </label>
        </fieldset>
      </div>
      <aside class="card recognition-info" aria-label="识别信息" aria-live="polite" :aria-busy="analyzing">
        <h3>识别信息</h3>
        <dl class="recognition-values">
          <div>
            <dt>角色名称</dt>
            <dd>{{ result ? (result.player_name.status === 'known' ? result.player_name.text : '未知') : analyzing ? '识别中…' : '待识别' }}</dd>
            <dd v-if="result?.player_name.reason" class="reading-note">{{ nameReasons[result.player_name.reason] || result.player_name.reason }}</dd>
          </div>
          <div v-for="kind in (['hp', 'mp'] as const)" :key="kind">
            <dt>{{ kind === 'hp' ? '血量' : '蓝量' }}<span class="value-unit">当前 / 总值</span></dt>
            <dd>{{ result ? numbers(result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers']) : analyzing ? '识别中…' : '待识别' }}</dd>
            <dd v-if="result" class="value-percent">数值比例 {{ numericRatio(result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers']) }}</dd>
            <dd v-if="result && result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].reason" class="reading-note">{{ numberReason(result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers']) }}</dd>
          </div>
          <div v-for="field in characterFields" :key="field.key">
            <dt>{{ field.label }}</dt>
            <dd>{{ characterValue(field.key) }}</dd>
            <dd v-if="result && result[field.key].reason" class="reading-note">{{ characterReason(result[field.key]) }}</dd>
          </div>
        </dl>
        <p v-if="result" class="detail">识别耗时 {{ result.processing_ms }} ms</p>
        <details class="recognition-diagnostics">
          <summary>识别详情</summary>
          <svg v-if="image && nameRegion && !mismatch" class="name-crop"
            :viewBox="`${nameRegion.x} ${nameRegion.y} ${nameRegion.width} ${nameRegion.height}`"
            :width="nameRegion.width" :height="nameRegion.height" role="img" aria-label="角色姓名原图裁剪">
            <image :href="preview" :width="image.width" :height="image.height" />
          </svg>
          <template v-if="result">
            <p v-if="result.player_name.confidence !== null" class="detail">姓名模型置信度 {{ (result.player_name.confidence * 100).toFixed(1) }}%（不是准确率）</p>
            <p v-if="result.player_name.status === 'unknown' && result.player_name.raw_text" class="detail">待核对文字：{{ result.player_name.raw_text }}</p>
            <p class="detail">姓名 {{ result.player_name.processing_ms }} ms · {{ result.player_name.backend }}</p>
            <div v-for="kind in (['hp', 'mp'] as const)" :key="kind">
              <p class="detail">{{ kind === 'hp' ? '血量' : '蓝量' }} OCR：{{ result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].raw_text || '无文字' }} · 置信度 {{ result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].confidence ?? '未知' }}</p>
              <svg v-if="image && result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].bbox && !mismatch" class="name-crop"
                :viewBox="result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].bbox!.join(' ')"
                :width="result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].bbox![2]"
                :height="result[kind === 'hp' ? 'hp_numbers' : 'mp_numbers'].bbox![3]"
                role="img" :aria-label="kind === 'hp' ? '血量数字裁剪' : '蓝量数字裁剪'">
                <image :href="preview" :width="image.width" :height="image.height" />
              </svg>
            </div>
            <div v-for="field in extraDiagnostics" :key="field.key">
              <p class="detail">{{ field.label }} OCR：{{ field.reading.raw_text || '无文字' }} · 置信度 {{ field.reading.confidence ?? '未知' }} · {{ field.reading.processing_ms }} ms</p>
              <svg v-if="image && field.reading.bbox && !mismatch" class="name-crop"
                :viewBox="field.reading.bbox.join(' ')" :width="field.reading.bbox[2]" :height="field.reading.bbox[3]"
                role="img" :aria-label="`${field.label}原图裁剪`">
                <image :href="preview" :width="image.width" :height="image.height" />
              </svg>
            </div>
            <p class="detail">帧 {{ result.frame_id }} · 配置 {{ result.profile_version }}</p>
          </template>
          <p v-if="image" class="detail">截图 {{ image.width }} × {{ image.height }}</p>
          <p v-if="profile" class="detail">参考 {{ profile.reference_size[0] }} × {{ profile.reference_size[1] }}</p>
          <p class="detail">所有信息由本地 OCR 读取，血蓝比例按数值计算。首次 OCR 加载可能较慢。</p>
          <p v-if="configuring" class="detail">每个区域只框住对应文字一行。未保存配置仅用于试识别。</p>
        </details>
      </aside>
    </div>
  </section>
</template>
