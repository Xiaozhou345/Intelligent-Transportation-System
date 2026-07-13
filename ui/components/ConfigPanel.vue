<script setup>
import { ref, reactive, watch } from 'vue'
import { ElInputNumber, ElButton, ElDialog, ElMessage, ElTabs, ElTabPane } from 'element-plus'

const props = defineProps({
  serverUrl: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['send-command'])

const showDialog = ref(false)
const currentTab = ref('detection')
const loadingConfig = ref(false)

const defaultConfig = {
  detection: {
    vehicleConf: 0.5,
    plateConf: 0.2
  },
  tracking: {
    parkingThreshold: 30
  },
  business: {
    smoothMax: 1,
    slowMax: 3,
    congestionMax: 4
  }
}

const config = reactive(JSON.parse(JSON.stringify(defaultConfig)))

const resolveNumber = (value, fallback) => {
  return value !== undefined && value !== null ? Number(value) : fallback
}

const resolveDetectionConfig = (systemConfig) => {
  const runtime = systemConfig?.runtime || {}
  return {
    vehicleConf: resolveNumber(runtime.vehicleConf, defaultConfig.detection.vehicleConf),
    plateConf: resolveNumber(runtime.plateConf, defaultConfig.detection.plateConf)
  }
}

const resolveTrafficThresholds = (systemConfig) => {
  const runtimeThresholds = systemConfig?.runtime?.trafficThresholds || {}
  const storedThresholds = systemConfig?.traffic_thresholds || {}
  return {
    smoothMax: resolveNumber(runtimeThresholds.smoothMax ?? storedThresholds.smooth_max, defaultConfig.business.smoothMax),
    slowMax: resolveNumber(runtimeThresholds.slowMax ?? storedThresholds.slow_max, defaultConfig.business.slowMax),
    congestionMax: resolveNumber(runtimeThresholds.congestionMax ?? storedThresholds.congestion_max, defaultConfig.business.congestionMax)
  }
}

const resolveParkingThreshold = (systemConfig) => {
  const runtimeThreshold = systemConfig?.runtime?.parkingThreshold
  if (runtimeThreshold !== undefined && runtimeThreshold !== null) {
    return Number(runtimeThreshold)
  }

  const zones = systemConfig?.no_parking_zone_default || systemConfig?.no_parking_zones || []
  const threshold = zones[0]?.threshold_seconds
  return threshold !== undefined && threshold !== null ? Number(threshold) : defaultConfig.tracking.parkingThreshold
}

const loadBackendConfig = async () => {
  loadingConfig.value = true
  try {
    const response = await fetch(`${props.serverUrl}/api/config?t=${Date.now()}`, { cache: 'no-store' })
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`)
    }

    const result = await response.json()
    if (result.status !== 'success') {
      throw new Error(result.message || '配置读取失败')
    }

    const detectionConfig = resolveDetectionConfig(result.data)
    config.detection.vehicleConf = detectionConfig.vehicleConf
    config.detection.plateConf = detectionConfig.plateConf
    Object.assign(defaultConfig.detection, detectionConfig)

    const trafficThresholds = resolveTrafficThresholds(result.data)
    Object.assign(config.business, trafficThresholds)
    Object.assign(defaultConfig.business, trafficThresholds)

    const parkingThreshold = resolveParkingThreshold(result.data)
    config.tracking.parkingThreshold = parkingThreshold
    defaultConfig.tracking.parkingThreshold = parkingThreshold
    console.log('✅ 已同步后端配置:', { ...detectionConfig, ...trafficThresholds, parkingThreshold })
  } catch (error) {
    console.warn('⚠️ 读取后端配置失败，使用本地默认值:', error.message)
    ElMessage.warning('读取后端配置失败，已使用本地默认值')
  } finally {
    loadingConfig.value = false
  }
}

watch(showDialog, (visible) => {
  if (visible) {
    loadBackendConfig()
  }
})

const sendCommand = (command, data = {}) => {
  const payload = { command, ...data }
  console.log('📤 发送配置指令:', payload)
  emit('send-command', payload)
}

const handleSaveConfig = (tabKey) => {
  if (tabKey === 'business') {
    config.business.smoothMax = Number(config.business.smoothMax)
    config.business.slowMax = Math.max(Number(config.business.slowMax), config.business.smoothMax + 1)
    config.business.congestionMax = Math.max(Number(config.business.congestionMax), config.business.slowMax + 1)
  }

  const configData = config[tabKey]
  sendCommand('update_config', { config_type: tabKey, data: configData })
  Object.assign(defaultConfig[tabKey], configData)
  ElMessage.success('配置已更新')
}

const handleResetConfig = (tabKey) => {
  Object.assign(config[tabKey], defaultConfig[tabKey])
  ElMessage.info('已重置为默认配置')
}
</script>

<template>
  <div class="config-panel-trigger">
    <button class="config-btn" @click="showDialog = true">
      <span class="gear-icon">⚙️</span>
    </button>
  </div>

  <ElDialog
    :model-value="showDialog"
    title="系统配置"
    width="620px"
    append-to-body
    class="config-dialog"
    :z-index="4000"
    @close="showDialog = false"
  >
    <div class="config-wrapper">
      <ElTabs v-model="currentTab" class="config-tabs">
        <ElTabPane label="AI推理参数" name="detection">
          <div class="tab-content">
            <div class="section-title">
              <span>YOLOv11车辆检测器</span>
            </div>
            <div class="config-form">
              <div class="form-item">
                <span class="form-label">车辆检测置信度</span>
                <div class="form-content">
                  <input type="range" v-model.number="config.detection.vehicleConf" min="0.1" max="0.9" step="0.05" class="config-slider" :disabled="loadingConfig" />
                  <span class="slider-value">{{ config.detection.vehicleConf.toFixed(2) }}</span>
                </div>
              </div>
            </div>

            <div class="section-title">
              <span>车牌检测参数</span>
            </div>
            <div class="config-form">
              <div class="form-item">
                <span class="form-label">车牌检测置信度</span>
                <div class="form-content">
                  <input type="range" v-model.number="config.detection.plateConf" min="0.05" max="0.5" step="0.05" class="config-slider" :disabled="loadingConfig" />
                  <span class="slider-value">{{ config.detection.plateConf.toFixed(2) }}</span>
                </div>
              </div>
            </div>

            <div class="config-actions">
              <ElButton type="primary" :loading="loadingConfig" @click="handleSaveConfig('detection')">保存配置</ElButton>
              <ElButton :disabled="loadingConfig" @click="handleResetConfig('detection')">重置默认</ElButton>
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="跟踪算法参数" name="tracking">
          <div class="tab-content">
            <div class="section-title">
              <span>违停监控参数</span>
            </div>
            <div class="config-form">
              <div class="form-item">
                <span class="form-label">违停判定停留时长(秒)</span>
                <div class="form-content">
                  <ElInputNumber v-model="config.tracking.parkingThreshold" :min="1" :max="300" :disabled="loadingConfig" style="width: 150px" />
                </div>
              </div>
            </div>

            <div class="config-actions">
              <ElButton type="primary" :loading="loadingConfig" @click="handleSaveConfig('tracking')">保存配置</ElButton>
              <ElButton :disabled="loadingConfig" @click="handleResetConfig('tracking')">重置默认</ElButton>
            </div>
          </div>
        </ElTabPane>

        <ElTabPane label="业务阈值参数" name="business">
          <div class="tab-content">
            <div class="section-title">
              <span>拥堵热力图参数</span>
            </div>
            <div class="config-form">
              <div class="form-item">
                <span class="form-label">畅通阈值(车辆数)</span>
                <div class="form-content">
                  <ElInputNumber v-model="config.business.smoothMax" :min="1" :max="10" :disabled="loadingConfig" style="width: 150px" />
                </div>
              </div>
              <div class="form-item">
                <span class="form-label">缓行阈值(车辆数)</span>
                <div class="form-content">
                  <ElInputNumber v-model="config.business.slowMax" :min="config.business.smoothMax + 1" :max="15" :disabled="loadingConfig" style="width: 150px" />
                </div>
              </div>
              <div class="form-item">
                <span class="form-label">拥堵阈值(车辆数)</span>
                <div class="form-content">
                  <ElInputNumber v-model="config.business.congestionMax" :min="config.business.slowMax + 1" :max="20" :disabled="loadingConfig" style="width: 150px" />
                </div>
              </div>
            </div>

            <div class="config-actions">
              <ElButton type="primary" :loading="loadingConfig" @click="handleSaveConfig('business')">保存配置</ElButton>
              <ElButton :disabled="loadingConfig" @click="handleResetConfig('business')">重置默认</ElButton>
            </div>
          </div>
        </ElTabPane>
      </ElTabs>
    </div>
  </ElDialog>
</template>

<style scoped>
.config-panel-trigger {
  position: relative;
  flex-shrink: 0;
}

.config-btn {
  width: 42px;
  height: 42px;
  border-radius: 8px;
  border: 1px solid rgba(125, 211, 252, 0.42);
  background: linear-gradient(135deg, rgba(8, 145, 178, 0.92), rgba(37, 99, 235, 0.92));
  color: white;
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 0 20px rgba(34, 211, 238, 0.34);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  flex-shrink: 0;
}

.config-btn:hover {
  transform: rotate(90deg);
  box-shadow: 0 0 28px rgba(34, 211, 238, 0.58);
}

.gear-icon {
  line-height: 1;
}

.config-wrapper {
  padding-top: 4px;
}

.config-tabs {
  margin-bottom: 8px;
}

:deep(.el-tabs__header) {
  display: flex;
  justify-content: space-around;
  width: 100%;
}

:deep(.el-tabs__nav-wrap) {
  width: 100%;
}

:deep(.el-tabs__nav) {
  display: flex;
  width: 100%;
}

:deep(.el-tabs__item) {
  flex: 1;
  text-align: center;
}

.tab-content {
  padding: 10px 0;
}

.section-title {
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid rgba(125, 211, 252, 0.2);
  color: #7dd3fc;
  font-weight: 600;
}

.config-form {
  margin-bottom: 20px;
}

.form-item {
  display: flex;
  align-items: center;
  margin-bottom: 16px;
  padding-left: 50px;
}

.form-label {
  width: 150px;
  min-width: 150px;
  text-align: right;
  padding-right: 16px;
  color: #e0f2fe;
  white-space: nowrap;
}

.form-content {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.config-slider {
  flex: 1;
  max-width: 200px;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: rgba(148, 163, 184, 0.2);
  border-radius: 3px;
  cursor: pointer;
}

.config-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #7dd3fc;
  cursor: pointer;
  box-shadow: 0 0 10px rgba(125, 211, 252, 0.5);
  border: 2px solid #7dd3fc;
  transition: all 0.2s ease;
}

.config-slider::-webkit-slider-thumb:hover {
  background: #67e8f9;
  box-shadow: 0 0 15px rgba(103, 232, 249, 0.7);
}

.config-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #7dd3fc;
  cursor: pointer;
  box-shadow: 0 0 10px rgba(125, 211, 252, 0.5);
  border: 2px solid #7dd3fc;
}

.slider-value {
  min-width: 50px;
  text-align: right;
  color: #7dd3fc;
  font-weight: 600;
}

.input-hint {
  color: #94a3b8;
  font-size: 12px;
}

.config-actions {
  display: flex;
  gap: 80px;
  justify-content: center;
  padding-top: 12px;
  border-top: 1px solid rgba(125, 211, 252, 0.2);
}

:global(.config-dialog.el-dialog) {
  background: #0f172a;
  border: 1px solid rgba(56, 189, 248, 0.28);
  border-radius: 8px;
  box-shadow: 0 26px 70px rgba(2, 8, 23, 0.72);
  max-height: 85vh;
  overflow-y: auto;
}

:global(.config-dialog .el-dialog__title) {
  color: #e0f2fe;
}

:global(.config-dialog .el-dialog__body) {
  padding: 16px 24px;
}

:global(.config-dialog .el-tabs__item) {
  color: #94a3b8;
}

:global(.config-dialog .el-tabs__item.is-active) {
  color: #7dd3fc;
}

:global(.config-dialog .el-tabs__content) {
  color: #e0f2fe;
}

:global(.config-dialog .el-input__inner) {
  background: #ffffff;
  border-color: rgba(148, 163, 184, 0.2);
  color: #000000;
}

:global(.config-dialog .el-switch__background) {
  background: rgba(148, 163, 184, 0.3);
}

:global(.config-dialog .el-switch.is-checked .el-switch__background) {
  background: linear-gradient(90deg, #22d3ee, #60a5fa);
}
</style>
