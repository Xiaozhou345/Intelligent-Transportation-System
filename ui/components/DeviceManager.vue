<script setup>
import { ref, reactive, watch } from 'vue'
import { ElTable, ElTableColumn, ElButton, ElDialog, ElForm, ElFormItem, ElInput, ElMessage } from 'element-plus'

const props = defineProps({
  devices: {
    type: Array,
    default: () => []
  },
  canConfigure: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['add-device'])

const displayDevices = ref([])
const showAddDialog = ref(false)
const showDetailDialog = ref(false)
const currentDevice = ref(null)

const form = reactive({
  device_id: '',
  device_type: '',
  scene_id: ''
})

const getStatusText = (status) => {
  return status === 'online' ? '在线' : '离线'
}

const getStatusClass = (status) => {
  return status === 'online' ? 'status-online' : 'status-offline'
}

const formatHeartbeat = (timestamp) => {
  if (!timestamp) return '-'
  const date = new Date(timestamp)
  if (isNaN(date.getTime())) return timestamp
  const hours = date.getHours().toString().padStart(2, '0')
  const minutes = date.getMinutes().toString().padStart(2, '0')
  const seconds = date.getSeconds().toString().padStart(2, '0')
  const month = (date.getMonth() + 1).toString().padStart(2, '0')
  const day = date.getDate().toString().padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day} ${hours}:${minutes}:${seconds}`
}

const handleAddDevice = () => {
  if (!form.device_id || !form.device_type || !form.scene_id) {
    ElMessage.warning('请填写完整的设备信息')
    return
  }
  
  const newDevice = {
    device_id: form.device_id,
    device_type: form.device_type,
    scene_id: form.scene_id,
    status: 'online',
    last_heartbeat: new Date().toISOString()
  }
  
  emit('add-device', newDevice)
  
  form.device_id = ''
  form.device_type = ''
  form.scene_id = ''
  showAddDialog.value = false
  
  ElMessage.success('已添加本地演示设备')
}

const handleViewDetail = (device) => {
  currentDevice.value = device
  showDetailDialog.value = true
}

watch(() => props.devices, (newDevices) => {
  displayDevices.value = [...newDevices]
}, { deep: true, immediate: true })
</script>

<template>
  <div class="device-manager">
    <div class="header">
      <h3>设备管理</h3>
      <ElButton v-if="canConfigure" type="primary" size="small" @click="showAddDialog = true">
        本地演示添加
      </ElButton>
    </div>
    
    <ElTable 
      :data="displayDevices" 
      stripe 
      size="small" 
      :max-height="200"
    >
      <ElTableColumn prop="device_id" label="设备编号" />
      <ElTableColumn prop="device_type" label="设备类型" />
      <ElTableColumn label="在线状态" align="center">
        <template #default="{ row }">
          <div class="status-cell">
            <span :class="['status-dot', getStatusClass(row.status)]"></span>
            <span class="status-text">{{ getStatusText(row.status) }}</span>
          </div>
        </template>
      </ElTableColumn>
      <ElTableColumn label="最后心跳" align="center">
        <template #default="{ row }">
          {{ formatHeartbeat(row.last_heartbeat) }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" align="center">
        <template #default="{ row }">
          <ElButton type="text" size="small" @click="handleViewDetail(row)">
            查看详情
          </ElButton>
        </template>
      </ElTableColumn>
    </ElTable>
    
    <div v-if="displayDevices.length === 0" class="empty-tip">
      暂无设备记录
    </div>
    
    <ElDialog title="本地演示添加设备" v-model="showAddDialog" width="400px">
      <ElForm :model="form" label-width="80px">
        <ElFormItem label="设备编号">
          <ElInput v-model="form.device_id" placeholder="请输入设备编号" />
        </ElFormItem>
        <ElFormItem label="设备类型">
          <ElInput v-model="form.device_type" placeholder="请输入设备类型" />
        </ElFormItem>
        <ElFormItem label="场景编号">
          <ElInput v-model="form.scene_id" placeholder="请输入场景编号" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="showAddDialog = false">取消</ElButton>
      <ElButton type="primary" @click="handleAddDevice">确定</ElButton>
    </template>
  </ElDialog>

    <ElDialog title="设备详情" v-model="showDetailDialog" width="460px">
      <div v-if="currentDevice" class="device-detail">
        <div>
          <span>设备编号</span>
          <strong>{{ currentDevice.device_id }}</strong>
        </div>
        <div>
          <span>设备类型</span>
          <strong>{{ currentDevice.device_type }}</strong>
        </div>
        <div>
          <span>场景编号</span>
          <strong>{{ currentDevice.scene_id }}</strong>
        </div>
        <div>
          <span>在线状态</span>
          <strong>{{ getStatusText(currentDevice.status) }}</strong>
        </div>
        <div>
          <span>最后心跳</span>
          <strong>{{ formatHeartbeat(currentDevice.last_heartbeat) }}</strong>
        </div>
      </div>
      <template #footer>
        <ElButton @click="showDetailDialog = false">关闭</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<style scoped>
.device-manager {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  margin-top: 16px;
}

.device-manager .header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.device-manager h3 {
  font-size: 16px;
  color: #e0f2fe;
  margin: 0;
}

.status-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.status-online {
  background-color: #52c41a;
}

.status-offline {
  background-color: #f5222d;
}

.status-text {
  font-size: 13px;
  color: #dbeafe;
}

.empty-tip {
  text-align: center;
  color: #93c5fd;
  padding: 20px;
  font-size: 14px;
}

.device-detail {
  display: grid;
  gap: 10px;
}

.device-detail div {
  align-items: center;
  background: rgba(15, 23, 42, 0.72);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  display: flex;
  justify-content: space-between;
  padding: 10px 12px;
}

.device-detail span {
  color: #93c5fd;
  font-size: 13px;
}

.device-detail strong {
  color: #e0f2fe;
  font-size: 14px;
}
</style>
