<script setup>
import { ref, watch } from 'vue'
import { ElButton, ElDialog, ElInput, ElTable, ElTableColumn, ElTag, ElNotification } from 'element-plus'

const props = defineProps({
  records: {
    type: Array,
    default: () => []
  },
  canDispose: {
    type: Boolean,
    default: true
  }
})

const emit = defineEmits(['new-alarm', 'dispose-alarm'])

const displayRecords = ref([])
const acknowledgedKeys = ref(new Set())
const showDetailDialog = ref(false)
const showDisposeDialog = ref(false)
const currentAlarm = ref(null)
const disposeNote = ref('现场已确认，持续关注')

const getAlarmKey = (row) => `${row.timestamp || ''}-${row.data?.track_id || row.track_id || ''}`

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
  return status === 'acknowledged' ? '已确认' : status === 'warning' ? '告警中' : '已解除'
}

const getStatusType = (status) => {
  if (status === 'acknowledged') return 'warning'
  return status === 'warning' ? 'danger' : 'success'
}

const handleRowClass = ({ row }) => {
  return getDisplayStatus(row) === 'warning' ? 'alarm-row-highlight' : ''
}

const getDisplayStatus = (row) => {
  return acknowledgedKeys.value.has(getAlarmKey(row)) ? 'acknowledged' : row.status
}

const handleAcknowledge = (row) => {
  currentAlarm.value = row
  disposeNote.value = '现场已确认，持续关注'
  showDisposeDialog.value = true
}

const confirmAcknowledge = () => {
  if (!currentAlarm.value) return
  const next = new Set(acknowledgedKeys.value)
  next.add(getAlarmKey(currentAlarm.value))
  acknowledgedKeys.value = next
  emit('dispose-alarm', {
    action: 'acknowledged',
    eventType: 'illegal_parking',
    alarm: currentAlarm.value,
    note: disposeNote.value
  })
  showDisposeDialog.value = false
}

const handleViewDetail = (row) => {
  currentAlarm.value = row
  showDetailDialog.value = true
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
          <ElTag :type="getStatusType(getDisplayStatus(row))" size="small">
            {{ getStatusText(getDisplayStatus(row)) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="120" align="center">
        <template #default="{ row }">
          <ElButton type="primary" link size="small" @click="handleViewDetail(row)">详情</ElButton>
          <ElButton
            v-if="getDisplayStatus(row) === 'warning'"
            v-show="canDispose"
            type="warning"
            link
            size="small"
            @click="handleAcknowledge(row)"
          >
            确认
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    <div v-if="displayRecords.length === 0" class="empty-tip">
      暂无违停告警记录
    </div>

    <ElDialog title="违停告警详情" v-model="showDetailDialog" width="460px">
      <div v-if="currentAlarm" class="alarm-detail">
        <div><span>车辆ID</span><strong>{{ currentAlarm.data?.track_id || currentAlarm.track_id || '-' }}</strong></div>
        <div><span>告警时间</span><strong>{{ formatTime(currentAlarm.timestamp) }}</strong></div>
        <div><span>停留时长</span><strong>{{ Math.round(currentAlarm.data?.stay_time || 0) }} 秒</strong></div>
        <div><span>预设阈值</span><strong>{{ currentAlarm.data?.threshold || 30 }} 秒</strong></div>
        <div><span>目标位置</span><strong>{{ formatBbox(currentAlarm.bbox) }}</strong></div>
        <div><span>处置状态</span><strong>{{ getStatusText(getDisplayStatus(currentAlarm)) }}</strong></div>
      </div>
      <template #footer>
        <ElButton @click="showDetailDialog = false">关闭</ElButton>
        <ElButton
          v-if="currentAlarm && getDisplayStatus(currentAlarm) === 'warning'"
          v-show="canDispose"
          type="primary"
          @click="handleAcknowledge(currentAlarm); showDetailDialog = false"
        >
          确认告警
        </ElButton>
      </template>
    </ElDialog>

    <ElDialog title="确认违停告警" v-model="showDisposeDialog" width="420px">
      <div class="dispose-form">
        <span>处置备注</span>
        <ElInput
          v-model="disposeNote"
          type="textarea"
          :rows="3"
          maxlength="80"
          show-word-limit
        />
      </div>
      <template #footer>
        <ElButton @click="showDisposeDialog = false">取消</ElButton>
        <ElButton type="primary" @click="confirmAcknowledge">确认处置</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.illegal-parking-alarm {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.illegal-parking-alarm h3 {
  font-size: 16px;
  color: #e0f2fe;
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
  color: #93c5fd;
  padding: 20px;
  font-size: 14px;
}

.alarm-detail {
  display: grid;
  gap: 10px;
}

.alarm-detail div {
  align-items: center;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
}

.alarm-detail span {
  color: #93c5fd;
  font-size: 13px;
}

.alarm-detail strong {
  color: #e0f2fe;
  font-size: 14px;
}

.dispose-form {
  display: grid;
  gap: 8px;
}

.dispose-form span {
  color: #93c5fd;
  font-size: 13px;
}
</style>
