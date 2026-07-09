<script setup>
import { computed, onUnmounted, ref } from 'vue'
import { ElAlert, ElButton, ElOption, ElSelect, ElSlider, ElSwitch, ElTag } from 'element-plus'

const props = defineProps({
  whipSrc: {
    type: String,
    required: true
  }
})

const videoRef = ref(null)
const localStream = ref(null)
const peerConnection = ref(null)
const whipResourceUrl = ref('')
const status = ref('idle')
const errorMessage = ref('')
const facingMode = ref('environment')
const targetWidth = ref(640)
const targetFps = ref(15)
const lowBitrateMode = ref(true)

const isSecureContext = window.isSecureContext

const statusText = computed(() => {
  if (status.value === 'camera') return '摄像头已开启'
  if (status.value === 'connecting') return '推流连接中'
  if (status.value === 'publishing') return '正在推流'
  if (status.value === 'error') return '连接异常'
  return '待开始'
})

const statusType = computed(() => {
  if (status.value === 'publishing') return 'success'
  if (status.value === 'connecting' || status.value === 'camera') return 'warning'
  if (status.value === 'error') return 'danger'
  return 'info'
})

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

const preferH264 = (transceiver) => {
  if (!transceiver.setCodecPreferences || !window.RTCRtpSender?.getCapabilities) return

  const capabilities = window.RTCRtpSender.getCapabilities('video')
  if (!capabilities?.codecs?.length) return

  const h264Codecs = capabilities.codecs.filter(codec => codec.mimeType.toLowerCase() === 'video/h264')
  const otherCodecs = capabilities.codecs.filter(codec => codec.mimeType.toLowerCase() !== 'video/h264')

  if (h264Codecs.length > 0) {
    transceiver.setCodecPreferences([...h264Codecs, ...otherCodecs])
  }
}

const applySenderParameters = async (sender) => {
  if (!lowBitrateMode.value || !sender.getParameters) return

  const parameters = sender.getParameters()
  parameters.encodings = parameters.encodings?.length ? parameters.encodings : [{}]
  parameters.encodings[0] = {
    ...parameters.encodings[0],
    maxBitrate: 900_000,
    maxFramerate: targetFps.value
  }

  await sender.setParameters(parameters).catch(() => {})
}

const stopPublishing = async () => {
  if (whipResourceUrl.value) {
    fetch(whipResourceUrl.value, { method: 'DELETE' }).catch(() => {})
    whipResourceUrl.value = ''
  }

  if (peerConnection.value) {
    peerConnection.value.close()
    peerConnection.value = null
  }

  if (localStream.value) {
    status.value = 'camera'
  } else {
    status.value = 'idle'
  }
}

const stopCamera = async () => {
  await stopPublishing()

  if (localStream.value) {
    localStream.value.getTracks().forEach(track => track.stop())
    localStream.value = null
  }

  if (videoRef.value) {
    videoRef.value.srcObject = null
  }

  status.value = 'idle'
}

const startCamera = async () => {
  errorMessage.value = ''

  if (!navigator.mediaDevices?.getUserMedia) {
    errorMessage.value = '当前浏览器不支持摄像头采集'
    status.value = 'error'
    return
  }

  await stopCamera()

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: {
        facingMode: { ideal: facingMode.value },
        width: { ideal: targetWidth.value },
        height: { ideal: Math.round(targetWidth.value * 0.75) },
        frameRate: { ideal: targetFps.value, max: targetFps.value }
      }
    })

    localStream.value = stream
    if (videoRef.value) {
      videoRef.value.srcObject = stream
      await videoRef.value.play().catch(() => {})
    }
    status.value = 'camera'
  } catch (error) {
    errorMessage.value = `摄像头打开失败：${error.message || error}`
    status.value = 'error'
  }
}

const publish = async () => {
  errorMessage.value = ''

  if (!localStream.value) {
    await startCamera()
  }

  if (!localStream.value) return

  await stopPublishing()
  status.value = 'connecting'

  try {
    const pc = new RTCPeerConnection({ iceServers: [] })
    peerConnection.value = pc

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'connected') {
        status.value = 'publishing'
      } else if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
        status.value = 'error'
        errorMessage.value = 'WebRTC 推流连接已断开'
      }
    }

    const [videoTrack] = localStream.value.getVideoTracks()
    const transceiver = pc.addTransceiver(videoTrack, {
      direction: 'sendonly',
      streams: [localStream.value]
    })

    preferH264(transceiver)
    await applySenderParameters(transceiver.sender)

    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    await waitForIceGathering(pc)

    const response = await fetch(props.whipSrc, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/sdp',
        'Accept': 'application/sdp'
      },
      body: pc.localDescription.sdp
    })

    if (!response.ok) {
      throw new Error(`WHIP request failed: ${response.status}`)
    }

    const location = response.headers.get('Location') || ''
    if (location) {
      whipResourceUrl.value = /^https?:\/\//.test(location)
        ? location
        : new URL(location, props.whipSrc).toString()
    }

    const answer = await response.text()
    await pc.setRemoteDescription({ type: 'answer', sdp: answer })
  } catch (error) {
    await stopPublishing()
    errorMessage.value = `推流失败：${error.message || error}`
    status.value = 'error'
  }
}

const switchCamera = async () => {
  facingMode.value = facingMode.value === 'environment' ? 'user' : 'environment'
  await startCamera()
}

onUnmounted(() => {
  stopCamera()
})
</script>

<template>
  <main class="publisher-page">
    <section class="publisher-shell">
      <div class="publisher-header">
        <div>
          <p>Mobile WebRTC Publisher</p>
          <h1>手机低延迟采集</h1>
        </div>
        <ElTag :type="statusType" size="large">{{ statusText }}</ElTag>
      </div>

      <ElAlert
        v-if="!isSecureContext"
        title="需要 HTTPS"
        description="手机浏览器通常只允许 HTTPS 页面调用摄像头；请用 HTTPS 访问本页面，并让 WHIP 地址也使用 HTTPS。"
        type="warning"
        show-icon
        :closable="false"
      />

      <ElAlert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />

      <div class="preview-wrap">
        <video ref="videoRef" autoplay muted playsinline></video>
        <div v-if="!localStream" class="empty-preview">摄像头预览</div>
      </div>

      <div class="control-grid">
        <label>
          摄像头
          <ElSelect v-model="facingMode" size="large" @change="startCamera">
            <ElOption label="后置摄像头" value="environment" />
            <ElOption label="前置摄像头" value="user" />
          </ElSelect>
        </label>

        <label>
          分辨率宽度
          <ElSlider v-model="targetWidth" :min="480" :max="1280" :step="160" :disabled="status === 'publishing'" />
        </label>

        <label>
          帧率
          <ElSlider v-model="targetFps" :min="10" :max="24" :step="1" :disabled="status === 'publishing'" />
        </label>

        <label class="switch-row">
          低码率模式
          <ElSwitch v-model="lowBitrateMode" :disabled="status === 'publishing'" />
        </label>
      </div>

      <div class="actions">
        <ElButton size="large" @click="startCamera">打开摄像头</ElButton>
        <ElButton size="large" @click="switchCamera">切换镜头</ElButton>
        <ElButton size="large" type="primary" :disabled="status === 'publishing'" @click="publish">开始推流</ElButton>
        <ElButton size="large" type="danger" plain @click="stopCamera">停止</ElButton>
      </div>

      <div class="endpoint-list">
        <span>WHIP</span>
        <code>{{ whipSrc }}</code>
      </div>
    </section>
  </main>
</template>

<style scoped>
.publisher-page {
  min-height: 100vh;
  background:
    linear-gradient(135deg, rgba(8, 28, 42, 0.94), rgba(12, 24, 39, 0.98)),
    linear-gradient(90deg, rgba(20, 184, 166, 0.2), rgba(14, 165, 233, 0.18));
  color: #e5f6ff;
  padding: 18px;
}

.publisher-shell {
  width: min(760px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 16px;
}

.publisher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.publisher-header p {
  color: #67e8f9;
  font-size: 13px;
  margin-bottom: 4px;
}

.publisher-header h1 {
  font-size: 28px;
  line-height: 1.2;
}

.preview-wrap {
  position: relative;
  overflow: hidden;
  width: 100%;
  aspect-ratio: 4 / 3;
  border: 1px solid rgba(125, 211, 252, 0.28);
  background: #020617;
}

.preview-wrap video {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.empty-preview {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #93c5fd;
  font-size: 18px;
}

.control-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.control-grid label {
  display: grid;
  gap: 8px;
  color: #cbd5e1;
  font-size: 14px;
}

.switch-row {
  align-items: center;
  grid-template-columns: 1fr auto;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.endpoint-list {
  display: grid;
  gap: 6px;
  color: #94a3b8;
  font-size: 13px;
}

.endpoint-list code {
  overflow-wrap: anywhere;
  color: #bae6fd;
  background: rgba(15, 23, 42, 0.82);
  padding: 10px;
  border: 1px solid rgba(148, 163, 184, 0.24);
}

@media (max-width: 640px) {
  .publisher-page {
    padding: 14px;
  }

  .publisher-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .control-grid {
    grid-template-columns: 1fr;
  }

  .actions .el-button {
    flex: 1 1 calc(50% - 10px);
    margin-left: 0;
  }
}
</style>
