<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  }
})

const chartRef = ref(null)
let chartInstance = null

const getStatusColor = (vehicleCount) => {
  if (vehicleCount <= 2) return '#52c41a'
  if (vehicleCount <= 5) return '#faad14'
  return '#f5222d'
}

const getStatusText = (vehicleCount) => {
  if (vehicleCount <= 2) return '通畅'
  if (vehicleCount <= 5) return '缓行'
  return '拥堵'
}

const initChart = () => {
  if (!chartRef.value) return
  
  chartInstance = echarts.init(chartRef.value)
  updateChart()
  
  window.addEventListener('resize', handleResize)
}

const handleResize = () => {
  chartInstance?.resize()
}

const updateChart = () => {
  if (!chartInstance) return
  
  const regionNames = {
    road_A: 'A路段',
    road_B: 'B路段',
    road_C: 'C路段',
    road_D: 'D路段'
  }
  
  const roadLayouts = {
    road_A: {
      x: 200, y: 80, width: 200, height: 40,
      direction: 'horizontal',
      points: [[100, 100], [300, 100]]
    },
    road_B: {
      x: 380, y: 80, width: 200, height: 40,
      direction: 'horizontal',
      points: [[300, 100], [500, 100]]
    },
    road_C: {
      x: 260, y: 160, width: 40, height: 180,
      direction: 'vertical',
      points: [[280, 100], [280, 280]]
    },
    road_D: {
      x: 340, y: 160, width: 40, height: 180,
      direction: 'vertical',
      points: [[360, 100], [360, 280]]
    }
  }
  
  const customData = []
  const tooltipData = {}
  const connectionLines = []
  
  Object.keys(roadLayouts).forEach((region) => {
    const regionData = props.data.find(r => r.region_id === region)
    const vehicleCount = regionData?.vehicle_count || 0
    const color = getStatusColor(vehicleCount)
    const status = getStatusText(vehicleCount)
    const layout = roadLayouts[region]
    
    customData.push({
      value: [layout.x, layout.y, layout.width, layout.height],
      itemStyle: {
        color: color,
        borderRadius: 6
      },
      regionId: region,
      vehicleCount,
      status,
      name: regionNames[region]
    })
    
    tooltipData[region] = {
      name: regionNames[region],
      count: vehicleCount,
      status
    }
    
    connectionLines.push({
      coords: layout.points,
      lineStyle: {
        color: color,
        width: 4,
        opacity: 0.6
      }
    })
  })
  
  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        if (params.data.regionId) {
          const data = tooltipData[params.data.regionId]
          return `<div style="padding: 8px;">
            <div style="font-weight: bold; margin-bottom: 4px;">${data.name}</div>
            <div>车辆数: <strong>${data.count}</strong></div>
            <div>状态: <strong>${data.status}</strong></div>
          </div>`
        }
        return ''
      }
    },
    grid: {
      left: '5%',
      right: '5%',
      top: '10%',
      bottom: '15%'
    },
    xAxis: {
      show: false,
      min: 50,
      max: 550
    },
    yAxis: {
      show: false,
      min: 50,
      max: 350
    },
    series: [
      {
        name: '道路连接线',
        type: 'lines',
        coordinateSystem: 'cartesian2d',
        data: connectionLines,
        zlevel: 1
      },
      {
        name: '道路区域',
        type: 'custom',
        coordinateSystem: 'cartesian2d',
        data: customData,
        zlevel: 2,
        renderItem: (params) => {
          const data = params.data || {}
          const value = data.value || [0, 0, 100, 40]
          const [x, y, width, height] = value
          
          return {
            type: 'rect',
            shape: {
              x: x,
              y: y,
              width: width,
              height: height
            },
            style: {
              fill: data.itemStyle?.color || '#52c41a',
              borderRadius: data.itemStyle?.borderRadius || 6,
              stroke: '#fff',
              lineWidth: 2
            }
          }
        },
        label: {
          show: true,
          position: 'inside',
          formatter: (params) => {
            return `${params.data.name}\n${params.data.vehicleCount}辆`
          },
          fontSize: 13,
          fontWeight: 'bold',
          color: '#fff',
          lineHeight: 18,
          align: 'center',
          verticalAlign: 'middle'
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 15,
            shadowColor: 'rgba(0, 0, 0, 0.4)'
          }
        }
      },
      {
        name: '交叉点',
        type: 'scatter',
        coordinateSystem: 'cartesian2d',
        data: [
          { value: [280, 100], itemStyle: { color: '#22d3ee', size: 12 } },
          { value: [360, 100], itemStyle: { color: '#22d3ee', size: 12 } }
        ],
        symbolSize: 12,
        zlevel: 3,
        label: {
          show: false
        }
      }
    ]
  }
  
  chartInstance.setOption(option, true)
}

watch(() => props.data, () => {
  nextTick(() => {
    updateChart()
  })
}, { deep: true })

onMounted(() => {
  initChart()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
})
</script>

<template>
  <div class="traffic-heatmap-container">
    <h2>道路拥堵热力图</h2>
    <div class="chart-wrapper">
      <div ref="chartRef" class="chart"></div>
    </div>
    <div class="legend">
      <div class="legend-item">
        <span class="legend-color" style="background-color: #52c41a;"></span>
        <span class="legend-text">通畅 (≤2辆)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #faad14;"></span>
        <span class="legend-text">缓行 (3-5辆)</span>
      </div>
      <div class="legend-item">
        <span class="legend-color" style="background-color: #f5222d;"></span>
        <span class="legend-text">拥堵 (>5辆)</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.traffic-heatmap-container {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 24px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.traffic-heatmap-container h2 {
  font-size: 18px;
  color: #e0f2fe;
  margin-bottom: 16px;
}

.chart-wrapper {
  width: 100%;
  height: 320px;
}

.chart {
  width: 100%;
  height: 100%;
}

.legend {
  display: flex;
  justify-content: center;
  gap: 24px;
  margin-top: 16px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.legend-color {
  width: 20px;
  height: 20px;
  border-radius: 4px;
}

.legend-text {
  font-size: 14px;
  color: #dbeafe;
}
</style>
