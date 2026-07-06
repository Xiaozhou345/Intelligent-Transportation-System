<script setup>
import { ref, onMounted, onUnmounted, watch, reactive } from 'vue'
import * as echarts from 'echarts'
import { ElTag } from 'element-plus'

const props = defineProps({
  systemData: {
    type: Object,
    default: () => ({})
  }
})

const cpuChartRef = ref(null)
const gpuChartRef = ref(null)
const memoryChartRef = ref(null)

let cpuChartInstance = null
let gpuChartInstance = null
let memoryChartInstance = null

let mockTimer = null
let disconnectTimer = null

const localData = reactive({
  cpu_usage: 50,
  gpu_usage: 40,
  memory_usage: 60,
  stream_status: 'streaming',
  bitrate: 2048
})

const getStatusText = (status) => {
  return status === 'streaming' ? '拉流中' : '已断开'
}

const getStatusType = (status) => {
  return status === 'streaming' ? 'success' : 'danger'
}

const createGaugeOption = (value, title) => {
  return {
    series: [{
      type: 'gauge',
      radius: '90%',
      startAngle: 200,
      endAngle: -20,
      min: 0,
      max: 100,
      splitNumber: 5,
      axisLine: {
        lineStyle: {
          width: 12,
          color: [
            [0.5, '#52c41a'],
            [0.8, '#faad14'],
            [1, '#f5222d']
          ]
        }
      },
      pointer: {
        length: '60%',
        width: 4,
        itemStyle: {
          color: '#1e3c72'
        }
      },
      axisTick: {
        distance: -12,
        length: 4,
        lineStyle: {
          color: '#666',
          width: 1
        }
      },
      splitLine: {
        distance: -18,
        length: 12,
        lineStyle: {
          color: '#666',
          width: 2
        }
      },
      axisLabel: {
        color: '#666',
        distance: 20,
        fontSize: 10
      },
      detail: {
        valueAnimation: true,
        formatter: '{value}%',
        color: '#303133',
        fontSize: 16,
        fontWeight: 'bold',
        offsetCenter: [0, '70%']
      },
      title: {
        offsetCenter: [0, '90%'],
        fontSize: 13,
        color: '#606266'
      },
      data: [{
        value: value,
        name: title
      }]
    }]
  }
}

const initCharts = () => {
  if (cpuChartRef.value) {
    cpuChartInstance = echarts.init(cpuChartRef.value)
    cpuChartInstance.setOption(createGaugeOption(localData.cpu_usage, 'CPU'))
  }
  if (gpuChartRef.value) {
    gpuChartInstance = echarts.init(gpuChartRef.value)
    gpuChartInstance.setOption(createGaugeOption(localData.gpu_usage, 'GPU'))
  }
  if (memoryChartRef.value) {
    memoryChartInstance = echarts.init(memoryChartRef.value)
    memoryChartInstance.setOption(createGaugeOption(localData.memory_usage, '内存'))
  }
  
  window.addEventListener('resize', handleResize)
}

const handleResize = () => {
  cpuChartInstance?.resize()
  gpuChartInstance?.resize()
  memoryChartInstance?.resize()
}

const updateCharts = () => {
  cpuChartInstance?.setOption(createGaugeOption(localData.cpu_usage, 'CPU'))
  gpuChartInstance?.setOption(createGaugeOption(localData.gpu_usage, 'GPU'))
  memoryChartInstance?.setOption(createGaugeOption(localData.memory_usage, '内存'))
}

const startMockData = () => {
  stopMockData()
  mockTimer = setInterval(() => {
    localData.cpu_usage = Math.round(30 + Math.random() * 50)
    localData.gpu_usage = Math.round(20 + Math.random() * 70)
    localData.memory_usage = Math.round(40 + Math.random() * 30)
    localData.bitrate = Math.round(1024 + Math.random() * 3072)
    updateCharts()
  }, 2000)
}

const stopMockData = () => {
  if (mockTimer) {
    clearInterval(mockTimer)
    mockTimer = null
  }
}

const resetDisconnectTimer = () => {
  if (disconnectTimer) {
    clearTimeout(disconnectTimer)
  }
  disconnectTimer = setTimeout(() => {
    localData.stream_status = 'disconnected'
  }, 5000)
}

watch(() => props.systemData, (newData) => {
  if (newData) {
    if (newData.cpu_usage !== undefined) {
      localData.cpu_usage = newData.cpu_usage
    }
    if (newData.gpu_usage !== undefined) {
      localData.gpu_usage = newData.gpu_usage
    }
    if (newData.memory_usage !== undefined) {
      localData.memory_usage = newData.memory_usage
    }
    if (newData.stream_status !== undefined) {
      localData.stream_status = newData.stream_status
    }
    if (newData.bitrate !== undefined) {
      localData.bitrate = newData.bitrate
    }
    updateCharts()
    resetDisconnectTimer()
    stopMockData()
  }
}, { deep: true })

onMounted(() => {
  initCharts()
  startMockData()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  cpuChartInstance?.dispose()
  gpuChartInstance?.dispose()
  memoryChartInstance?.dispose()
  stopMockData()
  if (disconnectTimer) {
    clearTimeout(disconnectTimer)
  }
})
</script>

<template>
  <div class="system-monitor">
    <h3>系统资源监控</h3>
    
    <div class="gauges-container">
      <div class="gauge-item">
        <div ref="cpuChartRef" class="gauge-chart"></div>
      </div>
      <div class="gauge-item">
        <div ref="gpuChartRef" class="gauge-chart"></div>
      </div>
      <div class="gauge-item">
        <div ref="memoryChartRef" class="gauge-chart"></div>
      </div>
    </div>
    
    <div class="stream-info">
      <div class="stream-status">
        <span class="label">视频流状态：</span>
        <ElTag :type="getStatusType(localData.stream_status)" size="small">
          {{ getStatusText(localData.stream_status) }}
        </ElTag>
      </div>
      <div class="bitrate">
        <span class="label">传输速率：</span>
        <span class="value">{{ localData.bitrate }} kbps</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.system-monitor {
  background: white;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.system-monitor h3 {
  font-size: 16px;
  color: #303133;
  margin-bottom: 16px;
}

.gauges-container {
  display: flex;
  justify-content: space-around;
  align-items: center;
}

.gauge-item {
  flex: 1;
  display: flex;
  justify-content: center;
}

.gauge-chart {
  width: 120px;
  height: 120px;
}

.stream-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #ebeef5;
}

.stream-info .label {
  font-size: 14px;
  color: #606266;
}

.stream-info .value {
  font-size: 14px;
  color: #303133;
  font-weight: 500;
}
</style>