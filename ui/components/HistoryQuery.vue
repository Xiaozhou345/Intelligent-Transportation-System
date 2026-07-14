<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElTable, ElTableColumn, ElTag, ElSelect, ElOption, ElInput, ElButton } from 'element-plus'

const props = defineProps({
  cloudServerUrl: {
    type: String,
    required: true
  }
})

const filters = reactive({
  eventType: '',
  keyword: ''
})

const events = ref([])
const loading = ref(false)

const eventOptions = [
  { label: '全部业务事件', value: '' },
  { label: '车辆检测', value: 'vehicle_detection' },
  { label: '车牌识别', value: 'plate_recognition' },
  { label: '拥堵分析', value: 'traffic_density' },
  { label: '违停告警', value: 'illegal_parking' },
  { label: '道路异常', value: 'road_anomaly' },
  { label: '告警处置', value: 'alarm_disposition' }
]

const eventTypeText = {
  vehicle_detection: '车辆检测',
  plate_recognition: '车牌识别',
  traffic_density: '拥堵分析',
  illegal_parking: '违停告警',
  road_anomaly: '道路异常',
  video_overlay: '画框快照',
  system_status: '系统状态',
  client_command: '控制指令',
  alarm_disposition: '告警处置',
  user_login: '用户登录',
  user_logout: '用户退出'
}

// 从后端加载历史数据
const loadEvents = async () => {
  loading.value = true
  try {
    const params = new URLSearchParams({ limit: '10' })
    if (filters.eventType) {
      params.append('event_type', filters.eventType)
    }

    const response = await fetch(`${props.cloudServerUrl}/api/history/events?${params}`)
    if (response.ok) {
      const data = await response.json()
      if (data.status === 'success') {
        // 转换数据格式
        events.value = data.data.map(event => {
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
            status: parsedData.status || 'normal',
            data: parsedData.data || parsedData,
            plate_number: event.plate_number
          }
        })
      }
    }
  } catch (error) {
    console.error('加载历史数据失败:', error)
  } finally {
    loading.value = false
  }
}

// 监听事件类型筛选变化，重新加载数据
watch(() => filters.eventType, () => {
  loadEvents()
})

// 组件挂载时加载初始数据
loadEvents()

const filteredEvents = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return events.value
    .filter(event => {
      if (!keyword) return true
      return JSON.stringify(event).toLowerCase().includes(keyword)
    })
    .slice(0, 10)
})

const resetFilters = () => {
  filters.eventType = ''
  filters.keyword = ''
}

const downloadFile = (filename, content, mimeType) => {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const sanitizeEventForExport = (event) => {
  const data = { ...(event.data || {}) }
  delete data.image
  delete data.frame
  delete data.frame_image
  delete data.image_base64
  return {
    time: formatTime(event.timestamp),
    type: eventTypeText[event.event_type] || event.event_type || '',
    device: event.device_id || '',
    status: event.status || 'normal',
    detail: formatDetail(event),
    data
  }
}

const exportJson = () => {
  const exportData = {
    exportedAt: new Date().toISOString(),
    source: 'business_history_events',
    count: filteredEvents.value.length,
    records: filteredEvents.value.map(sanitizeEventForExport)
  }
  downloadFile(
    `its-events-${Date.now()}.json`,
    JSON.stringify(exportData, null, 2),
    'application/json;charset=utf-8'
  )
}

const exportCsv = () => {
  const header = ['time', 'type', 'device', 'status', 'detail']
  const rows = filteredEvents.value.map(event => [
    formatTime(event.timestamp),
    eventTypeText[event.event_type] || event.event_type || '',
    event.device_id || '',
    event.status || 'normal',
    formatDetail(event)
  ])
  const csv = [header, ...rows]
    .map(row => row.map(cell => `"${String(cell).replaceAll('"', '""')}"`).join(','))
    .join('\n')
  downloadFile(`its-events-${Date.now()}.csv`, csv, 'text/csv;charset=utf-8')
}

const formatTime = (timestamp) => {
  if (!timestamp) return '-'

  // 后端返回格式：'2026-07-12 23:00:31'
  // 直接解析并格式化为 MM/DD HH:mm:ss
  try {
    // 解析时间字符串（本地时间，不做时区转换）
    const match = timestamp.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/)
    if (match) {
      const [_, year, month, day, hour, minute, second] = match
      return `${month}/${day} ${hour}:${minute}:${second}`
    }

    // 如果格式不匹配，尝试用Date解析（兼容旧格式）
    const date = new Date(timestamp)
    if (!Number.isNaN(date.getTime())) {
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hour = String(date.getHours()).padStart(2, '0')
      const minute = String(date.getMinutes()).padStart(2, '0')
      const second = String(date.getSeconds()).padStart(2, '0')
      return `${month}/${day} ${hour}:${minute}:${second}`
    }
  } catch (e) {
    console.warn('时间格式化失败:', timestamp, e)
  }

  return timestamp
}

const formatDetail = (event) => {
  const data = event.data || {}

  if (event.event_type === 'plate_recognition') {
    // 车牌识别：显示车牌号
    return event.plate_number || data.plate_number || '-'
  }

  if (event.event_type === 'vehicle_detection') {
    // 车辆检测：显示车辆类型和置信度
    const vehicleType = data.vehicle_type || data.class_name || '车辆'
    const confidence = data.confidence ? `${Math.round(data.confidence * 100)}%` : ''
    const trackId = data.track_id ? ` [ID:${data.track_id}]` : ''
    return `${vehicleType} ${confidence}${trackId}`.trim()
  }

  if (event.event_type === 'illegal_parking') {
    // 违停告警：显示车辆信息和停留时间
    const trackId = data.track_id || '-'
    const stayTime = data.stay_time ? Math.round(data.stay_time) : 0
    const plate = data.plate_number || event.plate_number || ''
    return plate ? `${plate} 停留${stayTime}秒` : `车辆${trackId} 停留${stayTime}秒`
  }

  if (event.event_type === 'road_anomaly') {
    // 道路异常：显示异常类型和受影响车道
    const anomalyType = data.anomaly_type || data.type || '异常'
    const lane = data.affected_lane || data.lane || '-'
    const severity = data.severity ? ` (${data.severity})` : ''
    return `${anomalyType} / 车道${lane}${severity}`
  }

  if (event.event_type === 'traffic_density') {
    // 拥堵分析：显示拥堵区域数量和等级
    const regionCount = Array.isArray(data.regions) ? data.regions.length : (data.region_count || 0)
    const level = data.congestion_level || ''
    return level ? `${level} / ${regionCount}个区域` : `${regionCount}个区域`
  }

  if (event.event_type === 'video_overlay') {
    // 画框快照：显示各类目标数量
    const vehicles = Array.isArray(data.vehicles) ? data.vehicles.length : 0
    const plates = Array.isArray(data.plates) ? data.plates.length : 0
    const parking = Array.isArray(data.illegal_parking) ? data.illegal_parking.length : 0
    const anomalies = Array.isArray(data.road_anomalies) ? data.road_anomalies.length : 0
    const total = vehicles + plates + parking + anomalies
    return `车辆${vehicles} 车牌${plates} 违停${parking} 异常${anomalies} (共${total})`
  }

  if (event.event_type === 'alarm_disposition') {
    // 告警处置：显示处理人和备注
    const operator = data.operator || '-'
    const note = data.note || '已处理'
    return `${operator} / ${note}`
  }

  // 其他类型：显示摘要或原始数据的描述
  return event.summary || data.description || data.message || '-'
}
</script>

<template>
  <section class="history-query">
    <div class="section-header">
      <h2>历史查询</h2>
      <div class="header-actions">
        <span>最近 10 条业务事件</span>
        <ElButton size="small" @click="exportCsv">CSV</ElButton>
        <ElButton size="small" @click="exportJson">JSON</ElButton>
      </div>
    </div>

    <div class="filters">
      <ElSelect v-model="filters.eventType" size="small" class="filter-control" placeholder="事件类型">
        <ElOption v-for="option in eventOptions" :key="option.value" :label="option.label" :value="option.value" />
      </ElSelect>
      <ElInput v-model="filters.keyword" size="small" placeholder="车牌、设备、车道关键字" clearable />
      <ElButton size="small" @click="resetFilters">重置</ElButton>
    </div>

    <ElTable :data="filteredEvents" stripe size="small" max-height="320">
      <ElTableColumn label="时间">
        <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
      </ElTableColumn>
      <ElTableColumn label="类型">
        <template #default="{ row }">
          <ElTag size="small">{{ eventTypeText[row.event_type] || row.event_type }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="设备" prop="device_id" />
      <ElTableColumn label="详情">
        <template #default="{ row }">{{ formatDetail(row) }}</template>
      </ElTableColumn>
    </ElTable>
  </section>
</template>

<style scoped>
.history-query {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.section-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}

.section-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.section-header span {
  color: #93c5fd;
  font-size: 12px;
}

.header-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}

.filters {
  display: grid;
  grid-template-columns: 130px 1fr 72px;
  gap: 8px;
  margin-bottom: 12px;
}

.filter-control {
  width: 100%;
}

@media (max-width: 900px) {
  .filters {
    grid-template-columns: 1fr;
  }
}
</style>
