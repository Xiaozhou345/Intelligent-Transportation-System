<script setup>
import { computed, reactive } from 'vue'
import { ElTable, ElTableColumn, ElTag, ElSelect, ElOption, ElInput, ElButton } from 'element-plus'

const props = defineProps({
  events: {
    type: Array,
    default: () => []
  }
})

const filters = reactive({
  eventType: '',
  keyword: '',
  status: ''
})

const eventOptions = [
  { label: '全部事件', value: '' },
  { label: '车辆检测', value: 'vehicle_detection' },
  { label: '车牌识别', value: 'plate_recognition' },
  { label: '拥堵分析', value: 'traffic_density' },
  { label: '违停告警', value: 'illegal_parking' },
  { label: '道路异常', value: 'road_anomaly' }
]

const statusOptions = [
  { label: '全部状态', value: '' },
  { label: '正常', value: 'normal' },
  { label: '告警', value: 'warning' },
  { label: '已确认', value: 'acknowledged' },
  { label: '已解除', value: 'resolved' }
]

const eventTypeText = {
  vehicle_detection: '车辆检测',
  plate_recognition: '车牌识别',
  traffic_density: '拥堵分析',
  illegal_parking: '违停告警',
  road_anomaly: '道路异常',
  system_status: '系统状态',
  client_command: '控制指令'
}

const filteredEvents = computed(() => {
  const keyword = filters.keyword.trim().toLowerCase()
  return props.events
    .filter(event => !filters.eventType || event.event_type === filters.eventType)
    .filter(event => !filters.status || event.status === filters.status)
    .filter(event => {
      if (!keyword) return true
      return JSON.stringify(event).toLowerCase().includes(keyword)
    })
    .slice(0, 50)
})

const resetFilters = () => {
  filters.eventType = ''
  filters.keyword = ''
  filters.status = ''
}

const formatTime = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const formatDetail = (event) => {
  const data = event.data || {}
  if (event.event_type === 'plate_recognition') return data.plate_number || '-'
  if (event.event_type === 'vehicle_detection') return `${data.vehicle_type || 'vehicle'} ${Math.round((data.confidence || 0) * 100)}%`
  if (event.event_type === 'illegal_parking') return `车辆${data.track_id || '-'} 停留${Math.round(data.stay_time || 0)}秒`
  if (event.event_type === 'road_anomaly') return `${data.anomaly_type || '-'} / ${data.affected_lane || '-'}`
  if (event.event_type === 'traffic_density') return `区域 ${Array.isArray(data.regions) ? data.regions.length : 0} 个`
  return event.summary || '-'
}
</script>

<template>
  <section class="history-query">
    <div class="section-header">
      <h2>历史查询</h2>
      <span>最近 50 条事件</span>
    </div>

    <div class="filters">
      <ElSelect v-model="filters.eventType" size="small" class="filter-control">
        <ElOption v-for="option in eventOptions" :key="option.value" :label="option.label" :value="option.value" />
      </ElSelect>
      <ElSelect v-model="filters.status" size="small" class="filter-control">
        <ElOption v-for="option in statusOptions" :key="option.value" :label="option.label" :value="option.value" />
      </ElSelect>
      <ElInput v-model="filters.keyword" size="small" placeholder="车牌、设备、车道关键字" clearable />
      <ElButton size="small" @click="resetFilters">重置</ElButton>
    </div>

    <ElTable :data="filteredEvents" stripe size="small" max-height="320">
      <ElTableColumn label="时间" width="130">
        <template #default="{ row }">{{ formatTime(row.timestamp) }}</template>
      </ElTableColumn>
      <ElTableColumn label="类型" width="100">
        <template #default="{ row }">
          <ElTag size="small">{{ eventTypeText[row.event_type] || row.event_type }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="设备" width="110" prop="device_id" />
      <ElTableColumn label="详情">
        <template #default="{ row }">{{ formatDetail(row) }}</template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="90" align="center">
        <template #default="{ row }">
          <ElTag :type="row.status === 'warning' ? 'danger' : row.status === 'resolved' ? 'success' : 'info'" size="small">
            {{ row.status || 'normal' }}
          </ElTag>
        </template>
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
}

.section-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.section-header span {
  color: #93c5fd;
  font-size: 12px;
}

.filters {
  display: grid;
  grid-template-columns: 130px 120px 1fr 72px;
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
