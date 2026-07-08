<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElTag, ElAlert } from 'element-plus'
import websocketManager from './utils/websocketManager'
import VideoPlayer from './components/VideoPlayer.vue'
import PlateResult from './components/PlateResult.vue'
import TrafficHeatmap from './components/TrafficHeatmap.vue'
import IllegalParkingAlarm from './components/IllegalParkingAlarm.vue'
import RoadAnomalyAlarm from './components/RoadAnomalyAlarm.vue'
import VehicleDetectionPanel from './components/VehicleDetectionPanel.vue'
import SystemMonitor from './components/SystemMonitor.vue'
import DeviceManager from './components/DeviceManager.vue'
import ConfigPanel from './components/ConfigPanel.vue'
import DashboardStats from './components/DashboardStats.vue'

const connectionStatus = ref('未连接')
const reconnectCount = ref(0)
const showError = ref(false)
const errorMessage = ref('')

const videoPlayerRef = ref(null)

const CLOUD_SERVER_URL = import.meta.env.VITE_CLOUD_SERVER_URL || 'http://172.20.10.2:5000'
const liveVideoSrc = import.meta.env.VITE_LIVE_VIDEO_URL || 'http://172.20.10.2:8888/live/mobile_001/index.m3u8'

const latestPlateResult = ref(null)
const plateRecords = ref([])
const vehicleDetectionRecords = ref([])

const trafficDensityData = ref([
  { region_id: 'road_A', vehicle_count: 2, status: 'smooth', color: 'green' },
  { region_id: 'road_B', vehicle_count: 4, status: 'slow', color: 'yellow' },
  { region_id: 'road_C', vehicle_count: 7, status: 'congested', color: 'red' },
  { region_id: 'road_D', vehicle_count: 3, status: 'slow', color: 'yellow' }
])

const illegalParkingRecords = ref([])

const roadAnomalyRecords = ref([])

const systemStatus = ref({})

const dashboardStats = reactive({
  plateCount: 0,
  congestionIndex: 0,
  illegalParkingCount: 0,
  roadAnomalyCount: 0
})

const deviceList = ref([
  {
    device_id: 'mobile_001',
    device_type: 'huawei_tablet',
    scene_id: 'scene_704',
    status: 'online',
    last_heartbeat: new Date(Date.now() - 30000).toISOString()
  },
  {
    device_id: 'mobile_002',
    device_type: 'iphone',
    scene_id: 'scene_705',
    status: 'offline',
    last_heartbeat: new Date(Date.now() - 7200000).toISOString()
  },
  {
    device_id: 'camera_001',
    device_type: 'ip_camera',
    scene_id: 'scene_704',
    status: 'online',
    last_heartbeat: new Date(Date.now() - 60000).toISOString()
  }
])

const statusMap = {
  disconnected: '未连接',
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  error: '连接失败'
}

const statusTypeMap = {
  disconnected: 'danger',
  connecting: 'warning',
  connected: 'success',
  reconnecting: 'warning',
  error: 'danger'
}

const handlePlateRecognition = (data) => {
  latestPlateResult.value = data
  plateRecords.value.unshift(data)
  if (plateRecords.value.length > 10) {
    plateRecords.value = plateRecords.value.slice(0, 10)
  }
  dashboardStats.plateCount++
}

const buildVehicleBoxes = (records) => {
  return records
    .filter(record => Array.isArray(record.bbox) && record.bbox.length === 4)
    .slice(0, 10)
    .map((record, index) => ({
      x1: record.bbox[0],
      y1: record.bbox[1],
      x2: record.bbox[2],
      y2: record.bbox[3],
      label: `${record.data?.vehicle_type || 'vehicle'} ${Math.round((record.data?.confidence || 0) * 100)}%`,
      color: index === 0 ? '#ff4d4f' : '#faad14'
    }))
}

const handleVehicleDetection = (data) => {
  vehicleDetectionRecords.value.unshift(data)
  if (vehicleDetectionRecords.value.length > 20) {
    vehicleDetectionRecords.value = vehicleDetectionRecords.value.slice(0, 20)
  }

  if (videoPlayerRef.value) {
    videoPlayerRef.value.drawBoxes(buildVehicleBoxes(vehicleDetectionRecords.value))
  }
}

const handleTrafficDensity = (data) => {
  if (data.data?.regions) {
    trafficDensityData.value = data.data.regions
    const totalVehicles = data.data.regions.reduce((sum, r) => sum + (r.vehicle_count || 0), 0)
    const avgVehicles = totalVehicles / data.data.regions.length
    dashboardStats.congestionIndex = Math.round(Math.min(100, avgVehicles * 15))
  }
}

const handleIllegalParking = (data) => {
  illegalParkingRecords.value.unshift(data)
  if (illegalParkingRecords.value.length > 20) {
    illegalParkingRecords.value = illegalParkingRecords.value.slice(0, 20)
  }
  dashboardStats.illegalParkingCount++
}

const handleRoadAnomaly = (data) => {
  roadAnomalyRecords.value.unshift(data)
  if (roadAnomalyRecords.value.length > 20) {
    roadAnomalyRecords.value = roadAnomalyRecords.value.slice(0, 20)
  }
  dashboardStats.roadAnomalyCount++
}

const handleSystemStatus = (data) => {
  if (data.data) {
    systemStatus.value = data.data
  }
}

const handleDeviceAdd = (device) => {
  const existingDevice = deviceList.value.find(d => d.device_id === device.device_id)
  if (existingDevice) {
    existingDevice.status = 'online'
    existingDevice.last_heartbeat = device.last_heartbeat
  } else {
    deviceList.value.push(device)
  }
}

const handleSendCommand = (command) => {
  websocketManager.send(command)
}

onMounted(() => {
  websocketManager.onMessage((data) => {
    console.log('WebSocket 消息:', data)
    if (data.event_type === 'vehicle_detection') {
      handleVehicleDetection(data)
    } else if (data.event_type === 'plate_recognition') {
      handlePlateRecognition(data)
    } else if (data.event_type === 'traffic_density') {
      handleTrafficDensity(data)
    } else if (data.event_type === 'illegal_parking') {
      handleIllegalParking(data)
    } else if (data.event_type === 'road_anomaly') {
      handleRoadAnomaly(data)
    } else if (data.event_type === 'system_status') {
      handleSystemStatus(data)
    }
  })

  websocketManager.onStatusChange((status, count) => {
    connectionStatus.value = statusMap[status] || status
    reconnectCount.value = count

    if (status === 'disconnected' && count >= 10) {
      showError.value = true
      errorMessage.value = 'WebSocket 连接失败，已达到最大重试次数'
    } else if (status === 'connected') {
      showError.value = false
    }
  })

  websocketManager.connect(CLOUD_SERVER_URL)
})

onUnmounted(() => {
  websocketManager.disconnect()
})
</script>

<template>
  <div class="app-container">
    <header class="header">
      <div class="header-content">
        <h1>交通监控系统</h1>
        <div class="header-right">
          <div class="status-container">
            <span class="status-label">连接状态：</span>
            <ElTag :type="statusTypeMap[connectionStatus === '已连接' ? 'connected' : connectionStatus === '重连中' ? 'reconnecting' : connectionStatus === '连接中' ? 'connecting' : 'disconnected']" size="large">
              {{ connectionStatus }}
              <span v-if="connectionStatus === '重连中'" class="reconnect-count">
                ({{ reconnectCount }}/{{ websocketManager.maxReconnectAttempts }})
              </span>
            </ElTag>
          </div>
          <ConfigPanel @send-command="handleSendCommand" />
        </div>
      </div>
    </header>

    <main class="main-content">
      <ElAlert
        v-if="showError"
        title="连接错误"
        :description="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />

      <div class="content-grid">
        <div class="video-section">
          <h2>视频监控</h2>
          <VideoPlayer ref="videoPlayerRef" :video-src="liveVideoSrc" />
        </div>

        <div class="plate-section">
          <SystemMonitor :system-data="systemStatus" />
          <VehicleDetectionPanel :records="vehicleDetectionRecords" />
          <PlateResult :latest-result="latestPlateResult" :records="plateRecords" />
          <IllegalParkingAlarm :records="illegalParkingRecords" />
          <RoadAnomalyAlarm :records="roadAnomalyRecords" />
          <DeviceManager :devices="deviceList" @add-device="handleDeviceAdd" />
        </div>
      </div>

      <DashboardStats :stats-data="dashboardStats" />

      <div class="heatmap-section">
        <TrafficHeatmap :data="trafficDensityData" />
      </div>

      <div class="message-area">
        <h2>控制台日志</h2>
        <div class="log-tip">
          <p>WebSocket 消息将在浏览器控制台中打印。</p>
          <p>按 F12 打开开发者工具查看。</p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background-color: #f5f7fa;
}

.header {
  background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
  color: white;
  padding: 16px 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1400px;
  margin: 0 auto;
}

.header h1 {
  font-size: 24px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.status-container {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-label {
  font-size: 14px;
}

.reconnect-count {
  margin-left: 4px;
  font-size: 12px;
}

.main-content {
  max-width: 1400px;
  margin: 24px auto;
  padding: 0 24px;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr 420px;
  gap: 24px;
  margin-top: 16px;
}

.video-section {
  background: white;
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.video-section h2 {
  font-size: 18px;
  color: #303133;
  margin-bottom: 16px;
}

.plate-section {
  display: flex;
  flex-direction: column;
}

@media (max-width: 1200px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}

.heatmap-section {
  margin-top: 16px;
}

.message-area {
  background: white;
  border-radius: 8px;
  padding: 24px;
  margin-top: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.message-area h2 {
  font-size: 18px;
  color: #303133;
  margin-bottom: 16px;
}

.log-tip {
  color: #909399;
  font-size: 14px;
  line-height: 1.8;
}
</style>
