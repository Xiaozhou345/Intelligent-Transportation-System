<script setup>
import { computed, defineAsyncComponent, ref, reactive, onMounted, onUnmounted, nextTick } from 'vue'
import { ElAlert, ElTabPane, ElTabs, ElTag } from 'element-plus'
import websocketManager from './utils/websocketManager'
import VideoPlayer from './components/VideoPlayer.vue'

// 非首屏面板按需加载，避免 ECharts/管理组件全部挤进首个 JS 包。
const CameraPublisher = defineAsyncComponent(() => import('./components/CameraPublisher.vue'))
const PlateResult = defineAsyncComponent(() => import('./components/PlateResult.vue'))
const TrafficHeatmap = defineAsyncComponent(() => import('./components/TrafficHeatmap.vue'))
const IllegalParkingAlarm = defineAsyncComponent(() => import('./components/IllegalParkingAlarm.vue'))
const RoadAnomalyAlarm = defineAsyncComponent(() => import('./components/RoadAnomalyAlarm.vue'))
const VehicleDetectionPanel = defineAsyncComponent(() => import('./components/VehicleDetectionPanel.vue'))
const SystemMonitor = defineAsyncComponent(() => import('./components/SystemMonitor.vue'))
const DeviceManager = defineAsyncComponent(() => import('./components/DeviceManager.vue'))
const ConfigPanel = defineAsyncComponent(() => import('./components/ConfigPanel.vue'))
const DashboardStats = defineAsyncComponent(() => import('./components/DashboardStats.vue'))
const CloudEdgeStatus = defineAsyncComponent(() => import('./components/CloudEdgeStatus.vue'))
const EventStream = defineAsyncComponent(() => import('./components/EventStream.vue'))
const HistoryQuery = defineAsyncComponent(() => import('./components/HistoryQuery.vue'))
const WhitelistManager = defineAsyncComponent(() => import('./components/WhitelistManager.vue'))
const UserSessionPanel = defineAsyncComponent(() => import('./components/UserSessionPanel.vue'))
const AlarmWorkbench = defineAsyncComponent(() => import('./components/AlarmWorkbench.vue'))
const DemoChecklist = defineAsyncComponent(() => import('./components/DemoChecklist.vue'))

const connectionStatus = ref('未连接')
const reconnectCount = ref(0)
const showError = ref(false)
const errorMessage = ref('')
const activeScene = ref('vehicle_detection')
const eventRecords = ref([])
const latestLatency = ref(0)
const currentTime = ref(new Date())
let clockTimer = null
let systemStatusTimer = null

const videoPlayerRef = ref(null)
const latestVideoOverlay = ref(null)

const PUBLIC_CLOUD_SERVER_URL = import.meta.env.VITE_CLOUD_SERVER_URL || 'http://106.54.10.11:15000'
const LOCAL_API_PORT = import.meta.env.VITE_LOCAL_API_PORT || '5001'
const CLOUD_SERVER_URL = window.location.port === '5173'
  ? `${window.location.protocol}//${window.location.hostname}:${LOCAL_API_PORT}`
  : PUBLIC_CLOUD_SERVER_URL
const liveVideoSrc = import.meta.env.VITE_LIVE_VIDEO_URL || 'http://106.54.10.11:8888/live/mobile_001/index.m3u8'
const liveWebrtcSrc = import.meta.env.VITE_LIVE_WEBRTC_URL ?? 'http://106.54.10.11:8889/live/mobile_001/whep'
const liveWhipSrc = import.meta.env.VITE_LIVE_WHIP_URL || 'http://106.54.10.11:8889/live/mobile_001/whip'
const isPublisherMode = window.location.pathname === '/publish' || new URLSearchParams(window.location.search).get('mode') === 'publisher'

const latestPlateResult = ref(null)
const plateRecords = ref([])
const vehicleDetectionRecords = ref([])
const latestTrafficDensityAt = ref('')

const trafficDensityData = ref([])

const illegalParkingRecords = ref([])
const roadAnomalyRecords = ref([])
const systemStatus = ref({})
const anomalyModeStatus = ref({ mode: 'detecting', background_frames: 0, enabled: false })
const currentUser = ref(null)
const showLoginDialog = ref(false)
const alarmDispositionRecords = ref([])

const dashboardStats = reactive({
  plateCount: 0,
  congestionIndex: 0,
  illegalParkingCount: 0,
  roadAnomalyCount: 0
})

const deviceList = ref([])

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
  return trafficDensityData.value.reduce((sum, item) => sum + (Number(item.vehicle_count) || 0), 0)
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
  if (!timestamp) {
    latestLatency.value = 0
    return
  }
  const eventTime = timestamp ? new Date(timestamp).getTime() : Date.now()
  latestLatency.value = Number.isNaN(eventTime)
    ? 0
    : Math.max(0, Math.min(999, Date.now() - eventTime))
}

const handleSceneChange = (scene) => {
  activeScene.value = scene
  nextTick(() => {
    redrawCurrentOverlay()
  })
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
      label: record.data?.confidence === undefined
        ? (record.data?.vehicle_type || record.data?.plate_number || 'vehicle')
        : `${record.data?.vehicle_type || record.data?.plate_number || 'vehicle'} ${Math.round(record.data.confidence * 100)}%`,
      color: index === 0 ? '#ef4444' : '#ef4444'
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
  const normalizePolygons = (items, color, fillColor, fallbackLabel) => {
    return (Array.isArray(items) ? items : [])
      .filter(item => Array.isArray(item.polygon) && item.polygon.length >= 3)
      .map(item => ({
        polygon: item.polygon,
        label: item.label || item.name || fallbackLabel,
        color,
        fillColor
      }))
  }
  const parkingStatuses = (Array.isArray(data.parking_statuses) ? data.parking_statuses : [])
    .filter(item => Array.isArray(item.bbox) && item.bbox.length === 4)
    .map(item => ({
      x1: item.bbox[0],
      y1: item.bbox[1],
      x2: item.bbox[2],
      y2: item.bbox[3],
      label: item.label || (item.has_warned ? '已违停' : '违停计时中'),
      color: item.has_warned ? '#b91c1c' : (item.is_stationary ? '#f97316' : '#2563eb'),
      trackId: item.track_id
    }))
  const activeParkingTrackIds = new Set(parkingStatuses.map(item => item.trackId))
  const parkingAlerts = (Array.isArray(data.illegal_parking) ? data.illegal_parking : [])
    .filter(item => !activeParkingTrackIds.has(item.track_id))

  return [
    ...normalizePolygons(data.no_parking_zones, '#f97316', 'rgba(249, 115, 22, 0.16)', 'no parking'),
    ...normalizePolygons(data.anomaly_road_roi, '#16a34a', 'rgba(22, 163, 74, 0.10)', '异物检测区'),
    ...normalize(data.vehicles, '#ef4444', 'vehicle'),
    ...normalize(data.plates, '#f59e0b', 'plate'),
    ...parkingStatuses,
    ...normalize(parkingAlerts, '#b91c1c', 'illegal'),
    ...normalize(data.road_anomalies, '#a855f7', 'anomaly')
  ]
}

const handleVideoOverlay = (data, skipDraw = false) => {
  latestVideoOverlay.value = data
  const analysisLatency = Number(data.analysis_latency_ms)
  if (Number.isFinite(analysisLatency)) {
    latestLatency.value = Math.max(0, Math.round(analysisLatency))
  }

  // 🔥 关键修复：如果 skipDraw=true，只更新数据，不绘制
  // 因为 video_frame 已经包含了完整画面
  if (skipDraw || !videoPlayerRef.value) return

  const sourceSize = data.stream_size?.width && data.stream_size?.height
    ? { width: data.stream_size.width, height: data.stream_size.height }
    : null
  videoPlayerRef.value.drawBoxes(buildOverlayBoxes(data), sourceSize)
}

// 新增：处理后端绘制好的视频帧
let lastFrameSequence = 0
const handleVideoFrame = (data) => {
  const analysisLatency = Number(data.analysis_latency_ms)
  if (Number.isFinite(analysisLatency)) {
    latestLatency.value = Math.max(0, Math.round(analysisLatency))
  }
  if (!videoPlayerRef.value) return

  // 帧丢弃：如果前端渲染慢于后端推送，丢弃旧帧
  const sequence = data.sequence || 0
  if (sequence <= lastFrameSequence) {
    return  // 旧帧，直接丢弃
  }
  lastFrameSequence = sequence

  // 解码图像数据
  const imageData = data.data?.image
  if (!imageData || typeof imageData !== 'string') {
    console.warn('无效的图像数据', imageData)
    return
  }

  // 高性能 base64 解码：使用 Blob 构造函数直接处理
  try {
    // 方法1：使用 fetch data URI (Chrome 优化，最快)
    fetch(`data:image/jpeg;base64,${imageData}`)
      .then(res => res.blob())
      .then(blob => {
        const url = URL.createObjectURL(blob)
        videoPlayerRef.value.showAnnotatedFrame(url, sequence)
      })
      .catch(error => {
        console.error('解码图像失败:', error)
      })
  } catch (error) {
    console.error('解码图像失败:', error)
  }
}

const redrawCurrentOverlay = () => {
  if (!videoPlayerRef.value || !latestVideoOverlay.value) return
  const overlay = latestVideoOverlay.value
  const sourceSize = overlay.stream_size?.width && overlay.stream_size?.height
    ? { width: overlay.stream_size.width, height: overlay.stream_size.height }
    : null
  videoPlayerRef.value.drawBoxes(buildOverlayBoxes(overlay), sourceSize)
}

const handleVehicleDetection = (data) => {
  vehicleDetectionRecords.value.unshift(data)
  if (vehicleDetectionRecords.value.length > 20) {
    vehicleDetectionRecords.value = vehicleDetectionRecords.value.slice(0, 20)
  }
}

const handleTrafficDensity = (data) => {
  const regions = data.data?.regions || data.regions
  if (Array.isArray(regions)) {
    trafficDensityData.value = regions
    latestTrafficDensityAt.value = data.timestamp || new Date().toISOString()
    const totalVehicles = regions.reduce((sum, r) => sum + (Number(r.vehicle_count) || 0), 0)
    const avgVehicles = regions.length ? totalVehicles / regions.length : 0
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

const normalizeDevice = (device) => {
  const streamProcessing = Boolean(device.stream_processing)
  const rawStatus = device.status || 'offline'
  return {
    ...device,
    status: rawStatus === 'online' || streamProcessing ? 'online' : 'offline',
    stream_processing: streamProcessing,
    last_heartbeat: device.last_heartbeat || device.register_time || '',
    device_type: device.device_type || 'unknown',
    scene_id: device.scene_id || '-'
  }
}

const updateDeviceList = (devices = []) => {
  deviceList.value = (Array.isArray(devices) ? devices : []).map(normalizeDevice)
}

const handleAnomalyModeUpdated = (data) => {
  const payload = data.data || data
  if (payload.active_scene && sceneTabs.some(scene => scene.value === payload.active_scene)) {
    activeScene.value = payload.active_scene
  }
  anomalyModeStatus.value = {
    ...anomalyModeStatus.value,
    ...payload
  }
}

const handleAnomalyCalibration = (data) => {
  const payload = data.data || {}
  anomalyModeStatus.value = {
    ...anomalyModeStatus.value,
    status: data.status === 'skipped' ? 'warning' : 'success',
    message: '',
    mode: payload.mode || 'background_learning',
    background_frames: payload.background_frames ?? anomalyModeStatus.value.background_frames,
    skipped_frames: payload.skipped_frames ?? anomalyModeStatus.value.skipped_frames,
    last_calibration_status: data.status,
    last_calibration_reason: payload.reason
  }
}

const fetchSystemStatus = async () => {
  if (websocketManager.isSimulating()) return
  try {
    const response = await fetch(`${CLOUD_SERVER_URL}/api/system/status`, { cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    if (payload?.data) {
      handleSystemStatus({ data: payload.data })
    }
  } catch (error) {
    console.warn('系统状态拉取失败:', error)
  }
}

const fetchAnomalyStatus = async () => {
  if (websocketManager.isSimulating()) return
  try {
    const response = await fetch(`${CLOUD_SERVER_URL}/api/anomaly/status`, { cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    handleAnomalyModeUpdated({ data: payload })
  } catch (error) {
    console.warn('异常检测状态拉取失败:', error)
  }
}

const fetchDevices = async () => {
  if (websocketManager.isSimulating()) return
  try {
    const response = await fetch(`${CLOUD_SERVER_URL}/api/devices`, { cache: 'no-store' })
    if (!response.ok) return
    const payload = await response.json()
    updateDeviceList(payload.devices)
  } catch (error) {
    console.warn('设备列表拉取失败:', error)
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

  if (data.event_type === 'video_frame') {
    handleVideoFrame(data)
    // 🔥 关键修复：收到 video_frame 时，标记为"后端渲染模式"
    // video_frame 已经包含了完整画面（视频+检测框），不需要再处理 video_overlay
  } else if (data.event_type === 'video_overlay') {
    // 🔥 关键修复：如果正在使用后端渲染模式，跳过 overlay 绘制
    // 只保存数据用于统计面板，不在 canvas 上绘制
    handleVideoOverlay(data, true)  // 传入 skipDraw=true
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
  } else if (data.event_type === 'anomaly_mode_updated') {
    handleAnomalyModeUpdated(data)
  } else if (data.event_type === 'anomaly_calibration') {
    handleAnomalyCalibration(data)
  } else if (data.event_type === 'scene_switched') {
    const sceneId = data.data?.scene_id
    if (sceneTabs.some(scene => scene.value === sceneId)) {
      activeScene.value = sceneId
    }
  } else if (data.event_type === 'devices_list') {
    updateDeviceList(data.data?.devices)
  }
}

// 加载历史数据和白名单
const loadHistoryData = async () => {
  try {
    console.log('🔄 开始加载历史数据...')

    // 1. 加载历史识别事件（最近50条）
    const eventsRes = await fetch(`${CLOUD_SERVER_URL}/api/history/events?limit=50`)
    if (eventsRes.ok) {
      const eventsData = await eventsRes.json()
      if (eventsData.status === 'success' && eventsData.data.length > 0) {
        // 转换数据格式以匹配前端
        const historyEvents = eventsData.data.map(event => {
          // 解析 result_json 字符串为对象
          let parsedData = {}
          if (typeof event.result_json === 'string') {
            try {
              parsedData = JSON.parse(event.result_json)
            } catch (e) {
              console.warn('解析 result_json 失败:', e)
            }
          } else if (event.result_json) {
            parsedData = event.result_json
          }

          return {
            event_type: event.event_type,
            device_id: event.device_id,
            timestamp: event.created_at,
            status: 'normal',
            data: parsedData,
            plate_number: event.plate_number
          }
        })

        // 将历史数据添加到事件记录
        eventRecords.value = [...historyEvents, ...eventRecords.value]

        // 提取车牌识别记录到 plateRecords
        const plateHistory = historyEvents.filter(e => e.event_type === 'plate_recognition')
        if (plateHistory.length > 0) {
          plateRecords.value = [...plateHistory.slice(0, 10), ...plateRecords.value]
          console.log(`✅ 加载了 ${plateHistory.length} 条车牌识别历史`)
        }

        console.log(`✅ 加载了 ${historyEvents.length} 条历史事件`)
      }
    }

    // 2. 加载白名单
    const whitelistRes = await fetch(`${CLOUD_SERVER_URL}/api/whitelist`)
    if (whitelistRes.ok) {
      const whitelistData = await whitelistRes.json()
      if (whitelistData.status === 'success') {
        console.log(`✅ 加载了 ${whitelistData.data.length} 条白名单`)
        // 将白名单数据存储到全局状态（供 WhitelistManager 使用）
        window.initialWhitelist = whitelistData.data
        // 触发自定义事件通知白名单已加载
        window.dispatchEvent(new CustomEvent('whitelist-loaded', { detail: whitelistData.data }))
      }
    }

    // 3. 加载系统配置
    const configRes = await fetch(`${CLOUD_SERVER_URL}/api/config`)
    if (configRes.ok) {
      const configData = await configRes.json()
      if (configData.status === 'success') {
        console.log(`✅ 加载了系统配置:`, Object.keys(configData.data))
        window.systemConfig = configData.data
      }
    }

    console.log('✅ 历史数据加载完成')
  } catch (error) {
    console.warn('⚠️  加载历史数据失败:', error.message)
  }
}

onMounted(async () => {
  if (isPublisherMode) return
  loadSavedUser()

  // 先加载历史数据（使用 await 确保完成）
  await loadHistoryData()

  clockTimer = setInterval(() => {
    currentTime.value = new Date()
  }, 1000)

  fetchSystemStatus()
  fetchAnomalyStatus()
  fetchDevices()
  systemStatusTimer = setInterval(() => {
    fetchSystemStatus()
    fetchAnomalyStatus()
    fetchDevices()
  }, 3000)

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
      if (status === 'connected') {
        websocketManager.sendEvent('request_devices')
        fetchDevices()
      }
    }
  })

  websocketManager.connect(CLOUD_SERVER_URL)
})

onUnmounted(() => {
  if (clockTimer) {
    clearInterval(clockTimer)
  }
  if (systemStatusTimer) {
    clearInterval(systemStatusTimer)
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
            v-if="currentUser"
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

    <main v-if="!currentUser" class="login-shell">
      <section class="login-hero">
        <div class="login-copy">
          <span class="login-eyebrow">访问控制</span>
          <h2>登录后进入视频监控台</h2>
          <p>未登录状态不再直接展示实时视频画面。请选择身份进入系统，访客只能查看数据，值班员可处置告警，管理员可修改配置。</p>
        </div>
        <div class="login-card">
          <h3>用户登录</h3>
          <UserSessionPanel embedded @login="handleLogin" />
        </div>
      </section>
    </main>

    <main v-else class="main-content">
      <ElAlert
        v-if="showError"
        title="连接错误"
        :description="errorMessage"
        type="error"
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

          <TrafficHeatmap
            v-if="activeScene === 'traffic_density'"
            :data="trafficDensityData"
            :updated-at="latestTrafficDensityAt"
          />
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
            :can-operate="canOperate"
            :mode-status="anomalyModeStatus"
            @dispose-alarm="applyAlarmStatus"
            @send-command="handleSendCommand"
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
            :can-operate="canOperate"
            :mode-status="anomalyModeStatus"
            @dispose-alarm="applyAlarmStatus"
            @send-command="handleSendCommand"
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
  color: #7dd3fc;
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

.login-shell {
  align-items: center;
  display: flex;
  min-height: calc(100vh - 88px);
  padding: 32px 20px;
  position: relative;
  z-index: 1;
}

.login-hero {
  align-items: stretch;
  display: grid;
  gap: 24px;
  grid-template-columns: minmax(0, 1fr) 420px;
  margin: 0 auto;
  max-width: 1120px;
  width: 100%;
}

.login-copy {
  background: linear-gradient(135deg, rgba(15, 23, 42, 0.82), rgba(8, 47, 73, 0.72));
  border: 1px solid rgba(56, 189, 248, 0.24);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 300px;
  padding: 34px;
  box-shadow: 0 20px 48px rgba(2, 8, 23, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.login-eyebrow {
  color: #67e8f9;
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 12px;
}

.login-copy h2 {
  color: #f8fafc;
  font-size: 30px;
  line-height: 1.2;
  margin: 0;
}

.login-copy p {
  color: #bae6fd;
  font-size: 15px;
  line-height: 1.8;
  margin: 16px 0 0;
  max-width: 620px;
}

.login-card {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.94), rgba(8, 18, 33, 0.94));
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  overflow: visible;
  padding: 28px;
  box-shadow: 0 20px 48px rgba(2, 8, 23, 0.45), inset 0 1px 0 rgba(255, 255, 255, 0.06);
}

.login-card h3 {
  color: #e0f2fe;
  font-size: 20px;
  margin: 0 0 20px;
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
  color: #0284c7;
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
  .right-rail,
  .login-hero {
    grid-template-columns: 1fr;
  }

  .scene-meta {
    justify-content: flex-start;
    padding: 0 0 12px;
  }
}

@media (max-width: 720px) {
  .header,
  .main-content,
  .login-shell {
    padding-left: 12px;
    padding-right: 12px;
  }

  .header-right {
    align-items: flex-start;
    flex-direction: column;
  }

  .login-copy,
  .login-card {
    padding: 22px;
  }

  .login-copy h2 {
    font-size: 24px;
  }
}
</style>
