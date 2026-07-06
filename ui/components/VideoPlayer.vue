<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({
  videoSrc: {
    type: String,
    required: true
  }
})

const videoRef = ref(null)
const canvasRef = ref(null)
const containerRef = ref(null)
const pendingBoxes = ref([])

const updateCanvasSize = () => {
  const video = videoRef.value
  const canvas = canvasRef.value
  const container = containerRef.value
  
  if (!video || !canvas || !container) return
  
  const rect = container.getBoundingClientRect()
  const dpr = window.devicePixelRatio || 1
  
  canvas.style.width = `${rect.width}px`
  canvas.style.height = `${rect.height}px`
  canvas.width = rect.width * dpr
  canvas.height = rect.height * dpr
}

const drawBoxes = (boxes) => {
  const video = videoRef.value
  const canvas = canvasRef.value
  
  if (!video || !canvas) return
  if (!boxes || boxes.length === 0) return
  
  if (!video.videoWidth || !video.videoHeight) {
    pendingBoxes.value = boxes
    return
  }
  
  _drawBoxesInternal(boxes)
}

const _drawBoxesInternal = (boxes) => {
  const video = videoRef.value
  const canvas = canvasRef.value
  
  if (!video || !canvas) return
  
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  
  const videoWidth = video.videoWidth || 1
  const videoHeight = video.videoHeight || 1
  
  const rect = canvas.getBoundingClientRect()
  const scaleX = rect.width * dpr / videoWidth
  const scaleY = rect.height * dpr / videoHeight
  
  boxes.forEach(box => {
    const { x1, y1, x2, y2, label, color } = box
    
    ctx.save()
    ctx.strokeStyle = color || '#ff0000'
    ctx.lineWidth = 2 * dpr
    ctx.strokeRect(
      x1 * scaleX,
      y1 * scaleY,
      (x2 - x1) * scaleX,
      (y2 - y1) * scaleY
    )
    
    ctx.fillStyle = color || '#ff0000'
    ctx.font = `${14 * dpr}px sans-serif`
    ctx.textBaseline = 'top'
    
    const labelWidth = ctx.measureText(label || '').width
    const labelHeight = 18 * dpr
    
    ctx.fillRect(
      x1 * scaleX,
      y1 * scaleY - labelHeight,
      Math.max(labelWidth + 8 * dpr, (x2 - x1) * scaleX),
      labelHeight
    )
    
    ctx.fillStyle = '#ffffff'
    ctx.fillText(label || '', x1 * scaleX + 4 * dpr, y1 * scaleY - labelHeight + 2 * dpr)
    
    ctx.restore()
  })
}

const handleLoadedMetadata = () => {
  updateCanvasSize()
  if (pendingBoxes.value.length > 0) {
    _drawBoxesInternal(pendingBoxes.value)
    pendingBoxes.value = []
  }
}

const handleResize = () => {
  updateCanvasSize()
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
})

watch(() => props.videoSrc, () => {
  updateCanvasSize()
})

defineExpose({
  drawBoxes
})
</script>

<template>
  <div ref="containerRef" class="video-player-container">
    <video
      ref="videoRef"
      class="video-element"
      :src="videoSrc"
      controls
      autoplay
      muted
      playsinline
      @loadedmetadata="handleLoadedMetadata"
    />
    <canvas ref="canvasRef" class="video-canvas" />
  </div>
</template>

<style scoped>
.video-player-container {
  position: relative;
  width: 100%;
  max-width: 900px;
  margin: 0 auto;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

.video-element {
  position: relative;
  width: 100%;
  height: auto;
  display: block;
  z-index: 1;
}

.video-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 2;
  pointer-events: none;
}
</style>