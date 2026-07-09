<script setup>
import { computed, ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElAlert, ElTabPane, ElTabs, ElTag } from 'element-plus'
import websocketManager from './utils/websocketManager'
import VideoPlayer from './components/VideoPlayer.vue'
import CameraPublisher from './components/CameraPublisher.vue'
import PlateResult from './components/PlateResult.vue'
import TrafficHeatmap from './components/TrafficHeatmap.vue'
import IllegalParkingAlarm from './components/IllegalParkingAlarm.vue'
import RoadAnomalyAlarm from './components/RoadAnomalyAlarm.vue'
import VehicleDetectionPanel from './components/VehicleDetectionPanel.vue'
import SystemMonitor from './components/SystemMonitor.vue'
import DeviceManager from './components/DeviceManager.vue'
import ConfigPanel from './components/ConfigPanel.vue'
import DashboardStats from './components/DashboardStats.vue'
import CloudEdgeStatus from './components/CloudEdgeStatus.vue'
import EventStream from './components/EventStream.vue'
import HistoryQuery from './components/HistoryQuery.vue'
import WhitelistManager from './components/WhitelistManager.vue'
import UserSessionPanel from './components/UserSessionPanel.vue'
import AlarmWorkbench from './components/AlarmWorkbench.vue'
import DemoChecklist from './components/DemoChecklist.vue'

const connectionStatus = ref('未连接')
const reconnectCount = ref(0)
const showError = ref(false)
const errorMessage = ref('')
const activeScene = ref('vehicle_detection')
const eventRecords = ref([])
const latestLatency = ref(0)
const currentTime = ref(new Date())
let clockTimer = null

const videoPlayerRef = ref(null)

const CLOUD_SERVER_URL = import.meta.env.VITE_CLOUD_SERVER_URL || 'http://106.54.10.11:15000'
const liveVideoSrc = import.meta.env.VITE_LIVE_VIDEO_URL || 'http://106.54.10.11:8888/live/mobile_001/index.m3u8'
const liveWebrtcSrc = import.meta.env.VITE_LIVE_WEBRTC_URL || 'http://106.54.10.11:8889/live/mobile_001/whep'
const liveWhipSrc = import.meta.env.VITE_LIVE_WHIP_URL || 'http://106.54.10.11:8889/live/mobile_001/whip'
const isPublisherMode = window.location.pathname === '/publish' || new URLSearchParams(window.location.search).get('mode') === 'publisher'

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
const currentUser = ref(null)
const showLoginDialog = ref(false)
const alarmDispositionRecords = ref([])

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

const sceneTabs = [
  { label: '车辆检测', value: 'vehicle_detection', model: 'YOLOv11s' },
  { label: '车牌识别', value: 'plate_recognition', model: 'PlateOCR-v2' },
  { label: '拥堵热力', value: 'traffic_density', model: 'DensityMap' },
  { label: '违停检测', value: 'illegal_parking', model: 'Tracker + Rule' },
  { label: '道路异常', value: 'road_anomaly', model: 'AnomalyNet' }
]

const statusMap = {
  disconnected: '未连接',
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  error: '连接失败',
  simulating: '演示模式'
}

const statusTypeMap = {
  未连接: 'danger',
  连接中: 'warning',
  已连接: 'success',
  重连中: 'warning',
  连接失败: 'danger',
  演示模式: 'warning'
}

const roleTextMap = {
  admin: '管理员',
  operator: '值班员',
  viewer: '访客'
}

const activeSceneMeta = computed(() => {
  return sceneTabs.find(scene => scene.value === activeScene.value) || sceneTabs[0]
})

const onlineDeviceCount = computed(() => deviceList.value.filter(device => device.status === 'online').length)
const activeAlarmCount = computed(() => {
  const handledKeys = new Set(alarmDispositionRecords.value.map(record => record.alarmKey))
  const illegalCount = illegalParkingRecords.value.filter(record => record.status === 'warning' && !handledKeys.has(getAlarmKey(record, 'illegal_parking'))).length
  const anomalyCount = roadAnomalyRecords.value.filter(record => record.status === 'warning' && !handledKeys.has(getAlarmKey(record, 'road_anomaly'))).length
  return illegalCount + anomalyCount
})

const canOperate = computed(() => currentUser.value?.role === 'admin' || currentUser.value?.role === 'operator')
const canConfigure = computed(() => currentUser.value?.role === 'admin')

const latestEventTime = computed(() => {
  const event = eventRecords.value[0]
  if (!event?.timestamp) return '等待事件'
  const date = new Date(event.timestamp)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
})

const connectionQuality = computed(() => {
  if (connectionStatus.value === '已连接') return { text: '稳定', className: 'quality-good' }
  if (connectionStatus.value === '演示模式') return { text: '演示', className: 'quality-demo' }
  if (connectionStatus.value === '连接中' || connectionStatus.value === '重连中') return { text: '波动', className: 'quality-warn' }
  return { text: '中断', className: 'quality-bad' }
})

const formattedCurrentTime = computed(() => {
  return currentTime.value.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
})

const streamStatusText = computed(() => {
  if (systemStatus.value.stream_status === 'streaming') return '拉流中'
  if (systemStatus.value.stream_status === 'disconnected') return '已断开'
  if (connectionStatus.value === '演示模式') return '演示流'
  return connectionStatus.value
})

const currentDetectionCount = computed(() => {
  if (activeScene.value === 'vehicle_detection') return vehicleDetectionRecords.value.length
  if (activeScene.value === 'plate_recognition') return plateRecords.value.length
  if (activeScene.value === 'illegal_parking') return illegalParkingRecords.value.length
  if (activeScene.value === 'road_anomaly') return roadAnomalyRecords.value.length
  return trafficDensityData.value.reduce((sum, item) => sum + (item.vehicle_count || 0), 0)
})

const addEventRecord = (event) => {
  const normalized = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    timestamp: event.timestamp || new Date().toISOString(),
    status: event.status || 'normal',
    ...event
  }
  eventRecords.value.unshift(normalized)
  if (eventRecords.value.length > 200) {
    eventRecords.value = eventRecords.value.slice(0, 200)
  }
}

const getAlarmKey = (alarm, eventType = alarm?.event_type) => {
  if (eventType === 'illegal_parking') {
    return `${eventType}-${alarm?.timestamp || ''}-${alarm?.data?.track_id || alarm?.track_id || ''}`
  }
  if (eventType === 'road_anomaly') {
    return `${eventType}-${alarm?.timestamp || ''}-${alarm?.data?.anomaly_type || ''}-${alarm?.data?.affected_lane || ''}`
  }
  return `${eventType || 'alarm'}-${alarm?.timestamp || ''}-${JSON.stringify(alarm?.bbox || [])}`
}

const loadSavedUser = () => {
  try {
    const saved = window.localStorage.getItem('its_current_user')
    currentUser.value = saved ? JSON.parse(saved) : null
  } catch {
    currentUser.value = null
  }
}

const handleLogin = (user) => {
  currentUser.value = user
  window.localStorage.setItem('its_current_user', JSON.stringify(user))
  showLoginDialog.value = false
  addEventRecord({
    event_type: 'user_login',
    timestamp: new Date().toISOString(),
    device_id: 'frontend_console',
    status: 'normal',
    summary: `${user.username} 以${roleTextMap[user.role] || user.role}身份登录`,
    data: user
  })
}

const handleLogout = () => {
  const user = currentUser.value
  currentUser.value = null
  window.localStorage.removeItem('its_current_user')
  addEventRecord({
    event_type: 'user_logout',
    timestamp: new Date().toISOString(),
    device_id: 'frontend_console',
    status: 'normal',
    summary: `${user?.username || '用户'} 已退出`,
    data: { username: user?.username }
  })
}

const applyAlarmStatus = (payload) => {
  const alarmKey = getAlarmKey(payload.alarm, payload.eventType)
  const patchRecord = (record) => getAlarmKey(record, payload.eventType) === alarmKey
    ? { ...record, status: payload.action, handled_by: currentUser.value?.username || '未登录用户', handled_at: new Date().toISOString(), note: payload.note }
    : record

  if (payload.eventType === 'illegal_parking') {
    illegalParkingRecords.value = illegalParkingRecords.value.map(patchRecord)
  } else if (payload.eventType === 'road_anomaly') {
    roadAnomalyRecords.value = roadAnomalyRecords.value.map(patchRecord)
  }

  const disposition = {
    id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    alarmKey,
    eventType: payload.eventType,
    action: payload.action,
    operator: currentUser.value?.username || '未登录用户',
    role: currentUser.value?.role || 'guest',
    handledAt: new Date().toISOString(),
    note: payload.note || '已处理',
    alarm: payload.alarm
  }
  alarmDispositionRecords.value.unshift(disposition)
  if (alarmDispositionRecords.value.length > 50) {
    alarmDispositionRecords.value = alarmDispositionRecords.value.slice(0, 50)
  }

  addEventRecord({
    event_type: 'alarm_disposition',
    timestamp: disposition.handledAt,
    device_id: 'frontend_console',
    status: payload.action,
    summary: `${disposition.operator} 处理 ${payload.eventType}`,
    data: disposition
  })
}

const updateLatency = (timestamp) => {
  const eventTime = timestamp ? new Date(timestamp).getTime() : Date.now()
  latestLatency.value = Number.isNaN(eventTime)
    ? Math.round(60 + Math.random() * 80)
    : Math.max(0, Math.min(999, Date.now() - eventTime))
}

const handleSceneChange = (scene) => {
  activeScene.value = scene
  handleSendCommand({
    command: 'switch_scene',
    scene_id: scene
  })
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
      label: `${record.data?.vehicle_type || record.data?.plate_number || 'vehicle'} ${Math.round((record.data?.confidence || 0.86) * 100)}%`,
      color: index === 0 ? '#ef4444' : '#f59e0b'
    }))
}

const buildOverlayBoxes = (overlay) => {
  const data = overlay.data || {}
  const normalize = (items, color, fallbackLabel) => {
    return (Array.isArray(items) ? items : [])
      .filter(item => Array.isArray(item.bbox) && item.bbox.length === 4)
      .map(item => ({
        x1: item.bbox[0],
        y1: item.bbox[1],
        x2: item.bbox[2],
        y2: item.bbox[3],
        label: item.label || fallbackLabel,
        color
      }))
  }

  return [
    ...normalize(data.vehicles, '#38bdf8', 'vehicle'),
    ...normalize(data.plates, '#22c55e', 'plate'),
    ...normalize(data.illegal_parking, '#ef4444', 'illegal'),
    ...normalize(data.road_anomalies, '#a855f7', 'anomaly')
  ]
}

const handleVideoOverlay = (data) => {
  if (!videoPlayerRef.value) return
  const sourceSize = data.stream_size?.width && data.stream_size?.height
    ? { width: data.stream_size.width, height: data.stream_size.height }
    : null
  videoPlayerRef.value.drawBoxes(buildOverlayBoxes(data), sourceSize)
}

const handleVehicleDetection = (data) => {
  vehicleDetectionRecords.value.unshift(data)
  if (vehicleDetectionRecords.value.length > 20) {
    vehicleDetectionRecords.value = vehicleDetectionRecords.value.slice(0, 20)
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
  if (!canOperate.value) {
    showLoginDialog.value = true
    return
  }
  websocketManager.send(command)
  addEventRecord({
    event_type: 'client_command',
    command: command.command || 'command',
    data: command,
    device_id: 'frontend_console',
    status: 'normal'
  })
}

const routeEvent = (data) => {
  updateLatency(data.timestamp)
  addEventRecord(data)

  if (data.event_type === 'video_overlay') {
    handleVideoOverlay(data)
  } else if (data.event_type === 'vehicle_detection') {
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
}

onMounted(() => {
  if (isPublisherMode) return
  loadSavedUser()
  if (!currentUser.value) {
    showLoginDialog.value = true
  }

  clockTimer = setInterval(() => {
    currentTime.value = new Date()
  }, 1000)

  websocketManager.onMessage((data) => {
    console.log('WebSocket 消息:', data)
    routeEvent(data)
  })

  websocketManager.onStatusChange((status, count) => {
    connectionStatus.value = statusMap[status] || status
    reconnectCount.value = count

    if (status === 'disconnected' && count >= 10) {
      showError.value = true
      errorMessage.value = 'WebSocket 连接失败，已达到最大重试次数'
    } else if (status === 'connected' || status === 'simulating') {
      showError.value = false
    }
  })

  websocketManager.connect(CLOUD_SERVER_URL)
})

onUnmounted(() => {
  if (clockTimer) {
    clearInterval(clockTimer)
  }
  if (!isPublisherMode) {
    websocketManager.disconnect()
  }
})
</script>

<template>
  <CameraPublisher v-if="isPublisherMode" :whip-src="liveWhipSrc" />

  <div v-else class="app-container">
    <header class="header">
      <div class="header-content">
        <div class="brand">
          <div class="brand-mark">ITS</div>
          <div>
            <h1>智慧交通视觉感知系统</h1>
            <p>Cloud Edge Vision Command Center</p>
          </div>
        </div>
        <div class="header-right">
          <div class="time-block">
            <span>系统时间</span>
            <strong>{{ formattedCurrentTime }}</strong>
          </div>
          <div class="status-container">
            <span class="status-label">连接状态</span>
            <ElTag :type="statusTypeMap[connectionStatus]" size="large">
              {{ connectionStatus }}
              <span v-if="connectionStatus === '重连中'" class="reconnect-count">
                ({{ reconnectCount }}/{{ websocketManager.maxReconnectAttempts }})
              </span>
            </ElTag>
          </div>
          <UserSessionPanel
            v-model:visible="showLoginDialog"
            :user="currentUser"
            @login="handleLogin"
            @logout="handleLogout"
          />
          <ConfigPanel v-if="canConfigure" @send-command="handleSendCommand" />
          <ElTag v-else type="info" size="large">只读模式</ElTag>
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
      <ElAlert
        v-if="!currentUser"
        title="请先登录"
        description="未登录时可以查看大屏，但不能执行场景切换、配置变更和告警处置。"
        type="warning"
        show-icon
        :closable="false"
      />

      <section class="scene-tabs-panel">
        <ElTabs v-model="activeScene" class="scene-tabs" @tab-change="handleSceneChange">
          <ElTabPane v-for="scene in sceneTabs" :key="scene.value" :label="scene.label" :name="scene.value" />
        </ElTabs>
        <div class="scene-meta">
          <span>当前模型：{{ activeSceneMeta.model }}</span>
          <span>检测结果：{{ currentDetectionCount }}</span>
          <span>模式：{{ websocketManager.isSimulating() ? '演示数据' : '真实接入' }}</span>
        </div>
      </section>

      <section class="overview-strip" aria-label="系统运行总览">
        <div class="overview-card">
          <span>在线设备</span>
          <strong>{{ onlineDeviceCount }}/{{ deviceList.length }}</strong>
          <em>边端采集节点</em>
        </div>
        <div class="overview-card">
          <span>当前告警</span>
          <strong :class="{ danger: activeAlarmCount > 0 }">{{ activeAlarmCount }}</strong>
          <em>违停 / 道路异常</em>
        </div>
        <div class="overview-card">
          <span>传输延迟</span>
          <strong>{{ latestLatency }}ms</strong>
          <em>{{ connectionQuality.text }}</em>
        </div>
        <div class="overview-card">
          <span>事件总量</span>
          <strong>{{ eventRecords.length }}</strong>
          <em>最新 {{ latestEventTime }}</em>
        </div>
        <div class="overview-card">
          <span>通行识别</span>
          <strong>{{ dashboardStats.plateCount }}</strong>
          <em>车牌比对结果</em>
        </div>
        <div class="overview-card">
          <span>拥堵指数</span>
          <strong>{{ dashboardStats.congestionIndex }}</strong>
          <em>0-100 综合评分</em>
        </div>
        <div class="overview-card">
          <span>处置记录</span>
          <strong>{{ alarmDispositionRecords.length }}</strong>
          <em>{{ currentUser ? roleTextMap[currentUser.role] : '未登录' }}</em>
        </div>
      </section>

      <section class="command-grid">
        <aside class="left-rail">
          <CloudEdgeStatus
            :connection-status="connectionStatus"
            :reconnect-count="reconnectCount"
            :devices="deviceList"
            :system-data="systemStatus"
            :server-url="CLOUD_SERVER_URL"
            :stream-url="liveWebrtcSrc || liveVideoSrc"
            :active-scene-label="activeSceneMeta.label"
            :simulation-mode="websocketManager.isSimulating()"
          />
          <DemoChecklist
            :connection-status="connectionStatus"
            :stream-status="streamStatusText"
            :devices="deviceList"
            :user="currentUser"
            :server-url="CLOUD_SERVER_URL"
            :stream-url="liveWebrtcSrc || liveVideoSrc"
            :event-count="eventRecords.length"
            :alarm-count="activeAlarmCount"
          />
          <SystemMonitor
            :system-data="systemStatus"
            :connection-status="connectionStatus"
            :active-devices="onlineDeviceCount"
            :active-streams="systemStatus.active_streams || (streamStatusText === '拉流中' ? 1 : 0)"
            :event-count="eventRecords.length"
            :alarm-count="activeAlarmCount"
          />
          <DeviceManager :devices="deviceList" @add-device="handleDeviceAdd" />
        </aside>

        <section class="center-stage">
          <div class="video-section">
            <div class="panel-title">
              <div>
                <h2>实时视频分析</h2>
                <p>检测框、告警区域、识别结果与事件流同步展示</p>
              </div>
              <div class="video-title-actions">
                <span :class="['quality-dot', connectionQuality.className]"></span>
                <ElTag type="success">{{ streamStatusText }}</ElTag>
              </div>
            </div>
            <VideoPlayer
              ref="videoPlayerRef"
              :video-src="liveVideoSrc"
              :webrtc-src="liveWebrtcSrc"
              :analysis-mode="activeSceneMeta.label"
              :model-name="activeSceneMeta.model"
              :detection-count="currentDetectionCount"
              :latency="latestLatency"
              :stream-status="streamStatusText"
            />
          </div>

          <TrafficHeatmap v-if="activeScene === 'traffic_density'" :data="trafficDensityData" />
          <VehicleDetectionPanel v-else-if="activeScene === 'vehicle_detection'" :records="vehicleDetectionRecords" />
          <PlateResult
            v-else-if="activeScene === 'plate_recognition'"
            :latest-result="latestPlateResult"
            :records="plateRecords"
          />
          <IllegalParkingAlarm
            v-else-if="activeScene === 'illegal_parking'"
            :records="illegalParkingRecords"
            :can-dispose="canOperate"
            @dispose-alarm="applyAlarmStatus"
          />
          <RoadAnomalyAlarm
            v-else-if="activeScene === 'road_anomaly'"
            :records="roadAnomalyRecords"
            :can-dispose="canOperate"
            @dispose-alarm="applyAlarmStatus"
          />
        </section>

        <aside class="right-rail">
          <EventStream :events="eventRecords" />
          <PlateResult :latest-result="latestPlateResult" :records="plateRecords" />
          <IllegalParkingAlarm
            :records="illegalParkingRecords"
            :can-dispose="canOperate"
            @dispose-alarm="applyAlarmStatus"
          />
          <RoadAnomalyAlarm
            :records="roadAnomalyRecords"
            :can-dispose="canOperate"
            @dispose-alarm="applyAlarmStatus"
          />
        </aside>
      </section>

      <DashboardStats :stats-data="dashboardStats" />

      <section class="bottom-grid">
        <HistoryQuery :events="eventRecords" />
        <div class="bottom-stack">
          <AlarmWorkbench :records="alarmDispositionRecords" />
          <WhitelistManager v-if="canConfigure" @send-command="handleSendCommand" />
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background:
    radial-gradient(circle at 16% 12%, rgba(14, 165, 233, 0.2), transparent 28%),
    radial-gradient(circle at 82% 8%, rgba(20, 184, 166, 0.16), transparent 26%),
    linear-gradient(180deg, #07111f 0%, #0b1728 48%, #08111f 100%);
  color: #dbeafe;
  position: relative;
}

.app-container::before {
  content: '';
  inset: 0;
  pointer-events: none;
  position: fixed;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.06) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.9), transparent 78%);
  z-index: 0;
}

.header {
  background: rgba(7, 17, 31, 0.86);
  border-bottom: 1px solid rgba(34, 211, 238, 0.22);
  color: #ffffff;
  padding: 14px 24px;
  box-shadow: 0 12px 34px rgba(2, 8, 23, 0.42);
  position: sticky;
  top: 0;
  z-index: 5;
  backdrop-filter: blur(18px);
}

.header-content {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin: 0 auto;
  max-width: 1680px;
}

.brand {
  align-items: center;
  display: flex;
  gap: 12px;
}

.brand-mark {
  align-items: center;
  background: linear-gradient(135deg, #06b6d4, #2563eb);
  border-radius: 8px;
  box-shadow: 0 0 22px rgba(34, 211, 238, 0.45);
  display: flex;
  font-size: 15px;
  font-weight: 800;
  height: 44px;
  justify-content: center;
  letter-spacing: 0;
  width: 44px;
}

.brand h1 {
  color: #f8fafc;
  font-size: 22px;
  font-weight: 700;
  text-shadow: 0 0 18px rgba(125, 211, 252, 0.22);
}

.brand p {
  color: #93c5fd;
  font-size: 12px;
  margin-top: 2px;
}

.header-right {
  align-items: center;
  display: flex;
  gap: 16px;
}

.time-block {
  border-right: 1px solid rgba(125, 211, 252, 0.18);
  display: grid;
  gap: 3px;
  padding-right: 16px;
  text-align: right;
}

.time-block span {
  color: #7dd3fc;
  font-size: 11px;
}

.time-block strong {
  color: #e0f2fe;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
}

.status-container {
  align-items: center;
  display: flex;
  gap: 8px;
}

.status-label {
  color: #93c5fd;
  font-size: 13px;
}

.reconnect-count {
  font-size: 12px;
  margin-left: 4px;
}

.main-content {
  margin: 18px auto;
  max-width: 1680px;
  padding: 0 20px 24px;
  position: relative;
  z-index: 1;
}

.scene-tabs-panel {
  align-items: center;
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(15, 36, 62, 0.82));
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 0 16px;
  box-shadow: 0 18px 40px rgba(2, 8, 23, 0.32), inset 0 1px 0 rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(14px);
}

.scene-tabs {
  flex: 1;
  min-width: 0;
}

.scene-meta {
  align-items: center;
  color: #bae6fd;
  display: flex;
  flex-wrap: wrap;
  font-size: 13px;
  gap: 12px;
  justify-content: flex-end;
  padding-left: 16px;
}

.overview-strip {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(7, minmax(0, 1fr));
  margin-bottom: 16px;
}

.overview-card {
  background:
    linear-gradient(135deg, rgba(8, 145, 178, 0.16), rgba(15, 23, 42, 0.72)),
    rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 8px;
  min-width: 0;
  overflow: hidden;
  padding: 13px 14px;
  position: relative;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05), 0 12px 26px rgba(2, 8, 23, 0.22);
}

.overview-card::after {
  background: linear-gradient(180deg, rgba(34, 211, 238, 0.9), transparent);
  content: '';
  height: 44px;
  position: absolute;
  right: 0;
  top: 0;
  width: 2px;
}

.overview-card span {
  color: #93c5fd;
  display: block;
  font-size: 12px;
}

.overview-card strong {
  color: #e0f2fe;
  display: block;
  font-size: 25px;
  font-weight: 800;
  line-height: 1.1;
  margin-top: 6px;
}

.overview-card strong.danger {
  color: #fca5a5;
  text-shadow: 0 0 14px rgba(239, 68, 68, 0.42);
}

.overview-card em {
  color: #7dd3fc;
  display: block;
  font-size: 11px;
  font-style: normal;
  margin-top: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: 360px minmax(0, 1fr) 390px;
  align-items: start;
}

.left-rail,
.right-rail,
.center-stage {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.video-section {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(8, 18, 33, 0.94));
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 20px 48px rgba(2, 8, 23, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.panel-title {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 14px;
}

.video-title-actions {
  align-items: center;
  display: flex;
  gap: 10px;
}

.quality-dot {
  border-radius: 50%;
  height: 10px;
  width: 10px;
}

.quality-good {
  background: #22c55e;
  box-shadow: 0 0 14px rgba(34, 197, 94, 0.7);
}

.quality-demo {
  background: #38bdf8;
  box-shadow: 0 0 14px rgba(56, 189, 248, 0.7);
}

.quality-warn {
  background: #f59e0b;
  box-shadow: 0 0 14px rgba(245, 158, 11, 0.7);
}

.quality-bad {
  background: #ef4444;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.7);
}

.panel-title h2 {
  color: #e0f2fe;
  font-size: 18px;
}

.panel-title p {
  color: #7dd3fc;
  font-size: 12px;
  margin-top: 4px;
}

:deep(.el-tabs__item) {
  color: #93c5fd;
  font-weight: 600;
}

:deep(.el-tabs__item.is-active) {
  color: #67e8f9;
  text-shadow: 0 0 16px rgba(34, 211, 238, 0.52);
}

:deep(.el-tabs__active-bar) {
  background: linear-gradient(90deg, #22d3ee, #60a5fa);
  box-shadow: 0 0 16px rgba(34, 211, 238, 0.66);
}

:deep(.el-tabs__nav-wrap::after) {
  background-color: rgba(56, 189, 248, 0.18);
}

:deep(.el-tag) {
  border-radius: 6px;
}

:deep(.cloud-edge-status),
:deep(.system-monitor),
:deep(.device-manager),
:deep(.event-stream),
:deep(.plate-result-container .el-card),
:deep(.illegal-parking-alarm),
:deep(.road-anomaly-alarm),
:deep(.alarm-workbench),
:deep(.demo-checklist),
:deep(.vehicle-detection-panel),
:deep(.traffic-heatmap-container),
:deep(.dashboard-stats),
:deep(.history-query),
:deep(.whitelist-manager) {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: #dbeafe;
}

:deep(.system-monitor h3),
:deep(.device-manager h3),
:deep(.event-stream h2),
:deep(.traffic-heatmap-container h2),
:deep(.dashboard-stats h3),
:deep(.history-query h2),
:deep(.whitelist-manager h2),
:deep(.vehicle-detection-panel h3),
:deep(.illegal-parking-alarm h3),
:deep(.road-anomaly-alarm h3),
:deep(.alarm-workbench h2),
:deep(.demo-checklist h2),
:deep(.el-card__header) {
  color: #e0f2fe;
}

:deep(.el-card) {
  background: transparent;
  border-color: rgba(56, 189, 248, 0.2);
  color: #dbeafe;
}

:deep(.el-card__header) {
  border-bottom-color: rgba(56, 189, 248, 0.18);
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(14, 165, 233, 0.12);
  --el-table-row-hover-bg-color: rgba(14, 165, 233, 0.12);
  --el-table-border-color: rgba(56, 189, 248, 0.14);
  --el-table-text-color: #dbeafe;
  --el-table-header-text-color: #93c5fd;
  background: transparent;
  color: #dbeafe;
}

:deep(.el-table th.el-table__cell),
:deep(.el-table tr),
:deep(.el-table td.el-table__cell) {
  background: transparent;
}

:deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background: rgba(15, 23, 42, 0.38);
}

:deep(.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
}

:deep(.el-dialog__title),
:deep(.el-form-item__label) {
  color: #e0f2fe;
}

:deep(.el-input__wrapper),
:deep(.el-select__wrapper),
:deep(.el-input-number__wrapper) {
  background: rgba(15, 23, 42, 0.86);
  border: 1px solid rgba(56, 189, 248, 0.18);
  box-shadow: none;
}

:deep(.el-input__inner),
:deep(.el-select__placeholder) {
  color: #dbeafe;
}

.bottom-grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1.25fr) minmax(380px, 0.75fr);
  margin-top: 16px;
}

.bottom-stack {
  display: grid;
  gap: 16px;
}

@media (max-width: 1480px) {
  .overview-strip {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .command-grid {
    grid-template-columns: 330px minmax(0, 1fr);
  }

  .right-rail {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .header-content,
  .scene-tabs-panel {
    align-items: flex-start;
    flex-direction: column;
    gap: 12px;
  }

  .command-grid,
  .overview-strip,
  .bottom-grid,
  .right-rail {
    grid-template-columns: 1fr;
  }

  .scene-meta {
    justify-content: flex-start;
    padding: 0 0 12px;
  }
}

@media (max-width: 720px) {
  .header,
  .main-content {
    padding-left: 12px;
    padding-right: 12px;
  }

  .header-right {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
