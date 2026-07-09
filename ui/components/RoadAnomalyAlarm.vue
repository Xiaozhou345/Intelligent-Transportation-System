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

const emit = defineEmits(['dispose-alarm'])

const displayRecords = ref([])
const resolvedKeys = ref(new Set())
const showDetailDialog = ref(false)
const showDisposeDialog = ref(false)
const currentAlarm = ref(null)
const disposeNote = ref('已派人排查，异常解除')

const getAlarmKey = (row) => `${row.timestamp || ''}-${row.data?.anomaly_type || ''}-${row.data?.affected_lane || ''}`

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
  return getDisplayStatus(row) === 'warning' ? 'anomaly-row-highlight' : ''
}

const getDisplayStatus = (row) => {
  return resolvedKeys.value.has(getAlarmKey(row)) ? 'resolved' : row.status
}

const handleResolve = (row) => {
  currentAlarm.value = row
  disposeNote.value = '已派人排查，异常解除'
  showDisposeDialog.value = true
}

const confirmResolve = () => {
  if (!currentAlarm.value) return
  const next = new Set(resolvedKeys.value)
  next.add(getAlarmKey(currentAlarm.value))
  resolvedKeys.value = next
  emit('dispose-alarm', {
    action: 'resolved',
    eventType: 'road_anomaly',
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
            type="success"
            link
            size="small"
            @click="handleResolve(row)"
          >
            解除
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    <div v-if="displayRecords.length === 0" class="empty-tip">
      暂无道路异常告警记录
    </div>

    <ElDialog title="道路异常详情" v-model="showDetailDialog" width="460px">
      <div v-if="currentAlarm" class="alarm-detail">
        <div><span>异常类型</span><strong>{{ getAnomalyTypeText(currentAlarm.data?.anomaly_type) }}</strong></div>
        <div><span>影响车道</span><strong>{{ getLaneText(currentAlarm.data?.affected_lane) }}</strong></div>
        <div><span>告警时间</span><strong>{{ formatTime(currentAlarm.timestamp) }}</strong></div>
        <div><span>持续帧数</span><strong>{{ currentAlarm.data?.duration_frames || 0 }} 帧</strong></div>
        <div><span>目标位置</span><strong>{{ formatBbox(currentAlarm.bbox) }}</strong></div>
        <div><span>处置状态</span><strong>{{ getStatusText(getDisplayStatus(currentAlarm)) }}</strong></div>
      </div>
      <template #footer>
        <ElButton @click="showDetailDialog = false">关闭</ElButton>
        <ElButton
          v-if="currentAlarm && getDisplayStatus(currentAlarm) === 'warning'"
          v-show="canDispose"
          type="primary"
          @click="handleResolve(currentAlarm); showDetailDialog = false"
        >
          解除告警
        </ElButton>
      </template>
    </ElDialog>

    <ElDialog title="解除道路异常告警" v-model="showDisposeDialog" width="420px">
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
        <ElButton type="primary" @click="confirmResolve">确认解除</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.road-anomaly-alarm {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  margin-top: 16px;
}

.road-anomaly-alarm h3 {
  font-size: 16px;
  color: #e0f2fe;
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
