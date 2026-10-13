<script setup lang="ts">
import ScreenshotLab from '../components/ScreenshotLab.vue'
</script>

<template>
  <div class="settings-page">
    <p class="muted settings-introduction">
      上传参考截图，配置血条和蓝条的识别区域。保存后返回工作台，重新选择截图即可使用该配置。
    </p>
    <ScreenshotLab mode="configure" />
  </div>
</template>
