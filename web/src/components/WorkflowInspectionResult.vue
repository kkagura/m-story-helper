<script setup lang="ts">
import type { WorkflowInspection } from '../vision'

defineProps<{ reading: WorkflowInspection | null; loading: boolean; selectedName: string }>()
const statuses = { found: '已识别', not_found: '未找到', ambiguous: '存在歧义', unknown: '未知' }
function display(value: string | number | boolean | null) {
  return value === null ? '未知' : typeof value === 'boolean' ? (value ? '是' : '否') : String(value)
}
</script>

<template>
  <section class="dialogue-result" aria-label="流程单步判断结果">
    <h3>流程信息</h3>
    <p class="dialogue-status">{{ loading ? '识别中…' : reading ? statuses[reading.status] : selectedName ? '待识别' : '未选择流程，仅识别基础信息' }}</p>
    <template v-if="reading && !loading">
      <p class="detail">{{ selectedName }} · {{ reading.plugin_version }}</p>
      <dl class="dialogue-values">
        <div><dt>当前阶段</dt><dd>{{ reading.stage_label }}</dd></div>
        <div v-for="field in reading.fields" :key="field.key"><dt>{{ field.label }}</dt><dd>{{ display(field.value) }}</dd></div>
        <div><dt>下一步意图</dt><dd>{{ reading.intent?.label || '暂停，等待明确证据' }}</dd></div>
      </dl>
      <p v-if="reading.intent" class="detail">依据：{{ reading.intent.reason }}</p>
      <ul v-if="reading.missing_conditions.length" class="dialogue-options reading-note">
        <li v-for="condition in reading.missing_conditions" :key="condition">{{ condition }}</li>
      </ul>
      <p class="detail">只读预览，不授予执行许可。</p>
      <details class="recognition-diagnostics">
        <summary>依据与诊断 · {{ reading.processing_ms }} ms</summary>
        <p v-for="(message, index) in reading.diagnostics" :key="index" class="detail">{{ message }}</p>
        <ul class="dialogue-options"><li v-for="box in reading.annotations" :key="box.id">{{ box.label }} · {{ box.bbox.join(', ') }}</li></ul>
      </details>
    </template>
  </section>
</template>
