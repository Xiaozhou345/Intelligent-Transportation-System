<script setup>
import { computed, ref } from 'vue'
import { ElTag } from 'element-plus'

const props = defineProps({
  events: {
    type: Array,
    default: () => []
  }
})

const eventTypeMap = {
  vehicle_detection: { label: '车辆检测', type: 'success' },
  plate_recognition: { label: '车牌识别', type: 'primary' },
  traffic_density: { label: '拥堵分析', type: 'warning' },
  illegal_parking: { label: '违停告警', type: 'danger' },
  road_anomaly: { label: '道路异常', type: 'danger' },
  video_overlay: { label: '画框快照', type: 'info' },
  system_status: { label: '系统状态', type: 'info' },
  connection_status: { label: '连接状态', type: 'info' },
  client_command: { label: '控制指令', type: 'info' },
  alarm_disposition: { label: '告警处置', type: 'success' },
  user_login: { label: '用户登录', type: 'primary' },
  user_logout: { label: '用户退出', type: 'info' }
}

const activeFilter = ref('all')

const filterOptions = [
  { label: '全部', value: 'all' },
  { label: '告警', value: 'alarm' },
  { label: '识别', value: 'recognition' },
  { label: '系统', value: 'system' }
]

const filteredEvents = computed(() => {
  if (activeFilter.value === 'alarm') {
    return props.events.filter(event => event.event_type === 'illegal_parking' || event.event_type === 'road_anomaly' || event.status === 'warning')
  }
  if (activeFilter.value === 'recognition') {
    return props.events.filter(event => event.event_type === 'vehicle_detection' || event.event_type === 'plate_recognition')
  }
  if (activeFilter.value === 'system') {
    return props.events.filter(event => event.event_type === 'system_status' || event.event_type === 'connection_status' || event.event_type === 'client_command' || event.event_type === 'user_login' || event.event_type === 'user_logout' || event.event_type === 'alarm_disposition')
  }
  return props.events
})

const alarmCount = computed(() => props.events.filter(event => event.status === 'warning' || event.event_type === 'illegal_parking' || event.event_type === 'road_anomaly').length)
const displayEvents = computed(() => filteredEvents.value.slice(0, 12))

const formatTime = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const getEventMeta = (eventType) => eventTypeMap[eventType] || { label: eventType || '未知事件', type: 'info' }

const getEventSummary = (event) => {
  const data = event.data || {}
  if (event.event_type === 'vehicle_detection') {
    return `${data.vehicle_type || 'vehicle'} / 置信度 ${Math.round((data.confidence || 0) * 100)}%`
  }
  if (event.event_type === 'plate_recognition') {
    return `${data.plate_number || '未识别'} / ${data.decision === 'allow' ? '允许通行' : '禁止通行'}`
  }
  if (event.event_type === 'traffic_density') {
    const total = Array.isArray(data.regions) ? data.regions.reduce((sum, item) => sum + (item.vehicle_count || 0), 0) : 0
    return `区域车辆数合计 ${total}`
  }
  if (event.event_type === 'video_overlay') {
    const data = event.data || {}
    const count = ['vehicles', 'plates', 'illegal_parking', 'road_anomalies']
      .reduce((sum, key) => sum + (Array.isArray(data[key]) ? data[key].length : 0), 0)
    return `当前帧叠加目标 ${count} 个`
  }
  if (event.event_type === 'illegal_parking') {
    return `车辆 ${data.track_id || '-'} 停留 ${Math.round(data.stay_time || 0)} 秒`
  }
  if (event.event_type === 'road_anomaly') {
    return `${data.anomaly_type || '异常'} / ${data.affected_lane || '未知车道'}`
  }
  if (event.event_type === 'client_command') {
    return event.command || '已发送控制指令'
  }
  if (event.event_type === 'alarm_disposition') {
    return `${data.operator || '-'} / ${data.note || '已处理'}`
  }
  return event.summary || '收到实时消息'
}
</script>

<template>
  <section class="event-stream">
    <div class="stream-header">
      <div>
        <h2>实时事件流</h2>
        <p>{{ events.length }} 条消息 / {{ alarmCount }} 条告警</p>
      </div>
      <span>LIVE</span>
    </div>

    <div class="stream-filters" aria-label="事件筛选">
      <button
        v-for="option in filterOptions"
        :key="option.value"
        :class="{ active: activeFilter === option.value }"
        type="button"
        @click="activeFilter = option.value"
      >
        {{ option.label }}
      </button>
    </div>

    <div v-if="displayEvents.length" class="timeline">
      <div v-for="event in displayEvents" :key="event.id" class="timeline-item">
        <div class="timeline-dot"></div>
        <div class="timeline-content">
          <div class="event-line">
            <ElTag :type="getEventMeta(event.event_type).type" size="small">
              {{ getEventMeta(event.event_type).label }}
            </ElTag>
            <span class="event-time">{{ formatTime(event.timestamp) }}</span>
          </div>
          <div class="event-summary">{{ getEventSummary(event) }}</div>
          <div class="event-device">{{ event.device_id || 'cloud_server' }}</div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">等待实时分析事件</div>
  </section>
</template>

<style scoped>
.event-stream {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.stream-header {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stream-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.stream-header span {
  border: 1px solid rgba(34, 211, 238, 0.28);
  border-radius: 999px;
  color: #67e8f9;
  font-size: 12px;
  font-weight: 800;
  padding: 3px 8px;
}

.stream-header p {
  color: #93c5fd;
  font-size: 12px;
  margin-top: 4px;
}

.stream-filters {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(4, 1fr);
  margin-bottom: 12px;
}

.stream-filters button {
  background: rgba(15, 23, 42, 0.7);
  border: 1px solid rgba(56, 189, 248, 0.16);
  border-radius: 7px;
  color: #93c5fd;
  cursor: pointer;
  font-size: 12px;
  height: 30px;
}

.stream-filters button.active,
.stream-filters button:hover {
  background: rgba(14, 165, 233, 0.18);
  border-color: rgba(34, 211, 238, 0.5);
  color: #e0f2fe;
  box-shadow: 0 0 16px rgba(34, 211, 238, 0.14);
}

.timeline {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 430px;
  overflow: auto;
  padding-right: 4px;
}

.timeline-item {
  display: grid;
  grid-template-columns: 12px 1fr;
  gap: 10px;
}

.timeline-dot {
  background: #22d3ee;
  border: 3px solid rgba(34, 211, 238, 0.2);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.62);
  border-radius: 50%;
  height: 12px;
  margin-top: 5px;
  width: 12px;
}

.timeline-content {
  border-bottom: 1px solid rgba(56, 189, 248, 0.14);
  padding-bottom: 10px;
}

.event-line {
  align-items: center;
  display: flex;
  gap: 8px;
  justify-content: space-between;
}

.event-time,
.event-device {
  color: #93c5fd;
  font-size: 12px;
}

.event-summary {
  color: #e0f2fe;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
  margin-top: 6px;
}

.event-device {
  margin-top: 4px;
}

.empty-state {
  color: #93c5fd;
  font-size: 14px;
  padding: 28px 0;
  text-align: center;
}
</style>
