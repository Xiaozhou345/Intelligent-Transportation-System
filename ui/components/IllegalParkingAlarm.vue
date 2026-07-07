<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { ElTable, ElTableColumn, ElTag, ElNotification } from 'element-plus'

const props = defineProps({
  records: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits(['new-alarm'])

const displayRecords = ref([])

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

const getStatusText = (status) => {
  return status === 'warning' ? '告警中' : '已解除'
}

const getStatusType = (status) => {
  return status === 'warning' ? 'danger' : 'success'
}

const handleRowClass = ({ row }) => {
  return row.status === 'warning' ? 'alarm-row-highlight' : ''
}

watch(() => props.records, (newRecords) => {
  displayRecords.value = [...newRecords].slice(0, 20)
}, { deep: true, immediate: true })

watch(() => props.records.length, (newLen, oldLen) => {
  if (newLen > oldLen) {
    const newAlarm = props.records[0]
    if (newAlarm) {
      ElNotification({
        title: '违停告警',
        message: `车辆ID: ${newAlarm.data?.track_id || newAlarm.track_id}\n停留时长: ${newAlarm.data?.stay_time || 0}秒`,
        type: newAlarm.status === 'warning' ? 'warning' : 'info',
        duration: 5000
      })
    }
  }
})
</script>

<template>
  <div class="illegal-parking-alarm">
    <h3>违停告警</h3>
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
      <ElTableColumn label="车辆ID" width="100" align="center">
        <template #default="{ row }">
          {{ row.data?.track_id || row.track_id || '-' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="停留时长" width="90" align="center">
        <template #default="{ row }">
          <span>{{ row.data?.stay_time || 0 }}</span>秒
        </template>
      </ElTableColumn>
      <ElTableColumn label="位置" width="100" align="center">
        <template #default="{ row }">
          {{ formatBbox(row.bbox) }}
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
      暂无违停告警记录
    </div>
  </div>
</template>

<style scoped>
.illegal-parking-alarm {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  margin-top: 16px;
}

.illegal-parking-alarm h3 {
  font-size: 16px;
  color: #303133;
  margin-bottom: 12px;
}

.alarm-row-highlight {
  background-color: #fef0f0 !important;
}

.alarm-row-highlight td {
  border-color: #ffccc7 !important;
}

.empty-tip {
  text-align: center;
  color: #909399;
  padding: 20px;
  font-size: 14px;
}
</style>