<script setup>
import { ref, reactive } from 'vue'
import { ElDialog, ElForm, ElFormItem, ElSelect, ElOption, ElInputNumber, ElInput, ElSlider, ElButton, ElDrawer, ElMessage } from 'element-plus'

const emit = defineEmits(['send-command'])

const showDrawer = ref(false)
const showWhitelistDialog = ref(false)

const config = reactive({
  scene: 'plate_recognition',
  threshold: 30,
  model: 'YOLOv11s',
  confidence: 0.5
})

const whitelistForm = reactive({
  plate: '',
  owner: ''
})

const sceneOptions = [
  { label: '车牌识别', value: 'plate_recognition' },
  { label: '车辆密度', value: 'traffic_density' },
  { label: '违停检测', value: 'illegal_parking' },
  { label: '异常检测', value: 'road_anomaly' }
]

const modelOptions = [
  { label: 'YOLOv11s', value: 'YOLOv11s' },
  { label: 'YOLOv11m', value: 'YOLOv11m' },
  { label: 'YOLOv8n', value: 'YOLOv8n' }
]

const sendCommand = (command, data = {}) => {
  const payload = { command, ...data }
  console.log('📤 发送配置指令:', payload)
  emit('send-command', payload)
}

const handleSceneChange = (value) => {
  sendCommand('switch_scene', { scene_id: value })
}

const handleThresholdSave = () => {
  sendCommand('set_threshold', { threshold: config.threshold })
  ElMessage.success('违停阈值已更新')
}

const handleModelChange = (value) => {
  sendCommand('set_model', { model: value })
}

const handleConfidenceChange = (value) => {
  sendCommand('set_confidence', { confidence: value })
}

const handleStartAnalysis = () => {
  sendCommand('start_analysis')
  ElMessage.success('分析已开始')
}

const handleStopAnalysis = () => {
  sendCommand('stop_analysis')
  ElMessage.success('分析已停止')
}

const handleWhitelistUpdate = () => {
  if (!whitelistForm.plate || !whitelistForm.owner) {
    ElMessage.warning('请填写车牌号和所属人')
    return
  }
  
  sendCommand('update_whitelist', {
    data: {
      plate: whitelistForm.plate,
      owner: whitelistForm.owner
    }
  })
  
  whitelistForm.plate = ''
  whitelistForm.owner = ''
  showWhitelistDialog.value = false
  ElMessage.success('白名单已更新')
}
</script>

<template>
  <div class="config-panel-trigger">
    <button class="config-btn" @click="showDrawer = true">
      <span class="gear-icon">⚙️</span>
    </button>
  </div>
  
  <ElDrawer 
    title="系统配置" 
    v-model="showDrawer" 
    direction="rtl" 
    size="480px"
  >
    <ElForm :model="config" label-width="120px" class="config-form">
      <ElFormItem label="场景切换">
        <ElSelect v-model="config.scene" @change="handleSceneChange" style="width: 100%">
          <ElOption v-for="option in sceneOptions" :key="option.value" :label="option.label" :value="option.value" />
        </ElSelect>
      </ElFormItem>
      
      <ElFormItem label="违停阈值(秒)">
        <div class="threshold-control">
          <ElInputNumber v-model="config.threshold" :min="1" :max="300" style="width: 120px" />
          <ElButton type="primary" size="small" @click="handleThresholdSave">保存</ElButton>
        </div>
      </ElFormItem>
      
      <ElFormItem label="模型选择">
        <ElSelect v-model="config.model" @change="handleModelChange" style="width: 100%">
          <ElOption v-for="option in modelOptions" :key="option.value" :label="option.label" :value="option.value" />
        </ElSelect>
      </ElFormItem>
      
      <ElFormItem label="置信度阈值">
        <div class="slider-control">
          <ElSlider v-model="config.confidence" :min="0.1" :max="0.9" :step="0.05" @change="handleConfidenceChange" />
          <span class="slider-value">{{ config.confidence.toFixed(2) }}</span>
        </div>
      </ElFormItem>
      
      <ElFormItem>
        <div class="action-buttons">
          <ElButton type="primary" @click="handleStartAnalysis">开始分析</ElButton>
          <ElButton @click="handleStopAnalysis">停止分析</ElButton>
        </div>
      </ElFormItem>
      
      <ElFormItem>
        <ElButton type="success" @click="showWhitelistDialog = true">更新白名单</ElButton>
      </ElFormItem>
    </ElForm>
  </ElDrawer>
  
  <ElDialog title="更新白名单" v-model="showWhitelistDialog" width="400px">
    <ElForm :model="whitelistForm" label-width="80px">
      <ElFormItem label="车牌号">
        <ElInput v-model="whitelistForm.plate" placeholder="请输入车牌号" />
      </ElFormItem>
      <ElFormItem label="所属人">
        <ElInput v-model="whitelistForm.owner" placeholder="请输入所属人" />
      </ElFormItem>
    </ElForm>
    <template #footer>
      <ElButton @click="showWhitelistDialog = false">取消</ElButton>
      <ElButton type="primary" @click="handleWhitelistUpdate">确定</ElButton>
    </template>
  </ElDialog>
</template>

<style scoped>
.config-panel-trigger {
  position: relative;
  margin-left: 16px;
}

.config-btn {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  border: none;
  background: #1e3c72;
  color: white;
  font-size: 24px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}

.config-btn:hover {
  transform: rotate(90deg);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.3);
}

.gear-icon {
  line-height: 1;
}

.config-form {
  padding-top: 20px;
}

.threshold-control {
  display: flex;
  align-items: center;
  gap: 12px;
}

.slider-control {
  display: flex;
  align-items: center;
  gap: 16px;
}

.slider-value {
  width: 50px;
  text-align: right;
  font-size: 14px;
  color: #606266;
}

.action-buttons {
  display: flex;
  gap: 12px;
}
</style>