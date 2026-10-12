<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

type CaptureState = 'idle' | 'selecting' | 'sharing' | 'muted' | 'stopped' | 'error'

const video = ref<HTMLVideoElement | null>(null)
const state = ref<CaptureState>('idle')
const pending = ref(false)
const hasStream = ref(false)
const unavailableReason = ref('正在检查浏览器支持…')
const error = ref('')
const notice = ref('')
const sourceType = ref('未知')
const width = ref(0)
const height = ref(0)

let stream: MediaStream | null = null
let detachTrackListeners: (() => void) | null = null
let generation = 0
let disposed = false

const stateLabel = computed(() => ({
  idle: '尚未共享',
  selecting: '等待选择',
  sharing: '正在共享',
  muted: '画面暂不可用',
  stopped: '已停止',
  error: '共享失败',
})[state.value])

function checkSupport(): string {
  if (!window.isSecureContext) {
    return '请通过 localhost、127.0.0.1 或 HTTPS 打开页面后选择窗口。'
  }
  if (typeof navigator.mediaDevices?.getDisplayMedia !== 'function') {
    return '当前浏览器不支持窗口共享，请使用宿主机上的 Chrome 或 Edge。'
  }
  return ''
}

function stopTracks(value: MediaStream) {
  value.getTracks().forEach(track => track.stop())
}

function releaseStream() {
  detachTrackListeners?.()
  detachTrackListeners = null
  if (stream) stopTracks(stream)
  stream = null
  if (video.value) {
    video.value.pause()
    video.value.srcObject = null
  }
  hasStream.value = false
  width.value = 0
  height.value = 0
  sourceType.value = '未知'
}

function stopSharing(message = '已停止共享，可以重新选择窗口。') {
  generation += 1
  releaseStream()
  state.value = 'stopped'
  error.value = ''
  notice.value = message
}

function updateMetadata() {
  const track = stream?.getVideoTracks()[0]
  if (!track) return
  const settings = track.getSettings()
  width.value = video.value?.videoWidth || settings.width || 0
  height.value = video.value?.videoHeight || settings.height || 0
  const surfaces: Record<string, string> = {
    window: '应用窗口',
    browser: '浏览器标签页',
    monitor: '整个屏幕',
  }
  sourceType.value = surfaces[settings.displaySurface ?? ''] ?? '浏览器未提供来源类型'
}

function describeError(cause: unknown): string {
  if (cause instanceof DOMException) {
    switch (cause.name) {
      case 'NotAllowedError':
        return '未获得共享授权。你可能取消了选择，或浏览器禁止了共享；可以重新选择。'
      case 'NotReadableError':
        return '无法读取所选画面，请检查窗口状态或系统的屏幕捕获权限。'
      case 'NotFoundError':
        return '没有找到可共享的窗口或屏幕。'
      case 'InvalidStateError':
        return '请保持页面处于前台，并点击“选择窗口”重新授权。'
      case 'AbortError':
        return '共享启动被中断，请重新选择。'
    }
  }
  return cause instanceof Error ? cause.message : '无法开始共享，请重新选择窗口。'
}

async function selectWindow() {
  if (pending.value || hasStream.value || disposed) return
  unavailableReason.value = checkSupport()
  if (unavailableReason.value) return

  const requestGeneration = ++generation
  pending.value = true
  state.value = 'selecting'
  error.value = ''
  notice.value = '请在浏览器选择器中选择要预览的应用窗口。'

  try {
    // Called directly from the click handler, before any await loses user activation.
    const selected = await navigator.mediaDevices.getDisplayMedia({
      video: { displaySurface: 'window' },
      audio: false,
    })
    // The permission dialog may resolve after navigation/unmount or cancellation.
    if (disposed || generation !== requestGeneration) {
      stopTracks(selected)
      return
    }

    stream = selected
    const track = selected.getVideoTracks()[0]
    if (!track || track.readyState === 'ended') {
      throw new Error('所选来源没有可用的视频轨道，请重新选择。')
    }

    const ended = () => stopSharing('浏览器或共享来源已结束共享。')
    const muted = () => { state.value = 'muted' }
    const unmuted = () => { state.value = 'sharing'; updateMetadata() }
    track.addEventListener('ended', ended)
    track.addEventListener('mute', muted)
    track.addEventListener('unmute', unmuted)
    detachTrackListeners = () => {
      track.removeEventListener('ended', ended)
      track.removeEventListener('mute', muted)
      track.removeEventListener('unmute', unmuted)
    }

    const player = video.value
    if (!player) throw new Error('预览区域尚未就绪，请重新选择。')
    player.srcObject = selected
    hasStream.value = true
    state.value = track.muted ? 'muted' : 'sharing'
    updateMetadata()
    notice.value = ''
    try {
      await player.play()
    } catch {
      if (generation === requestGeneration) {
        throw new Error('浏览器无法播放预览，已释放共享资源，请重新选择。')
      }
    }
  } catch (cause) {
    if (!disposed && generation === requestGeneration) {
      releaseStream()
      state.value = 'error'
      notice.value = ''
      error.value = describeError(cause)
    }
  } finally {
    if (!disposed) pending.value = false
  }
}

function pageExit() {
  stopSharing('页面离开时已停止共享。')
}

onMounted(() => {
  unavailableReason.value = checkSupport()
  window.addEventListener('pagehide', pageExit)
})
onBeforeUnmount(() => {
  disposed = true
  generation += 1
  window.removeEventListener('pagehide', pageExit)
  releaseStream()
})
</script>

<template>
  <section class="workspace card" aria-labelledby="capture-heading">
    <div class="workspace-heading">
      <h2 id="capture-heading">画面工作区</h2>
      <span class="badge" aria-live="polite">{{ stateLabel }}</span>
    </div>
    <div class="capture-actions">
      <button
        :disabled="Boolean(unavailableReason) || pending || hasStream"
        @click="selectWindow"
      >{{ pending ? '等待浏览器选择…' : '选择窗口' }}</button>
      <button class="secondary" :disabled="!hasStream" @click="stopSharing()">停止共享</button>
    </div>

    <p v-if="unavailableReason" class="error" role="alert">{{ unavailableReason }}</p>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" class="detail" role="status">{{ notice }}</p>

    <div class="capture-preview">
      <!-- Always mounted so srcObject can be bound directly; hidden when stopped. -->
      <video
        v-show="hasStream"
        ref="video"
        autoplay muted playsinline
        aria-label="共享画面实时预览"
        @loadedmetadata="updateMetadata"
        @resize="updateMetadata"
      />
      <div v-if="!hasStream" class="capture-empty">
        <p class="placeholder-title">选择一个窗口，开始本地预览</p>
        <p class="muted">每次共享都需要在浏览器选择器中确认。</p>
      </div>
      <p v-if="state === 'muted'" class="capture-muted" role="status">
        共享来源暂时无法提供画面，当前预览可能停留在上一帧。
      </p>
    </div>

    <dl v-if="hasStream" class="capture-metadata" aria-live="polite">
      <div><dt>来源类型</dt><dd>{{ sourceType }}</dd></div>
      <div><dt>画面尺寸</dt><dd>{{ width && height ? `${width} × ${height}` : '等待画面' }}</dd></div>
    </dl>
    <p class="detail">画面仅在当前浏览器预览，尚未发送给 Python，也未进行识别或录制。</p>
  </section>
</template>
