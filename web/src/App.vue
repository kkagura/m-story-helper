<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson } from './api'
import type { HealthResponse, StatusResponse } from './api'

const health = ref<HealthResponse | null>(null)
const status = ref<StatusResponse | null>(null)
const loading = ref(false)
const error = ref('')
let controller: AbortController | null = null
let disposed = false

const connectionLabel = computed(() => {
  if (loading.value) return '检查中'
  if (error.value) return '连接失败'
  return health.value ? '已连接' : '尚未检查'
})

async function refresh() {
  if (loading.value || disposed) return
  loading.value = true
  error.value = ''
  health.value = null
  status.value = null
  controller = new AbortController()
  const timeout = window.setTimeout(() => controller?.abort(), 5000)
  try {
    const [nextHealth, nextStatus] = await Promise.all([
      getJson<HealthResponse>('/api/health', controller.signal),
      getJson<StatusResponse>('/api/status', controller.signal),
    ])
    if (!disposed) {
      health.value = nextHealth
      status.value = nextStatus
    }
  } catch (cause) {
    controller.abort()
    if (!disposed) {
      error.value = cause instanceof Error && cause.name === 'AbortError'
        ? '请求超时，请确认本地服务已启动。'
        : cause instanceof Error ? cause.message : '无法连接本地服务。'
    }
  } finally {
    window.clearTimeout(timeout)
    if (!disposed) loading.value = false
  }
}

onMounted(refresh)
onBeforeUnmount(() => {
  disposed = true
  controller?.abort()
})
</script>

<template>
  <main class="shell">
    <header class="header">
      <div>
        <p class="eyebrow">MAPLE VISION LAB</p>
        <h1>视觉研究工作台</h1>
        <p class="muted">本地服务状态 · P0 项目骨架</p>
      </div>
      <button :disabled="loading" @click="refresh">
        {{ loading ? '正在检查…' : '刷新状态' }}
      </button>
    </header>

    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <section class="stats" aria-label="本地服务状态" aria-live="polite">
      <article class="card">
        <p class="muted">服务连接</p>
        <h2>{{ connectionLabel }}</h2>
        <p class="detail">{{ health ? `版本 ${health.version}` : '等待本地服务响应' }}</p>
      </article>
      <article class="card">
        <p class="muted">引擎状态</p>
        <h2>{{ status ? (status.engine.state === 'idle' ? '空闲' : '已停止') : '—' }}</h2>
        <p class="detail">{{ status ? `服务运行 ${Math.floor(status.engine.uptime_seconds)} 秒` : '尚无状态数据' }}</p>
      </article>
      <article class="card">
        <p class="muted">前端构建</p>
        <h2>{{ status ? (status.web_ui_ready ? '已就绪' : '未构建') : '—' }}</h2>
        <p class="detail">开发页面通过 Vite 访问服务</p>
      </article>
    </section>

    <section class="workspace card">
      <div class="workspace-heading">
        <h2>画面工作区</h2>
        <span class="badge">待接入</span>
      </div>
      <div class="placeholder">
        <p class="placeholder-title">下一步：选择窗口并预览画面</p>
        <p class="muted">窗口共享、视频接收与识别任务将在后续接入。</p>
      </div>
      <p class="detail">当前页面只检查服务状态，尚未采集或传输任何画面。</p>
    </section>
  </main>
</template>
