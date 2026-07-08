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

const testVideoSrc = '/test-video.mp4'

const latestPlateResult = ref(null)
const plateRecords = ref([])
const vehicleDetectionRecords = ref([])

const trafficDensityData = ref([
  { region_id: 'road_A', vehicle_count: 2, status: 'smooth', color: 'green' },
  { region_id: 'road_B', vehicle_count: 4, status: 'slow', color: 'yellow' },
  { region_id: 'road_C', vehicle_count: 7, status: 'congested', color: 'red' },
  { region_id: 'road_D', vehicle_count: 3, status: 'slow', color: 'yellow' }
])

const illegalParkingRecords = ref([
  {
    event_type: 'illegal_parking',
    timestamp: new Date(Date.now() - 30000).toISOString(),
    device_id: 'mobile_001',
    status: 'warning',
    data: {
      track_id: 'track_001',
      stay_time: 45,
      threshold: 30
    },
    bbox: [200, 150, 220, 170]
  },
  {
    event_type: 'illegal_parking',
    timestamp: new Date(Date.now() - 60000).toISOString(),
    device_id: 'mobile_001',
    status: 'normal',
    data: {
      track_id: 'track_002',
      stay_time: 25,
      threshold: 30
    },
    bbox: [300, 200, 320, 220]
  },
  {
    event_type: 'illegal_parking',
    timestamp: new Date(Date.now() - 90000).toISOString(),
    device_id: 'mobile_001',
    status: 'warning',
    data: {
      track_id: 'track_003',
      stay_time: 55,
      threshold: 30
    },
    bbox: [150, 180, 170, 200]
  }
])

const roadAnomalyRecords = ref([
  {
    event_type: 'road_anomaly',
    timestamp: new Date(Date.now() - 20000).toISOString(),
    device_id: 'mobile_001',
    status: 'warning',
    data: {
      anomaly_type: 'fallen_object',
      affected_lane: 'lane_1',
      duration_frames: 25
    },
    bbox: [300, 200, 320, 220]
  },
  {
    event_type: 'road_anomaly',
    timestamp: new Date(Date.now() - 50000).toISOString(),
    device_id: 'mobile_001',
    status: 'warning',
    data: {
      anomaly_type: 'debris',
      affected_lane: 'lane_2',
      duration_frames: 18
    },
    bbox: [400, 150, 420, 170]
  },
  {
    event_type: 'road_anomaly',
    timestamp: new Date(Date.now() - 80000).toISOString(),
    device_id: 'mobile_001',
    status: 'normal',
    data: {
      anomaly_type: 'unknown_object',
      affected_lane: 'lane_3',
      duration_frames: 35
    },
    bbox: [250, 180, 270, 200]
  }
])

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

const mockPlateData = [
  {
    event_type: 'plate_recognition',
    timestamp: new Date(Date.now() - 30000).toISOString(),
    device_id: 'mobile_001',
    status: 'normal',
    data: {
      plate_number: '京A12345',
      is_in_whitelist: true,
      decision: 'allow'
    }
  },
  {
    event_type: 'plate_recognition',
    timestamp: new Date(Date.now() - 60000).toISOString(),
    device_id: 'mobile_001',
    status: 'warning',
    data: {
      plate_number: '京B67890',
      is_in_whitelist: false,
      decision: 'deny'
    }
  },
  {
    event_type: 'plate_recognition',
    timestamp: new Date(Date.now() - 90000).toISOString(),
    device_id: 'mobile_001',
    status: 'normal',
    data: {
      plate_number: '沪C11223',
      is_in_whitelist: true,
      decision: 'allow'
    }
  }
]

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

  websocketManager.connect('ws://192.168.1.100:5000')

  plateRecords.value = [...mockPlateData]
  if (mockPlateData.length > 0) {
    latestPlateResult.value = mockPlateData[0]
  }

  setTimeout(() => {
    if (videoPlayerRef.value) {
      const testBoxes = [
        { x1: 100, y1: 80, x2: 250, y2: 180, label: '车辆', color: '#ff0000' },
        { x1: 300, y1: 120, x2: 450, y2: 220, label: '行人', color: '#00ff00' },
        { x1: 500, y1: 60, x2: 650, y2: 160, label: '自行车', color: '#0000ff' }
      ]
      videoPlayerRef.value.drawBoxes(testBoxes)
    }
  }, 2000)
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
          <VideoPlayer ref="videoPlayerRef" :video-src="testVideoSrc" />
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
