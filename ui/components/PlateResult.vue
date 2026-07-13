<script setup>
import { computed } from 'vue'
import { ElCard, ElTable, ElTableColumn, ElTag } from 'element-plus'

const props = defineProps({
  latestResult: {
    type: Object,
    default: null
  },
  records: {
    type: Array,
    default: () => []
  }
})

const formatTime = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  return date.toLocaleString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

const whitelistStatus = computed(() => {
  if (!props.latestResult) return { text: '-', type: 'info' }
  const isInList = props.latestResult.data?.is_in_whitelist
  return isInList ? { text: '是', type: 'success' } : { text: '否', type: 'danger' }
})

const decisionStatus = computed(() => {
  if (!props.latestResult) return { text: '-', type: 'info' }
  const decision = props.latestResult.data?.decision
  return decision === 'allow' ? { text: '允许', type: 'success' } : { text: '禁止', type: 'danger' }
})
</script>

<template>
  <div class="plate-result-container">
    <h3>车牌识别</h3>
    <ElCard title="最新识别结果" class="latest-card">
      <div v-if="latestResult" class="latest-info">
        <div class="info-row">
          <span class="label">车牌号：</span>
          <span class="value plate-number">{{ latestResult.data?.plate_number || '-' }}</span>
        </div>
        <div class="info-row">
          <span class="label">白名单：</span>
          <ElTag :type="whitelistStatus.type" size="small">{{ whitelistStatus.text }}</ElTag>
        </div>
        <div class="info-row">
          <span class="label">通行决策：</span>
          <ElTag :type="decisionStatus.type" size="small">{{ decisionStatus.text }}</ElTag>
        </div>
        <div class="info-row">
          <span class="label">识别时间：</span>
          <span class="value">{{ formatTime(latestResult.timestamp) }}</span>
        </div>
      </div>
      <div v-else class="no-data">
        暂无识别结果
      </div>
    </ElCard>

    <ElCard title="识别记录（最近10条）" class="records-card">
      <ElTable :data="records" stripe size="small" :max-height="300">
        <ElTableColumn type="index" label="序号" width="60" align="center" />
        <ElTableColumn label="车牌号" width="120">
          <template #default="{ row }">
            {{ row.plate_number || row.data?.plate_number || '-' }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="白名单" width="80" align="center">
          <template #default="{ row }">
            <ElTag :type="row.data?.is_in_whitelist ? 'success' : 'danger'" size="small">
              {{ row.data?.is_in_whitelist ? '是' : '否' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="决策" width="80" align="center">
          <template #default="{ row }">
            <ElTag :type="row.data?.decision === 'allow' ? 'success' : 'danger'" size="small">
              {{ row.data?.decision === 'allow' ? '允许' : '禁止' }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="时间" width="120">
          <template #default="{ row }">
            {{ formatTime(row.timestamp) }}
          </template>
        </ElTableColumn>
      </ElTable>
      <div v-if="records.length === 0" class="no-data">
        暂无记录
      </div>
    </ElCard>
  </div>
</template>

<style scoped>
.plate-result-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.plate-result-container h3 {
  font-size: 16px;
  color: #e0f2fe;
  margin: 0 0 12px;
}

.latest-card {
  :deep(.el-card__header) {
    padding: 12px 16px;
    font-size: 16px;
    font-weight: 600;
    color: #e0f2fe;
    background: rgba(15, 23, 42, 0.6);
    border-bottom: 1px solid rgba(56, 189, 248, 0.22);
  }

  :deep(.el-card__body) {
    padding: 16px;
  }
}

.latest-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.label {
  font-size: 14px;
  color: #93c5fd;
  min-width: 80px;
}

.value {
  font-size: 14px;
  color: #e0f2fe;
  font-weight: 500;
}

.plate-number {
  font-size: 18px;
  font-weight: 600;
  color: #67e8f9;
  letter-spacing: 2px;
  text-shadow: 0 0 14px rgba(34, 211, 238, 0.44);
}

.no-data {
  text-align: center;
  color: #93c5fd;
  font-size: 14px;
  padding: 20px;
}

.records-card {
  :deep(.el-card__header) {
    padding: 12px 16px;
    font-size: 16px;
    font-weight: 600;
    color: #e0f2fe;
    background: rgba(15, 23, 42, 0.6);
    border-bottom: 1px solid rgba(56, 189, 248, 0.22);
  }

  :deep(.el-card__body) {
    padding: 16px;
    padding-top: 12px;
  }
}
</style>
