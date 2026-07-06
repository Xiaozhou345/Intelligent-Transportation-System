<script setup>
import { ref, watch } from 'vue'
import { ElTable, ElTableColumn, ElTag, ElNotification } from 'element-plus'

const props = defineProps({
  records: {
    type: Array,
    default: () => []
  }
})

const displayRecords = ref([])

const anomalyTypeMap = {
  unknown_object: '不明物体',
  fallen_object: '掉落物',
  debris: '杂物'
}

const laneMap = {
  lane_1: '第一车道',
  lane_2: '第二车道',
  lane_3: '第三车道'
}

const formatTime = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  const hours = date.getHours().toString().padStart(2, '0')
  const minutes = date.getMinutes().toString().padStart(2, '0')
  const seconds = date.getSeconds().toString().padStart(2, '0')
  return `${hours}:${minutes}:${seconds}`
}

const formatBbox = (bbox) => {
  if (!bbox || !Array.isArray(bbox)) return '-'
  return `(${Math.round(bbox[0])}, ${Math.round(bbox[1])})`
}

const getAnomalyTypeText = (type) => {
  return anomalyTypeMap[type] || type
}

const getLaneText = (lane) => {
  return laneMap[lane] || lane
}

const getStatusText = (status) => {
  return status === 'warning' ? '告警中' : '已恢复'
}

const getStatusType = (status) => {
  return status === 'warning' ? 'danger' : 'success'
}

const handleRowClass = ({ row }) => {
  return row.status === 'warning' ? 'anomaly-row-highlight' : ''
}

watch(() => props.records, (newRecords) => {
  displayRecords.value = [...newRecords].slice(0, 20)
}, { deep: true, immediate: true })

watch(() => props.records.length, (newLen, oldLen) => {
  if (newLen > oldLen) {
    const newAlarm = props.records[0]
    if (newAlarm) {
      ElNotification({
        title: '⚠️ 道路异常',
        message: `异常类型: ${getAnomalyTypeText(newAlarm.data?.anomaly_type)}\n影响车道: ${getLaneText(newAlarm.data?.affected_lane)}`,
        type: newAlarm.status === 'warning' ? 'warning' : 'info',
        duration: 5000
      })
    }
  }
})
</script>

<template>
  <div class="road-anomaly-alarm">
    <h3>道路异常告警</h3>
    <ElTable 
      :data="displayRecords" 
      stripe 
      size="small" 
      :max-height="350"
      :row-class-name="handleRowClass"
    >
      <ElTableColumn type="index" label="序号" width="50" align="center" />
      <ElTableColumn prop="timestamp" label="告警时间" width="100" align="center">
        <template #default="{ row }">
          {{ formatTime(row.timestamp) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="异常类型" width="100" align="center">
        <template #default="{ row }">
          <ElTag :type="row.status === 'warning' ? 'danger' : 'info'" size="small">
            {{ getAnomalyTypeText(row.data?.anomaly_type) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="影响车道" width="100" align="center">
        <template #default="{ row }">
          {{ getLaneText(row.data?.affected_lane) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="位置" width="100" align="center">
        <template #default="{ row }">
          {{ formatBbox(row.bbox) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="持续帧数" width="90" align="center">
        <template #default="{ row }">
          {{ row.data?.duration_frames || 0 }}帧
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="80" align="center">
        <template #default="{ row }">
          <ElTag :type="getStatusType(row.status)" size="small">
            {{ getStatusText(row.status) }}
          </ElTag>
        </template>
      </ElTableColumn>
    </ElTable>
    <div v-if="displayRecords.length === 0" class="empty-tip">
      暂无道路异常告警记录
    </div>
  </div>
</template>

<style scoped>
.road-anomaly-alarm {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  margin-top: 16px;
}

.road-anomaly-alarm h3 {
  font-size: 16px;
  color: #303133;
  margin-bottom: 12px;
}

.anomaly-row-highlight {
  background-color: #fef0f0 !important;
}

.anomaly-row-highlight td {
  border-color: #ffccc7 !important;
}

.empty-tip {
  text-align: center;
  color: #909399;
  padding: 20px;
  font-size: 14px;
}
</style>