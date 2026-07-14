<script setup>
import { computed } from 'vue'
import { ElButton, ElTable, ElTableColumn, ElTag } from 'element-plus'

const props = defineProps({
  records: {
    type: Array,
    default: () => []
  }
})

const displayRecords = computed(() => props.records.slice(0, 12))

const actionText = {
  acknowledged: '已确认',
  resolved: '已解除',
  false_alarm: '误报'
}

const actionType = {
  acknowledged: 'warning',
  resolved: 'success',
  false_alarm: 'info'
}

const alarmTypeText = {
  illegal_parking: '违停告警',
  road_anomaly: '道路异常'
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

const downloadFile = (filename, content, mimeType) => {
  const blob = new Blob([content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const exportLedger = () => {
  const exportData = {
    exportedAt: new Date().toISOString(),
    source: 'database_latest_10',
    count: props.records.length,
    records: props.records
  }
  downloadFile(
    `its-alarm-dispositions-${Date.now()}.json`,
    JSON.stringify(exportData, null, 2),
    'application/json;charset=utf-8'
  )
}
</script>

<template>
  <section class="alarm-workbench">
    <div class="section-header">
      <div>
        <h2>告警处置台账</h2>
        <p>{{ records.length }} 条处置记录（最新10条）</p>
      </div>
      <div class="header-actions">
        <ElButton size="small" :disabled="!records.length" @click="exportLedger">导出最新10条</ElButton>
      </div>
    </div>

    <ElTable v-if="displayRecords.length" :data="displayRecords" stripe size="small" max-height="300">
      <ElTableColumn label="时间" width="130">
        <template #default="{ row }">{{ formatTime(row.handledAt) }}</template>
      </ElTableColumn>
      <ElTableColumn label="类型" width="96">
        <template #default="{ row }">{{ alarmTypeText[row.eventType] || row.eventType }}</template>
      </ElTableColumn>
      <ElTableColumn label="结果" width="84" align="center">
        <template #default="{ row }">
          <ElTag :type="actionType[row.action] || 'info'" size="small">
            {{ actionText[row.action] || row.action }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="处理人" width="90" prop="operator" />
      <ElTableColumn label="备注" prop="note" />
    </ElTable>

    <div v-else class="empty-state">暂无告警处置记录</div>
  </section>
</template>

<style scoped>
.alarm-workbench {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: #dbeafe;
  padding: 16px;
}

.section-header {
  align-items: center;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.section-header p,
.empty-state {
  color: #93c5fd;
  font-size: 12px;
  margin-top: 4px;
}

.empty-state {
  padding: 28px 0;
  text-align: center;
}

.header-actions {
  align-items: center;
  display: flex;
  gap: 8px;
}
</style>
