<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import Hls from 'hls.js'

const props = defineProps({
  videoSrc: {
    type: String,
    required: true
  },
  webrtcSrc: {
    type: String,
    default: ''
  },
  analysisMode: {
    type: String,
    default: '车辆检测'
  },
  modelName: {
    type: String,
    default: 'YOLOv11s'
  },
  detectionCount: {
    type: Number,
    default: 0
  },
  latency: {
    type: Number,
    default: 0
  },
  streamStatus: {
    type: String,
    default: '待连接'
  }
})

const videoRef = ref(null)
const canvasRef = ref(null)
const containerRef = ref(null)
const pendingBoxes = ref([])
const pendingSourceSize = ref(null)
const playbackProtocol = ref('初始化')
const videoViewport = ref({ left: 0, top: 0, width: 0, height: 0 })
const showingAnnotatedFrame = ref(false)  // 新增：标记是否正在显示AI处理后的帧
let hls = null
let peerConnection = null
let whepResourceUrl = ''
let webrtcFallbackTimer = null
let webrtcFrameTimer = null
let receivedVideoFrame = false
let playbackWatchdog = null
let lastPlaybackTime = -1
let stalledChecks = 0
let overlayClearTimer = null
const OVERLAY_STALE_MS = 1200

const calculateVideoViewport = () => {
  const video = videoRef.value
  const container = containerRef.value
  if (!video || !container) {
    return { left: 0, top: 0, width: 0, height: 0 }
  }

  const rect = container.getBoundingClientRect()
  const intrinsicWidth = video.videoWidth || 16
  const intrinsicHeight = video.videoHeight || 9
  const scale = Math.min(rect.width / intrinsicWidth, rect.height / intrinsicHeight)
  const renderedWidth = intrinsicWidth * scale
  const renderedHeight = intrinsicHeight * scale

  return {
    left: (rect.width - renderedWidth) / 2,
    top: (rect.height - renderedHeight) / 2,
    width: renderedWidth,
    height: renderedHeight
  }
}

const destroyHls = () => {
  if (hls) {
    hls.destroy()
    hls = null
  }
}

const destroyWebrtc = async () => {
  if (webrtcFallbackTimer) {
    window.clearTimeout(webrtcFallbackTimer)
    webrtcFallbackTimer = null
  }
  if (webrtcFrameTimer) {
    window.clearTimeout(webrtcFrameTimer)
    webrtcFrameTimer = null
  }
  if (whepResourceUrl) {
    fetch(whepResourceUrl, { method: 'DELETE' }).catch(() => {})
    whepResourceUrl = ''
  }
  if (peerConnection) {
    peerConnection.close()
    peerConnection = null
  }
}

const fallbackToHls = async (reason) => {
  console.warn(reason)
  const video = videoRef.value
  const hlsIsAlreadyActive = Boolean(video && !video.srcObject && (hls || video.currentSrc))
  await destroyWebrtc()
  if (hlsIsAlreadyActive) {
    playbackProtocol.value = 'HLS'
  } else {
    loadHlsSource()
  }
}

const markVideoFrameReceived = () => {
  receivedVideoFrame = true
  if (webrtcFrameTimer) {
    window.clearTimeout(webrtcFrameTimer)
    webrtcFrameTimer = null
  }
}

const watchForWebrtcFirstFrame = () => {
  const video = videoRef.value
  if (!video) return

  receivedVideoFrame = false
  if ('requestVideoFrameCallback' in video) {
    video.requestVideoFrameCallback(() => {
      markVideoFrameReceived()
    })
  }

  if (webrtcFrameTimer) {
    window.clearTimeout(webrtcFrameTimer)
  }
  webrtcFrameTimer = window.setTimeout(() => {
    if (playbackProtocol.value !== 'WebRTC' || receivedVideoFrame) return
    fallbackToHls('WebRTC 已连接但未收到可渲染视频帧，回退到 HLS')
  }, 6000)
}

const waitForIceGathering = (pc) => {
  if (pc.iceGatheringState === 'complete') return Promise.resolve()

  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, 1500)
    const checkState = () => {
      if (pc.iceGatheringState === 'complete') {
        window.clearTimeout(timeout)
        pc.removeEventListener('icegatheringstatechange', checkState)
        resolve()
      }
    }
    pc.addEventListener('icegatheringstatechange', checkState)
  })
}

const loadHlsSource = () => {
  const video = videoRef.value
  if (!video) return

  destroyHls()
  video.srcObject = null
  playbackProtocol.value = 'HLS'

  const isHlsSource = (() => {
    try {
      return new URL(props.videoSrc, window.location.href).pathname.endsWith('.m3u8')
    } catch (_) {
      return props.videoSrc.includes('.m3u8')
    }
  })()

  if (isHlsSource) {
    if (Hls.isSupported()) {
      hls = new Hls({
        lowLatencyMode: false,
        liveSyncDurationCount: 2,
        liveMaxLatencyDurationCount: 5,
        maxLiveSyncPlaybackRate: 1.08,
        maxBufferLength: 8,
        maxMaxBufferLength: 12,
        backBufferLength: 4,
        liveDurationInfinity: true,
        highBufferWatchdogPeriod: 1,
        enableWorker: true
      })
      hls.loadSource(props.videoSrc)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {})
      })
      hls.on(Hls.Events.LEVEL_LOADED, () => {
        const liveSyncPosition = hls.liveSyncPosition
        if (Number.isFinite(liveSyncPosition) && video.currentTime < liveSyncPosition - 2) {
          video.currentTime = liveSyncPosition
        }
      })
      hls.on(Hls.Events.ERROR, (_, data) => {
        console.error('HLS 播放错误:', data)
        if (!data.fatal) return
        if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
          window.setTimeout(() => hls?.startLoad(-1), 800)
        } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
          hls.recoverMediaError()
        } else {
          window.setTimeout(loadVideoSource, 1200)
        }
      })
      return
    }

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = props.videoSrc
      video.load()
      video.play().catch(() => {})
      return
    }
  }

  video.src = props.videoSrc
  video.load()
}

const loadWebrtcSource = async () => {
  const video = videoRef.value
  if (!video || !props.webrtcSrc || !window.RTCPeerConnection) return false

  await destroyWebrtc()

  const pc = new RTCPeerConnection({
    iceServers: []
  })
  peerConnection = pc

  pc.addTransceiver('video', { direction: 'recvonly' })

  pc.ontrack = (event) => {
    const [stream] = event.streams
    if (stream && video.srcObject !== stream) {
      destroyHls()
      video.removeAttribute('src')
      video.srcObject = stream
      playbackProtocol.value = 'WebRTC'
      video.play().catch(() => {})
      watchForWebrtcFirstFrame()
    }
  }

  pc.onconnectionstatechange = () => {
    console.info('WebRTC connection state:', pc.connectionState)
    if (pc.connectionState === 'connected' && webrtcFallbackTimer) {
      window.clearTimeout(webrtcFallbackTimer)
      webrtcFallbackTimer = null
      return
    }

    if (pc.connectionState === 'disconnected' && !webrtcFallbackTimer) {
      webrtcFallbackTimer = window.setTimeout(() => {
        if (peerConnection === pc && pc.connectionState === 'disconnected') {
          fallbackToHls('WebRTC 播放长时间断开，回退到 HLS')
        }
      }, 5000)
      return
    }

    if (pc.connectionState === 'failed') {
      fallbackToHls('WebRTC 播放连接失败，回退到 HLS')
    }
  }

  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)
  await waitForIceGathering(pc)

  const requestController = new AbortController()
  const requestTimeout = window.setTimeout(() => requestController.abort(), 4000)
  let response
  try {
    response = await fetch(props.webrtcSrc, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
        'Accept': 'application/sdp'
      },
      body: pc.localDescription.sdp,
      signal: requestController.signal
    })
  } finally {
    window.clearTimeout(requestTimeout)
  }

  if (!response.ok) {
    throw new Error(`WHEP request failed: ${response.status}`)
  }

  whepResourceUrl = response.headers.get('Location') || ''
  if (whepResourceUrl && !/^https?:\/\//.test(whepResourceUrl)) {
    whepResourceUrl = new URL(whepResourceUrl, props.webrtcSrc).toString()
  }

  const answer = await response.text()
  await pc.setRemoteDescription({ type: 'answer', sdp: answer })
  return true
}

const loadVideoSource = async () => {
  const video = videoRef.value
  if (!video) return

  destroyHls()
  await destroyWebrtc()
  video.srcObject = null
  loadHlsSource()

  if (props.webrtcSrc) {
    try {
      playbackProtocol.value = 'HLS / WebRTC连接中'
      const loaded = await loadWebrtcSource()
      if (loaded) return
    } catch (error) {
      console.error('WebRTC 播放失败，回退到 HLS:', error)
      await destroyWebrtc()
      playbackProtocol.value = 'HLS'
    }
  }
}

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
  videoViewport.value = calculateVideoViewport()

  if (pendingBoxes.value.length > 0) {
    _drawBoxesInternal(pendingBoxes.value, pendingSourceSize.value)
  }
}

const clearCanvas = () => {
  const canvas = canvasRef.value
  if (!canvas) return

  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
}

const scheduleOverlayExpiry = () => {
  if (overlayClearTimer) window.clearTimeout(overlayClearTimer)
  overlayClearTimer = window.setTimeout(() => {
    overlayClearTimer = null
    pendingBoxes.value = []
    pendingSourceSize.value = null
    clearCanvas()
  }, OVERLAY_STALE_MS)
}

const drawBoxes = (boxes, sourceSize = null) => {
  const video = videoRef.value
  const canvas = canvasRef.value
  
  if (!video || !canvas) return
  if (!boxes || boxes.length === 0) {
    if (overlayClearTimer) {
      window.clearTimeout(overlayClearTimer)
      overlayClearTimer = null
    }
    pendingBoxes.value = []
    pendingSourceSize.value = null
    clearCanvas()
    return
  }
  
  if (!video.videoWidth || !video.videoHeight) {
    pendingBoxes.value = boxes
    pendingSourceSize.value = sourceSize
    scheduleOverlayExpiry()
    return
  }
  pendingBoxes.value = boxes
  pendingSourceSize.value = sourceSize
  scheduleOverlayExpiry()
  _drawBoxesInternal(boxes, sourceSize)
}

const _drawBoxesInternal = (boxes, sourceSize = null) => {
  const video = videoRef.value
  const canvas = canvasRef.value
  
  if (!video || !canvas) return
  
  const ctx = canvas.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  
  const videoWidth = sourceSize?.width || video.videoWidth || 1
  const videoHeight = sourceSize?.height || video.videoHeight || 1
  const viewport = calculateVideoViewport()
  videoViewport.value = viewport
  const offsetX = viewport.left * dpr
  const offsetY = viewport.top * dpr
  const scaleX = viewport.width * dpr / videoWidth
  const scaleY = viewport.height * dpr / videoHeight
  
  boxes.forEach(box => {
    const { x1, y1, x2, y2, label, color, polygon, fillColor } = box

    if (Array.isArray(polygon) && polygon.length >= 3) {
      const points = polygon.map(([x, y]) => [
        offsetX + x * scaleX,
        offsetY + y * scaleY
      ])
      ctx.save()
      ctx.beginPath()
      ctx.moveTo(points[0][0], points[0][1])
      points.slice(1).forEach(([px, py]) => ctx.lineTo(px, py))
      ctx.closePath()
      ctx.fillStyle = fillColor || 'rgba(239, 68, 68, 0.16)'
      ctx.strokeStyle = color || '#ef4444'
      ctx.lineWidth = 2 * dpr
      ctx.fill()
      ctx.stroke()

      if (label) {
        ctx.font = `${14 * dpr}px sans-serif`
        ctx.textBaseline = 'top'
        const labelX = Math.min(...points.map(point => point[0]))
        const labelY = Math.min(...points.map(point => point[1]))
        const labelWidth = ctx.measureText(label).width
        const labelHeight = 18 * dpr
        ctx.fillStyle = color || '#ef4444'
        ctx.fillRect(labelX, Math.max(offsetY, labelY - labelHeight), labelWidth + 8 * dpr, labelHeight)
        ctx.fillStyle = '#ffffff'
        ctx.fillText(label, labelX + 4 * dpr, Math.max(offsetY, labelY - labelHeight) + 2 * dpr)
      }

      ctx.restore()
      return
    }

    const boxX = offsetX + x1 * scaleX
    const boxY = offsetY + y1 * scaleY
    const boxWidth = (x2 - x1) * scaleX
    const boxHeight = (y2 - y1) * scaleY
    
    ctx.save()
    ctx.strokeStyle = color || '#ff0000'
    ctx.lineWidth = 2 * dpr
    ctx.strokeRect(boxX, boxY, boxWidth, boxHeight)
    
    ctx.fillStyle = color || '#ff0000'
    ctx.font = `${14 * dpr}px sans-serif`
    ctx.textBaseline = 'top'
    
    const labelWidth = ctx.measureText(label || '').width
    const labelHeight = 18 * dpr
    
    ctx.fillRect(
      boxX,
      Math.max(offsetY, boxY - labelHeight),
      Math.max(labelWidth + 8 * dpr, boxWidth),
      labelHeight
    )
    
    ctx.fillStyle = '#ffffff'
    ctx.fillText(label || '', boxX + 4 * dpr, Math.max(offsetY, boxY - labelHeight) + 2 * dpr)
    
    ctx.restore()
  })
}

const handleLoadedMetadata = () => {
  updateCanvasSize()
  if (pendingBoxes.value.length > 0) {
    _drawBoxesInternal(pendingBoxes.value, pendingSourceSize.value)
  }
}

const handleLoadedData = () => {
  markVideoFrameReceived()
}

const handleResize = () => {
  updateCanvasSize()
}

const startPlaybackWatchdog = () => {
  if (playbackWatchdog) window.clearInterval(playbackWatchdog)
  lastPlaybackTime = -1
  stalledChecks = 0
  playbackWatchdog = window.setInterval(() => {
    const video = videoRef.value
    if (!video || video.paused || video.ended || document.hidden) return

    if (video.readyState >= 2 && Math.abs(video.currentTime - lastPlaybackTime) > 0.01) {
      lastPlaybackTime = video.currentTime
      stalledChecks = 0
      return
    }

    stalledChecks += 1
    const maxStalledChecks = playbackProtocol.value.startsWith('HLS') ? 5 : 3
    if (stalledChecks < maxStalledChecks) return
    stalledChecks = 0
    console.warn('视频连续卡顿，正在重建播放连接')
    loadVideoSource()
  }, 3000)
}

onMounted(() => {
  loadVideoSource()
  startPlaybackWatchdog()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  if (playbackWatchdog) window.clearInterval(playbackWatchdog)
  if (overlayClearTimer) window.clearTimeout(overlayClearTimer)
  destroyHls()
  destroyWebrtc()
  window.removeEventListener('resize', handleResize)
})

watch(() => props.videoSrc, async () => {
  await nextTick()
  loadVideoSource()
  updateCanvasSize()
})

watch(() => props.webrtcSrc, async () => {
  await nextTick()
  loadVideoSource()
  updateCanvasSize()
})

// 新增：显示后端已绘制好的帧（优化版：使用 requestAnimationFrame 和离屏渲染）
let pendingFrameUrl = null
let isRendering = false

const showAnnotatedFrame = (imageUrl, sequence) => {
  const canvas = canvasRef.value
  const video = videoRef.value
  if (!canvas) {
    URL.revokeObjectURL(imageUrl)
    return
  }

  // 如果有待处理的旧帧，释放它
  if (pendingFrameUrl) {
    URL.revokeObjectURL(pendingFrameUrl)
  }
  pendingFrameUrl = imageUrl

  // 标记正在显示AI处理后的帧
  showingAnnotatedFrame.value = true

  // 将video元素设置为不可见（但不停止播放，以便未来可以切换回去）
  if (video && video.style.opacity !== '0') {
    video.style.opacity = '0'
  }

  // 如果正在渲染，等下一轮
  if (isRendering) {
    return
  }

  isRendering = true

  // 使用 requestAnimationFrame 确保在浏览器重绘前更新
  requestAnimationFrame(() => {
    const currentUrl = pendingFrameUrl
    if (!currentUrl) {
      isRendering = false
      return
    }
    pendingFrameUrl = null

    const img = new Image()
    img.onload = () => {
      const ctx = canvas.getContext('2d', { alpha: false })  // 禁用 alpha 通道加速渲染

      // 使用 willReadFrequently 优化（如果需要频繁读取像素数据）
      // const ctx = canvas.getContext('2d', { alpha: false, willReadFrequently: false })

      // 计算缩放比例以适应canvas
      const scale = Math.min(
        canvas.width / img.width,
        canvas.height / img.height
      )

      const scaledWidth = img.width * scale
      const scaledHeight = img.height * scale

      // 居中绘制
      const x = (canvas.width - scaledWidth) / 2
      const y = (canvas.height - scaledHeight) / 2

      // 清空画布（使用 clearRect 比 fillRect 快）
      ctx.clearRect(0, 0, canvas.width, canvas.height)

      // 如果需要黑色背景（可选）
      if (x > 0 || y > 0) {
        ctx.fillStyle = '#000000'
        ctx.fillRect(0, 0, canvas.width, canvas.height)
      }

      // 使用 imageSmoothingEnabled 控制缩放质量
      ctx.imageSmoothingEnabled = true
      ctx.imageSmoothingQuality = 'low'  // 'low' 最快，'high' 最慢

      ctx.drawImage(img, x, y, scaledWidth, scaledHeight)

      // 释放URL
      URL.revokeObjectURL(currentUrl)
      isRendering = false

      // 如果有新帧在等待，立即处理
      if (pendingFrameUrl) {
        showAnnotatedFrame(pendingFrameUrl, sequence + 1)
      }
    }
    img.onerror = () => {
      console.error('图像加载失败')
      URL.revokeObjectURL(currentUrl)
      isRendering = false
    }
    img.src = currentUrl
  })
}

defineExpose({
  drawBoxes,
  showAnnotatedFrame
})
</script>

<template>
  <div ref="containerRef" class="video-player-container">
    <div class="video-status-bar">
      <div class="status-left">
        <span class="live-dot"></span>
        <strong>{{ analysisMode }}</strong>
        <span>{{ modelName }}</span>
      </div>
      <div class="status-metrics">
        <span>目标 {{ detectionCount }}</span>
        <span>延迟 {{ latency }}ms</span>
        <span>{{ playbackProtocol }}</span>
        <span>{{ streamStatus }}</span>
      </div>
    </div>
    <video
      ref="videoRef"
      class="video-element"
      controls
      autoplay
      muted
      playsinline
      @loadedmetadata="handleLoadedMetadata"
      @loadeddata="handleLoadedData"
    />
    <div class="video-frame-guide" aria-hidden="true">
      <span></span>
      <span></span>
      <span></span>
      <span></span>
    </div>
    <canvas ref="canvasRef" class="video-canvas" />
  </div>
</template>

<style scoped>
.video-player-container {
  position: relative;
  width: 100%;
  max-width: none;
  margin: 0 auto;
  aspect-ratio: 16 / 9;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(34, 211, 238, 0.3);
  box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.08), 0 24px 60px rgba(2, 8, 23, 0.5);
  background: #0f172a;
}

.video-element {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
  object-fit: contain;
  z-index: 1;
}

.video-frame-guide {
  position: absolute;
  inset: 0;
  z-index: 2;
  pointer-events: none;
}

.video-frame-guide span {
  position: absolute;
  width: 42px;
  height: 30px;
  border-color: rgba(34, 211, 238, 0.7);
  border-style: solid;
}

.video-frame-guide span:nth-child(1) {
  left: 14px;
  top: 50px;
  border-width: 2px 0 0 2px;
}

.video-frame-guide span:nth-child(2) {
  right: 14px;
  top: 50px;
  border-width: 2px 2px 0 0;
}

.video-frame-guide span:nth-child(3) {
  right: 14px;
  bottom: 14px;
  border-width: 0 2px 2px 0;
}

.video-frame-guide span:nth-child(4) {
  left: 14px;
  bottom: 14px;
  border-width: 0 0 2px 2px;
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

.video-status-bar {
  align-items: center;
  background: linear-gradient(90deg, rgba(8, 18, 33, 0.94), rgba(14, 116, 144, 0.42));
  border-bottom: 1px solid rgba(34, 211, 238, 0.24);
  color: #ffffff;
  display: flex;
  gap: 12px;
  justify-content: space-between;
  left: 0;
  padding: 10px 12px;
  position: absolute;
  right: 0;
  top: 0;
  z-index: 3;
}

.status-left,
.status-metrics {
  align-items: center;
  display: flex;
  gap: 10px;
  min-width: 0;
}

.status-left strong {
  color: #e0f2fe;
  font-size: 14px;
}

.status-left span,
.status-metrics span {
  color: #bae6fd;
  font-size: 12px;
  white-space: nowrap;
}

.live-dot {
  animation: pulse 1.5s infinite;
  background: #22c55e;
  border-radius: 50%;
  height: 8px;
  width: 8px;
}

@keyframes pulse {
  0% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0.5);
  }
  70% {
    box-shadow: 0 0 0 8px rgba(34, 197, 94, 0);
  }
  100% {
    box-shadow: 0 0 0 0 rgba(34, 197, 94, 0);
  }
}

@media (max-width: 720px) {
  .video-status-bar {
    align-items: flex-start;
    flex-direction: column;
  }

  .status-metrics {
    flex-wrap: wrap;
  }
}
</style>
