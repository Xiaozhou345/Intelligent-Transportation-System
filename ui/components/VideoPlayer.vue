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
const playbackProtocol = ref('初始化')
let hls = null
let peerConnection = null
let whepResourceUrl = ''
let webrtcFallbackTimer = null

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
  if (whepResourceUrl) {
    fetch(whepResourceUrl, { method: 'DELETE' }).catch(() => {})
    whepResourceUrl = ''
  }
  if (peerConnection) {
    peerConnection.close()
    peerConnection = null
  }
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

  if (props.videoSrc.endsWith('.m3u8')) {
    if (Hls.isSupported()) {
      hls = new Hls({
        lowLatencyMode: true,
        liveSyncDurationCount: 1,
        liveMaxLatencyDurationCount: 3,
        maxLiveSyncPlaybackRate: 1.5,
        maxBufferLength: 5,
        maxMaxBufferLength: 8,
        backBufferLength: 10,
        enableWorker: true
      })
      hls.loadSource(props.videoSrc)
      hls.attachMedia(video)
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        video.play().catch(() => {})
      })
      hls.on(Hls.Events.LEVEL_LOADED, () => {
        const liveSyncPosition = hls.liveSyncPosition
        if (Number.isFinite(liveSyncPosition) && video.currentTime < liveSyncPosition - 3) {
          video.currentTime = liveSyncPosition
        }
      })
      hls.on(Hls.Events.ERROR, (_, data) => {
        console.error('HLS 播放错误:', data)
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
          console.warn('WebRTC 播放长时间断开，回退到 HLS')
          loadHlsSource()
        }
      }, 5000)
      return
    }

    if (pc.connectionState === 'failed') {
      console.warn('WebRTC 播放连接失败，回退到 HLS')
      loadHlsSource()
    }
  }

  const offer = await pc.createOffer()
  await pc.setLocalDescription(offer)
  await waitForIceGathering(pc)

  const response = await fetch(props.webrtcSrc, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/sdp',
      'Accept': 'application/sdp'
    },
    body: pc.localDescription.sdp
  })

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

  if (props.webrtcSrc) {
    try {
      playbackProtocol.value = 'WebRTC连接中'
      const loaded = await loadWebrtcSource()
      if (loaded) return
    } catch (error) {
      console.error('WebRTC 播放失败，回退到 HLS:', error)
    }
  }

  loadHlsSource()
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
  loadVideoSource()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
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

defineExpose({
  drawBoxes
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
    />
    <canvas ref="canvasRef" class="video-canvas" />
  </div>
</template>

<style scoped>
.video-player-container {
  position: relative;
  width: 100%;
  max-width: none;
  margin: 0 auto;
  border-radius: 8px;
  overflow: hidden;
  border: 1px solid rgba(34, 211, 238, 0.3);
  box-shadow: 0 0 0 1px rgba(34, 211, 238, 0.08), 0 24px 60px rgba(2, 8, 23, 0.5);
  background: #0f172a;
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
