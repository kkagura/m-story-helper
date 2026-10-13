<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getJson } from './api'
import type { HealthResponse, StatusResponse } from './api'
import ScreenCapture from './components/ScreenCapture.vue'
import RecognitionTestPage from './pages/RecognitionTestPage.vue'
import SettingsPage from './pages/SettingsPage.vue'

const health = ref<HealthResponse | null>(null)
const status = ref<StatusResponse | null>(null)
const loading = ref(false)
const error = ref('')
type Page = 'workspace' | 'recognition' | 'settings'
function currentPage(): Page {
  if (window.location.hash === '#settings') return 'settings'
  if (window.location.hash === '#recognition') return 'recognition'
  return 'workspace'
}
const page = ref<Page>(currentPage())
const pageTitles: Record<Page, string> = {
  workspace: '工作台', recognition: '识别测试', settings: '设置',
}
const pageDescriptions: Record<Page, string> = {
  workspace: '本地服务状态 · 窗口共享与预览',
  recognition: '离线截图 · 血蓝比例与角色名称识别',
  settings: '识别区域与参考画面配置',
}
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

function updatePage() {
  page.value = currentPage()
}

onMounted(() => {
  window.addEventListener('hashchange', updatePage)
  void refresh()
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', updatePage)
  disposed = true
  controller?.abort()
})
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <p class="eyebrow">MAPLE VISION LAB</p>
      <h1>视觉研究工作台</h1>
    </header>

    <div class="app-content">
      <aside class="sidebar">
        <nav class="page-navigation" aria-label="主导航">
          <a href="#workspace" :aria-current="page === 'workspace' ? 'page' : undefined">工作台</a>
          <a href="#recognition" :aria-current="page === 'recognition' ? 'page' : undefined">识别测试</a>
          <a href="#settings" :aria-current="page === 'settings' ? 'page' : undefined">设置</a>
        </nav>
      </aside>

      <main class="page-content">
        <header class="page-heading">
          <div>
            <h2>{{ pageTitles[page] }}</h2>
            <p v-if="page !== 'recognition'" class="muted">{{ pageDescriptions[page] }}</p>
          </div>
          <button v-if="page === 'workspace'" :disabled="loading" @click="refresh">
            {{ loading ? '正在检查…' : '刷新状态' }}
          </button>
        </header>

        <SettingsPage v-if="page === 'settings'" />
        <RecognitionTestPage v-else-if="page === 'recognition'" />
        <template v-else>
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

          <ScreenCapture />
        </template>
      </main>
    </div>
  </div>
</template>
