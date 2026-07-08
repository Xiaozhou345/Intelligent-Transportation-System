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

const getVehicleTypeText = (type) => {
  return type || 'vehicle'
}

const formatConfidence = (value) => {
  if (value === undefined || value === null) return '-'
  return `${Math.round(value * 100)}%`
}

watch(() => props.records, (newRecords) => {
  displayRecords.value = [...newRecords].slice(0, 20)
}, { deep: true, immediate: true })

watch(() => props.records.length, (newLen, oldLen) => {
  if (newLen > oldLen) {
    const detection = props.records[0]
    if (detection) {
      ElNotification({
        title: '🚗 车辆检测',
        message: `类型: ${getVehicleTypeText(detection.data?.vehicle_type)}\n置信度: ${formatConfidence(detection.data?.confidence)}`,
        type: 'success',
        duration: 3000
      })
    }
  }
})
</script>

<template>
  <div class="vehicle-detection-panel">
    <h3>车辆检测记录</h3>
    <ElTable :data="displayRecords" stripe size="small" :max-height="320">
      <ElTableColumn type="index" label="序号" width="50" align="center" />
      <ElTableColumn prop="timestamp" label="检测时间" width="100" align="center">
        <template #default="{ row }">
          {{ formatTime(row.timestamp) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="车辆类型" width="110" align="center">
        <template #default="{ row }">
          <ElTag type="success" size="small">
            {{ getVehicleTypeText(row.data?.vehicle_type) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="置信度" width="90" align="center">
        <template #default="{ row }">
          {{ formatConfidence(row.data?.confidence) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="位置" width="100" align="center">
        <template #default="{ row }">
          {{ formatBbox(row.bbox) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="车牌" width="110" align="center">
        <template #default="{ row }">
          {{ row.data?.plate_number || '未识别' }}
        </template>
      </ElTableColumn>
    </ElTable>
    <div v-if="displayRecords.length === 0" class="empty-tip">
      暂无车辆检测记录
    </div>
  </div>
</template>

<style scoped>
.vehicle-detection-panel {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  margin-top: 16px;
}

.vehicle-detection-panel h3 {
  font-size: 16px;
  color: #303133;
  margin-bottom: 12px;
}

.empty-tip {
  text-align: center;
  color: #909399;
  padding: 20px;
  font-size: 14px;
}
</style>
