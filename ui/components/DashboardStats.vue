<script setup>
import { ref, reactive, watch, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  statsData: {
    type: Object,
    default: () => ({})
  }
})

const stats = reactive({
  plateCount: 0,
  congestionIndex: 0,
  illegalParkingCount: 0,
  roadAnomalyCount: 0
})

const trendChartRef = ref(null)
const distributionChartRef = ref(null)

let trendChartInstance = null
let distributionChartInstance = null
let trendTimer = null

const generateTimeLabels = () => {
  const labels = []
  const now = new Date()
  for (let i = 11; i >= 0; i--) {
    const time = new Date(now.getTime() - i * 5 * 60 * 1000)
    const hours = time.getHours().toString().padStart(2, '0')
    const minutes = time.getMinutes().toString().padStart(2, '0')
    labels.push(`${hours}:${minutes}`)
  }
  return labels
}

const trendData = ref({
  timeLabels: generateTimeLabels(),
  values: Array(12).fill(0)
})

const distributionData = ref({
  categories: ['违规停车', '道路异常'],
  values: [0, 0]
})

const initTrendChart = () => {
  if (trendChartRef.value) {
    trendChartInstance = echarts.init(trendChartRef.value)
    updateTrendChart()
  }
}

const initDistributionChart = () => {
  if (distributionChartRef.value) {
    distributionChartInstance = echarts.init(distributionChartRef.value)
    updateDistributionChart()
  }
}

const updateTrendChart = () => {
  const option = {
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const data = params[0]
        return `<div style="padding: 8px;">
          <div>时间: ${data.name}</div>
          <div>拥堵指数: <strong>${data.value}</strong></div>
        </div>`
      }
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '10%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: trendData.value.timeLabels,
      axisLine: {
        lineStyle: {
          color: 'rgba(125, 211, 252, 0.35)'
        }
      },
      axisTick: {
        lineStyle: {
          color: 'rgba(125, 211, 252, 0.28)'
        }
      },
      axisLabel: {
        color: '#93c5fd',
        fontSize: 11,
        rotate: 30
      }
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitLine: {
        lineStyle: {
          color: 'rgba(56, 189, 248, 0.12)'
        }
      },
      axisLine: {
        lineStyle: {
          color: 'rgba(125, 211, 252, 0.35)'
        }
      },
      axisLabel: {
        color: '#93c5fd',
        formatter: '{value}'
      }
    },
    series: [{
      name: '拥堵指数',
      type: 'line',
      smooth: true,
      data: trendData.value.values,
      lineStyle: {
        width: 3,
        color: '#22d3ee'
      },
      itemStyle: {
        color: '#67e8f9'
      },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(34, 211, 238, 0.35)' },
          { offset: 1, color: 'rgba(34, 211, 238, 0.03)' }
        ])
      }
    }]
  }
  trendChartInstance?.setOption(option)
}

const updateDistributionChart = () => {
  const option = {
    tooltip: {
      trigger: 'axis',
      axisPointer: {
        type: 'shadow'
      },
      formatter: (params) => {
        const item = params[0]
        return `<div style="padding: 8px;"><strong>${item.name}</strong><br/>次数: <strong>${item.value}</strong></div>`
      }
    },
    legend: {
      show: false
    },
    grid: {
      left: '3%',
      right: '4%',
      bottom: '3%',
      top: '15%',
      containLabel: true
    },
    xAxis: {
      type: 'category',
      data: distributionData.value.categories,
      axisLine: {
        lineStyle: {
          color: 'rgba(125, 211, 252, 0.35)'
        }
      },
      axisLabel: {
        color: '#93c5fd',
        fontSize: 12
      }
    },
    yAxis: {
      type: 'value',
      splitLine: {
        lineStyle: {
          color: 'rgba(56, 189, 248, 0.12)'
        }
      },
      axisLabel: {
        color: '#93c5fd',
        formatter: '{value}次'
      }
    },
    series: [
      {
        name: '事件数量',
        type: 'bar',
        data: distributionData.value.values,
        itemStyle: {
          color: (params) => params.dataIndex === 0 ? '#f59e0b' : '#ef4444',
          borderRadius: [4, 4, 0, 0]
        }
      }
    ]
  }
  distributionChartInstance?.setOption(option)
}

const addTrendDataPoint = () => {
  const now = new Date()
  const hours = now.getHours().toString().padStart(2, '0')
  const minutes = now.getMinutes().toString().padStart(2, '0')
  
  trendData.value.timeLabels.push(`${hours}:${minutes}`)
  trendData.value.timeLabels.shift()
  
  const newIndex = stats.congestionIndex || 0
  trendData.value.values.push(newIndex)
  trendData.value.values.shift()
  
  updateTrendChart()
}

const handleResize = () => {
  trendChartInstance?.resize()
  distributionChartInstance?.resize()
}

watch(() => props.statsData, (newData) => {
  if (newData) {
    if (newData.plateCount !== undefined) {
      stats.plateCount = newData.plateCount
    }
    if (newData.congestionIndex !== undefined) {
      stats.congestionIndex = newData.congestionIndex
    }
    if (newData.illegalParkingCount !== undefined) {
      stats.illegalParkingCount = newData.illegalParkingCount
    }
    if (newData.roadAnomalyCount !== undefined) {
      stats.roadAnomalyCount = newData.roadAnomalyCount
    }
    trendData.value.values[trendData.value.values.length - 1] = stats.congestionIndex || 0
    distributionData.value.values = [
      stats.illegalParkingCount,
      stats.roadAnomalyCount
    ]
    updateTrendChart()
    updateDistributionChart()
  }
}, { deep: true, immediate: true })

onMounted(() => {
  initTrendChart()
  initDistributionChart()
  window.addEventListener('resize', handleResize)
  
  trendTimer = setInterval(addTrendDataPoint, 5 * 60 * 1000)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  trendChartInstance?.dispose()
  distributionChartInstance?.dispose()
  if (trendTimer) {
    clearInterval(trendTimer)
  }
})
</script>

<template>
  <div class="dashboard-stats">
    <h3>数据统计</h3>
    
    <div class="stats-cards">
      <div class="stat-card">
        <div class="stat-icon plate-icon">🚗</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.plateCount }}</div>
          <div class="stat-label">今日检测车牌数</div>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon congestion-icon">📊</div>
        <div class="stat-info">
          <div class="stat-value" :class="getCongestionClass(stats.congestionIndex)">{{ stats.congestionIndex }}</div>
          <div class="stat-label">当前拥堵指数</div>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon parking-icon">⚠️</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.illegalParkingCount }}</div>
          <div class="stat-label">违规停车总数</div>
        </div>
      </div>
      
      <div class="stat-card">
        <div class="stat-icon anomaly-icon">🔴</div>
        <div class="stat-info">
          <div class="stat-value">{{ stats.roadAnomalyCount }}</div>
          <div class="stat-label">道路异常总数</div>
        </div>
      </div>
    </div>
    
    <div class="charts-container">
      <div class="chart-item">
        <h4>拥堵度变化趋势</h4>
        <div ref="trendChartRef" class="chart"></div>
      </div>
      
      <div class="chart-item">
        <h4>违规与异常分布</h4>
        <div ref="distributionChartRef" class="chart"></div>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  methods: {
    getCongestionClass(index) {
      if (index <= 30) return 'congestion-low'
      if (index <= 70) return 'congestion-medium'
      return 'congestion-high'
    }
  }
}
</script>

<style scoped>
.dashboard-stats {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  margin-top: 16px;
}

.dashboard-stats h3 {
  font-size: 16px;
  color: #e0f2fe;
  margin-bottom: 16px;
}

.dashboard-stats h4 {
  font-size: 14px;
  color: #93c5fd;
  margin-bottom: 12px;
  font-weight: 500;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: linear-gradient(135deg, rgba(14, 165, 233, 0.14), rgba(15, 23, 42, 0.66));
  border: 1px solid rgba(56, 189, 248, 0.16);
  border-radius: 8px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  background: rgba(8, 18, 33, 0.72);
  box-shadow: inset 0 0 18px rgba(34, 211, 238, 0.12), 0 0 16px rgba(14, 165, 233, 0.18);
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-size: 24px;
  font-weight: 600;
  color: #f8fafc;
}

.stat-label {
  font-size: 12px;
  color: #93c5fd;
  margin-top: 4px;
}

.congestion-low {
  color: #52c41a;
}

.congestion-medium {
  color: #faad14;
}

.congestion-high {
  color: #f5222d;
}

.charts-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.chart-item {
  background: rgba(15, 23, 42, 0.5);
  border: 1px solid rgba(56, 189, 248, 0.12);
  border-radius: 8px;
  padding: 16px;
}

.chart {
  width: 100%;
  height: 250px;
}

@media (max-width: 1200px) {
  .stats-cards {
    grid-template-columns: repeat(2, 1fr);
  }
  
  .charts-container {
    grid-template-columns: 1fr;
  }
}
</style>
