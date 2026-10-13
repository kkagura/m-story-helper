<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { visionRequest } from '../vision'
import type { BarReading, ImportedImage, ObservationResult, Rect, VisionProfile } from '../vision'

const props = withDefaults(defineProps<{ mode?: 'analyze' | 'configure' }>(), { mode: 'analyze' })
const configuring = computed(() => props.mode === 'configure')
const savedProfile = ref('')

const image = ref<ImportedImage | null>(null)
const profile = ref<VisionProfile | null>(null)
const result = ref<ObservationResult | null>(null)
const target = ref<'hp' | 'mp' | 'exp'>('hp')
const editor = ref<SVGSVGElement | null>(null)
const busy = ref(false)
const ready = ref(false)
const error = ref('')
const notice = ref('')
let controller: AbortController | null = null
let disposed = false
let drag: { x: number; y: number; pointerId: number; target: 'hp' | 'mp' | 'exp' } | null = null

const mismatch = computed(() => image.value && profile.value && (
  image.value.width !== profile.value.reference_size[0]
  || image.value.height !== profile.value.reference_size[1]
))
const canAnalyze = computed(() => image.value && ready.value && profile.value && !busy.value && !mismatch.value)
const preview = computed(() => image.value ? `/api/images/${image.value.image_id}/preview` : '')
const dirty = computed(() => configuring.value && profile.value && JSON.stringify(profile.value) !== savedProfile.value)
watch(profile, () => { result.value = null; notice.value = '' }, { deep: true })

async function perform(work: (signal: AbortSignal) => Promise<void>) {
  if (busy.value || disposed) return
  busy.value = true
  error.value = ''
  notice.value = ''
  const request = new AbortController()
  controller = request
  const timer = window.setTimeout(() => request.abort(), 20000)
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
      ? '拖拽框选血条/蓝条/经验条完整内部长度，避开边框和文字。'
      : '截图已导入，点击“识别血蓝”使用已保存的区域配置。'
  })
}

function adoptSize() {
  if (!configuring.value || !image.value || !profile.value) return
  profile.value = { ...profile.value, reference_size: [image.value.width, image.value.height], hp: null, mp: null, exp: null }
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

function editField(kind: 'hp' | 'mp' | 'exp', field: keyof Rect, event: Event) {
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
  const body = JSON.stringify(profile.value)
  await perform(async signal => {
    const next = await visionRequest<ObservationResult>(`/api/images/${current.image_id}/analyze`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body, signal,
    })
    if (!disposed && image.value?.image_id === next.session_id) result.value = next
  })
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
      notice.value = '区域已保存。返回工作台并重新选择截图即可使用。'
    }
  })
}

function reading(value: BarReading) {
  return value.ratio === null ? '未知' : `${(value.ratio * 100).toFixed(1)}%`
}
function reason(value: BarReading) {
  const reasons: Record<string, string> = {
    region_not_configured: '尚未配置区域', reference_size_mismatch: '参考分辨率不匹配',
    region_out_of_bounds: '区域越界', no_fill_color: '没有有效填充颜色，无法确认空条',
    fill_not_left_aligned: '填充不是从左侧开始', fill_not_contiguous: '颜色不连续，请检查区域',
  }
  return value.reason ? reasons[value.reason] || value.reason : `连续性评分 ${value.quality.toFixed(2)}（不是准确率）`
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
  <section class="card screenshot-lab" aria-labelledby="screenshot-heading">
    <div class="workspace-heading">
      <h2 id="screenshot-heading">{{ configuring ? '色条区域配置' : '离线截图调试' }}</h2>
      <span class="badge">{{ configuring ? (profile ? (dirty ? '有未保存更改' : '已保存配置') : '配置未加载') : '本地识别' }}</span>
    </div>
    <p class="detail">{{ configuring ? '选择参考截图，在画面上框选区域并保存；未保存更改仅用于此页试识别。' : '选择 samples 中的 PNG/JPEG，使用设置页保存的区域识别。' }}</p>
    <p v-if="profile" class="detail">配置参考尺寸：{{ profile.reference_size[0] }} × {{ profile.reference_size[1] }}</p>
    <div class="capture-actions">
      <label class="file-control">{{ configuring ? '选择参考截图' : '选择截图' }}<input type="file" accept="image/png,image/jpeg" :disabled="busy" @change="upload" /></label>
      <button :disabled="!canAnalyze" @click="analyze">{{ busy ? '处理中…' : configuring ? '试识别' : '识别血蓝' }}</button>
      <button v-if="configuring" class="secondary" :disabled="!image || !profile || busy || Boolean(mismatch)" @click="save">保存区域配置</button>
      <a v-else class="text-link" href="#settings">配置识别区域 →</a>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="detail" role="status">{{ notice }}</p>
    <div v-if="mismatch" class="size-warning">
      <p>当前截图与配置参考尺寸不同，请在设置页重新配置，不会自动缩放旧区域。</p>
      <button v-if="configuring" :disabled="busy" @click="adoptSize">使用当前尺寸并清空区域</button>
      <a v-else class="text-link" href="#settings">前往设置</a>
    </div>
    <div v-if="image && profile" class="roi-editor">
      <fieldset v-if="configuring" :disabled="busy || Boolean(mismatch)">
        <legend>框选目标（也可在下方输入像素坐标）</legend>
        <label><input v-model="target" type="radio" value="hp" /> 血条</label>
        <label><input v-model="target" type="radio" value="mp" /> 蓝条</label>
        <label><input v-model="target" type="radio" value="exp" /> 经验条</label>
      </fieldset>
      <svg :key="image.image_id" ref="editor" class="screenshot-editor" :class="{ 'read-only': !configuring }" :viewBox="`0 0 ${image.width} ${image.height}`"
        role="img" aria-label="游戏截图与血蓝及经验条区域" @pointerdown="beginDrag" @pointermove="moveDrag"
        @pointerup="endDrag" @pointercancel="drag = null">
        <image :href="preview" :width="image.width" :height="image.height"
          @load="ready = true" @error="ready = false; error = '预览已失效，请重新上传。'" />
        <template v-for="kind in (['hp', 'mp', 'exp'] as const)" :key="kind">
          <rect v-if="profile[kind]" :x="profile[kind]?.x" :y="profile[kind]?.y"
            :width="profile[kind]?.width" :height="profile[kind]?.height"
            :class="`roi-box roi-${kind}`" vector-effect="non-scaling-stroke" />
        </template>
      </svg>
      <p class="detail">源图 {{ image.width }} × {{ image.height }} · 图片编号 {{ image.image_id }}</p>
      <div v-if="configuring" class="roi-fields">
        <fieldset v-for="kind in (['hp', 'mp', 'exp'] as const)" :key="kind" :disabled="busy || Boolean(mismatch)">
          <legend>{{ kind === 'hp' ? '血条（红框）' : kind === 'mp' ? '蓝条（蓝框）' : '经验条（黄框）' }}</legend>
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
    <div v-if="result" class="stats recognition-results" aria-live="polite">
      <article v-for="kind in (['hp', 'mp'] as const)" :key="kind" class="card">
        <p class="muted">{{ kind === 'hp' ? '血量比例' : '蓝量比例' }}</p>
        <h2>{{ reading(result[kind]) }}</h2><p class="detail">{{ reason(result[kind]) }}</p>
      </article>
      <article class="card"><p class="muted">识别记录</p><p class="detail">{{ result.processing_ms }} ms · 帧 {{ result.frame_id }}<br />配置 {{ result.profile_version }}</p></article>
    </div>
    <p class="detail">经验条目前仅配置和展示区域，尚不计算经验比例。</p>
    <p class="detail">当前算法估算色条填充长度，不读取数字；无填充颜色时显示未知，尚不能可靠区分真实零值与错误区域。</p>
  </section>
</template>
