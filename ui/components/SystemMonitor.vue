<script setup>
import { computed, ref, onMounted, onUnmounted, watch, reactive } from 'vue'
import * as echarts from 'echarts'
import { ElTag } from 'element-plus'

const props = defineProps({
  systemData: {
    type: Object,
    default: () => ({})
  },
  connectionStatus: {
    type: String,
    default: '未连接'
  },
  activeDevices: {
    type: Number,
    default: 0
  },
  activeStreams: {
    type: Number,
    default: 0
  },
  eventCount: {
    type: Number,
    default: 0
  },
  alarmCount: {
    type: Number,
    default: 0
  }
})

const cpuChartRef = ref(null)
const gpuChartRef = ref(null)
const memoryChartRef = ref(null)

let cpuChartInstance = null
let gpuChartInstance = null
let memoryChartInstance = null

let disconnectTimer = null

const localData = reactive({
  cpu_usage: 0,
  gpu_usage: 0,
  memory_usage: 0,
  stream_status: 'disconnected',
  bitrate: null
})

const hasSystemData = computed(() => {
  return Object.keys(props.systemData || {}).length > 0
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
          width: 10,
          color: [
            [0.5, '#52c41a'],
            [0.8, '#faad14'],
            [1, '#f5222d']
          ]
        }
      },
      pointer: {
        length: '55%',
        width: 3,
        itemStyle: {
          color: '#22d3ee'
        }
      },
      axisTick: {
        distance: -10,
        length: 3,
        lineStyle: {
          color: '#7dd3fc',
          width: 1
        }
      },
      splitLine: {
        distance: -15,
        length: 10,
        lineStyle: {
          color: '#7dd3fc',
          width: 1.5
        }
      },
      axisLabel: {
        color: '#93c5fd',
        distance: 16,
        fontSize: 9
      },
      detail: {
        valueAnimation: true,
        formatter: '{value}%',
        color: '#e0f2fe',
        fontSize: 15,
        fontWeight: 'bold',
        offsetCenter: [0, '55%']
      },
      title: {
        offsetCenter: [0, '80%'],
        fontSize: 12,
        color: '#93c5fd'
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

const resetDisconnectTimer = () => {
  if (disconnectTimer) {
    clearTimeout(disconnectTimer)
  }
  disconnectTimer = setTimeout(() => {
    localData.stream_status = 'disconnected'
  }, 5000)
}

watch(() => props.systemData, (newData) => {
  if (newData && Object.keys(newData).length > 0) {
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
  }
}, { deep: true })

onMounted(() => {
  initCharts()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  cpuChartInstance?.dispose()
  gpuChartInstance?.dispose()
  memoryChartInstance?.dispose()
  if (disconnectTimer) {
    clearTimeout(disconnectTimer)
  }
})
</script>

<template>
  <div class="system-monitor">
    <h3>系统资源监控</h3>
    <div v-if="!hasSystemData" class="monitor-empty">
      正在获取系统资源数据
    </div>
    
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
        <span class="value">{{ localData.bitrate ?? '-' }} kbps</span>
      </div>
    </div>

    <div class="service-grid">
      <div>
        <span>Socket</span>
        <strong>{{ connectionStatus }}</strong>
      </div>
      <div>
        <span>活跃设备</span>
        <strong>{{ activeDevices }}</strong>
      </div>
      <div>
        <span>分析流</span>
        <strong>{{ activeStreams }}</strong>
      </div>
      <div>
        <span>事件/告警</span>
        <strong>{{ eventCount }}/{{ alarmCount }}</strong>
      </div>
    </div>
  </div>
</template>

<style scoped>
.system-monitor {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  flex-grow: 1;
  min-height: 0;
}

.system-monitor h3 {
  font-size: 16px;
  color: #e0f2fe;
  margin-bottom: 16px;
}

.monitor-empty {
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  color: #93c5fd;
  font-size: 13px;
  margin-bottom: 12px;
  padding: 10px 12px;
  text-align: center;
}

.gauges-container {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
}

.gauge-item {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.gauge-chart {
  width: 100px;
  height: 100px;
}

.stream-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(56, 189, 248, 0.16);
}

.stream-info .label {
  font-size: 14px;
  color: #93c5fd;
}

.stream-info .value {
  font-size: 14px;
  color: #e0f2fe;
  font-weight: 500;
}

.service-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 14px;
}

.service-grid div {
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  min-width: 0;
  padding: 10px;
}

.service-grid span {
  color: #93c5fd;
  display: block;
  font-size: 12px;
}

.service-grid strong {
  color: #e0f2fe;
  display: block;
  font-size: 14px;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
