<script setup lang="ts">
import ScreenshotLab from '../components/ScreenshotLab.vue'
</script>

<template>
  <div class="settings-page">
    <p class="muted settings-introduction">
      上传参考截图，配置血蓝、经验条和角色信息区域。保存后前往识别测试，重新选择截图即可使用。
    </p>
    <ScreenshotLab mode="configure" />
  </div>
</template>
