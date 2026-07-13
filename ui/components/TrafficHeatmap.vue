<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  data: {
    type: Array,
    default: () => []
  },
  updatedAt: {
    type: String,
    default: ''
  }
})

const chartRef = ref(null)
let chartInstance = null

const fallbackLayouts = {
  road_A: {
    name: 'A路段',
    polygon: [[92, 116], [318, 92], [326, 138], [104, 164]]
  },
  road_B: {
    name: 'B路段',
    polygon: [[322, 92], [550, 116], [536, 164], [316, 138]]
  },
  road_C: {
    name: 'C路段',
    polygon: [[250, 150], [304, 146], [286, 332], [230, 324]]
  },
  road_D: {
    name: 'D路段',
    polygon: [[350, 146], [404, 150], [424, 324], [368, 332]]
  }
}

const statusMeta = {
  smooth: { text: '通畅', color: '#22c55e', className: 'smooth' },
  slow: { text: '缓行', color: '#f59e0b', className: 'slow' },
  congested: { text: '拥堵', color: '#ef4444', className: 'congested' }
}

const colorMap = {
  green: '#22c55e',
  yellow: '#f59e0b',
  orange: '#f97316',
  red: '#ef4444',
  purple: '#a855f7'
}

const getStatusByCount = (vehicleCount) => {
  if (vehicleCount <= 1) return 'smooth'
  if (vehicleCount <= 3) return 'slow'
  return 'congested'
}

const getRegionStatus = (region) => {
  if (region?.status && statusMeta[region.status]) return region.status
  return getStatusByCount(Number(region?.vehicle_count || 0))
}

const getRegionColor = (region) => {
  if (region?.color && colorMap[region.color]) return colorMap[region.color]
  const status = getRegionStatus(region)
  return statusMeta[status].color
}

const isValidPolygon = (polygon) => {
  return Array.isArray(polygon)
    && polygon.length >= 3
    && polygon.every(point => Array.isArray(point) && point.length >= 2 && point.every(Number.isFinite))
}

const getFallbackPolygon = (regionId, index) => {
  if (fallbackLayouts[regionId]) return fallbackLayouts[regionId].polygon
  const col = index % 3
  const row = Math.floor(index / 3)
  const x = 90 + col * 180
  const y = 100 + row * 86
  return [[x, y], [x + 138, y], [x + 148, y + 46], [x + 10, y + 46]]
}

const normalizeRegion = (region, index) => {
  const regionId = region?.region_id || `region_${index + 1}`
  const vehicleCount = Number(region?.vehicle_count || 0)
  const status = getRegionStatus(region)
  const fallback = fallbackLayouts[regionId]
  const polygon = isValidPolygon(region?.polygon)
    ? region.polygon
    : getFallbackPolygon(regionId, index)

  return {
    id: regionId,
    name: region?.name || fallback?.name || regionId,
    vehicleCount,
    status,
    statusText: statusMeta[status].text,
    color: getRegionColor(region),
    polygon,
    source: isValidPolygon(region?.polygon) ? 'backend' : 'fallback'
  }
}

const normalizedRegions = computed(() => {
  return (Array.isArray(props.data) ? props.data : [])
    .map(normalizeRegion)
    .sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'))
})

const chartRegions = computed(() => {
  return normalizedRegions.value
})

const totalVehicles = computed(() => normalizedRegions.value.reduce((sum, region) => sum + region.vehicleCount, 0))
const busiestRegion = computed(() => {
  return normalizedRegions.value.reduce((max, region) => {
    return !max || region.vehicleCount > max.vehicleCount ? region : max
  }, null)
})
const congestedCount = computed(() => normalizedRegions.value.filter(region => region.status === 'congested').length)
const smoothCount = computed(() => normalizedRegions.value.filter(region => region.status === 'smooth').length)
const hasBackendPolygon = computed(() => normalizedRegions.value.some(region => region.source === 'backend'))

const statusSummary = computed(() => {
  if (!normalizedRegions.value.length) return '等待后端拥堵区域数据'
  if (congestedCount.value > 0) return `${congestedCount.value} 个区域拥堵`
  if (normalizedRegions.value.some(region => region.status === 'slow')) return '局部缓行'
  return '整体通畅'
})

const dataSourceText = computed(() => {
  if (!normalizedRegions.value.length) return '等待真实数据'
  if (hasBackendPolygon.value) return '使用后端 polygon'
  return '后端统计 + 兜底轮廓'
})

const formattedUpdatedAt = computed(() => {
  if (!props.updatedAt) return '等待更新'
  const date = new Date(props.updatedAt)
  if (Number.isNaN(date.getTime())) return props.updatedAt
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
})

const getChartBounds = (regions) => {
  const points = regions.flatMap(region => region.polygon)
  const xs = points.map(point => point[0])
  const ys = points.map(point => point[1])
  const minX = Math.min(...xs)
  const maxX = Math.max(...xs)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  const paddingX = Math.max(36, (maxX - minX) * 0.08)
  const paddingY = Math.max(28, (maxY - minY) * 0.12)

  return {
    minX: minX - paddingX,
    maxX: maxX + paddingX,
    minY: minY - paddingY,
    maxY: maxY + paddingY
  }
}

const getCentroid = (polygon) => {
  const total = polygon.reduce((acc, point) => {
    acc.x += point[0]
    acc.y += point[1]
    return acc
  }, { x: 0, y: 0 })
  return [total.x / polygon.length, total.y / polygon.length]
}

const buildOption = () => {
  const regions = chartRegions.value
  if (!regions.length) {
    return {
      backgroundColor: 'transparent',
      tooltip: { show: false },
      grid: {
        left: 16,
        right: 16,
        top: 16,
        bottom: 16,
        containLabel: false
      },
      xAxis: { show: false, min: 0, max: 1 },
      yAxis: { show: false, min: 0, max: 1 },
      series: []
    }
  }

  const bounds = getChartBounds(regions)
  const regionData = regions.map(region => ({
    name: region.name,
    value: getCentroid(region.polygon),
    polygon: region.polygon,
    regionId: region.id,
    vehicleCount: region.vehicleCount,
    status: region.status,
    statusText: region.statusText,
    itemStyle: { color: region.color }
  }))

  return {
    backgroundColor: 'transparent',
    animationDurationUpdate: 420,
    tooltip: {
      trigger: 'item',
      confine: true,
      backgroundColor: 'rgba(8, 18, 33, 0.96)',
      borderColor: 'rgba(56, 189, 248, 0.42)',
      textStyle: { color: '#dbeafe' },
      formatter: (params) => {
        const region = params.data
        if (!region?.regionId) return ''
        return `
          <div class="heatmap-tooltip">
            <div style="font-weight: 700; margin-bottom: 6px;">${region.name}</div>
            <div>区域编号：${region.regionId}</div>
            <div>车辆数量：<strong>${region.vehicleCount}</strong></div>
            <div>拥堵状态：<strong>${region.statusText}</strong></div>
          </div>
        `
      }
    },
    grid: {
      left: 16,
      right: 16,
      top: 16,
      bottom: 16,
      containLabel: false
    },
    xAxis: {
      show: false,
      min: bounds.minX,
      max: bounds.maxX
    },
    yAxis: {
      show: false,
      min: bounds.minY,
      max: bounds.maxY,
      inverse: true
    },
    series: [
      {
        name: '拥堵区域',
        type: 'custom',
        coordinateSystem: 'cartesian2d',
        data: regionData,
        z: 2,
        renderItem: (params, api) => {
          const region = regionData[params.dataIndex]
          const points = region.polygon.map(point => api.coord(point))
          return {
            type: 'polygon',
            shape: { points },
            style: {
              fill: region.itemStyle.color,
              opacity: 0.8,
              stroke: '#e0f2fe',
              lineWidth: 1.5,
              shadowBlur: 18,
              shadowColor: `${region.itemStyle.color}88`
            },
            emphasis: {
              style: {
                opacity: 0.96,
                lineWidth: 2.5,
                shadowBlur: 26
              }
            }
          }
        }
      },
      {
        name: '区域标签',
        type: 'scatter',
        coordinateSystem: 'cartesian2d',
        data: regionData,
        symbolSize: 1,
        z: 4,
        label: {
          show: true,
          position: 'inside',
          formatter: (params) => `${params.data.name}\n${params.data.vehicleCount}辆`,
          color: '#ffffff',
          fontSize: 13,
          fontWeight: 700,
          lineHeight: 18,
          textBorderColor: 'rgba(15, 23, 42, 0.82)',
          textBorderWidth: 3
        },
        tooltip: { show: false }
      }
    ]
  }
}

const updateChart = () => {
  if (!chartInstance) return
  chartInstance.setOption(buildOption(), true)
}

const handleResize = () => {
  chartInstance?.resize()
}

const initChart = () => {
  if (!chartRef.value || chartInstance) return
  chartInstance = echarts.init(chartRef.value)
  updateChart()
  window.addEventListener('resize', handleResize)
}

watch(() => [props.data, props.updatedAt], () => {
  nextTick(updateChart)
}, { deep: true })

onMounted(() => {
  initChart()
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<template>
  <div class="traffic-heatmap-container">
    <div class="heatmap-header">
      <div>
        <p class="eyebrow">Traffic Density</p>
        <h2>道路拥堵热力图</h2>
      </div>
      <div class="heatmap-state">
        <span :class="['state-dot', congestedCount > 0 ? 'congested' : 'smooth']"></span>
        <strong>{{ statusSummary }}</strong>
        <small>更新 {{ formattedUpdatedAt }}</small>
      </div>
    </div>

    <div class="heatmap-main">
      <div class="chart-wrapper">
        <div ref="chartRef" class="chart"></div>
        <div v-if="!normalizedRegions.length" class="empty-mask">
          <strong>等待热力图数据</strong>
          <span>系统正在分析道路拥堵情况</span>
        </div>
      </div>

      <div class="metric-column">
        <div class="metric-card">
          <span>车辆总数</span>
          <strong>{{ totalVehicles }}</strong>
          <small>当前统计区域</small>
        </div>
        <div class="metric-card">
          <span>最高密度</span>
          <strong>{{ busiestRegion ? `${busiestRegion.vehicleCount}辆` : '0辆' }}</strong>
          <small>{{ busiestRegion?.name || '暂无区域' }}</small>
        </div>
        <div class="metric-card">
          <span>区域状态</span>
          <strong>{{ smoothCount }}/{{ normalizedRegions.length }}</strong>
          <small>通畅 / 全部</small>
        </div>
      </div>
    </div>

    <div v-if="normalizedRegions.length" class="region-list">
      <div
        v-for="region in chartRegions"
        :key="region.id"
        class="region-item"
      >
        <span class="region-color" :style="{ backgroundColor: region.color }"></span>
        <div>
          <strong>{{ region.name }}</strong>
          <small>{{ region.statusText }} · {{ region.vehicleCount }}辆</small>
        </div>
      </div>
    </div>

    <div class="legend">
      <div class="legend-item">
        <span class="legend-color smooth"></span>
        <span class="legend-text">通畅</span>
      </div>
      <div class="legend-item">
        <span class="legend-color slow"></span>
        <span class="legend-text">缓行</span>
      </div>
      <div class="legend-item">
        <span class="legend-color congested"></span>
        <span class="legend-text">拥堵</span>
      </div>
      <div class="legend-item source">
        <span class="source-mark"></span>
        <span class="legend-text">{{ dataSourceText }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.traffic-heatmap-container {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: #dbeafe;
  padding: 20px;
}

.heatmap-header {
  align-items: flex-start;
  display: flex;
  gap: 16px;
  justify-content: space-between;
  margin-bottom: 16px;
}

.eyebrow {
  color: #67e8f9;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0;
  margin: 0 0 4px;
  text-transform: uppercase;
}

.traffic-heatmap-container h2 {
  color: #e0f2fe;
  font-size: 18px;
  margin: 0;
}

.heatmap-state {
  align-items: center;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.18);
  border-radius: 8px;
  display: grid;
  gap: 2px 8px;
  grid-template-columns: auto 1fr;
  min-width: 160px;
  padding: 10px 12px;
}

.heatmap-state strong {
  color: #f8fafc;
  font-size: 14px;
}

.heatmap-state small {
  color: #93c5fd;
  font-size: 12px;
  grid-column: 2;
}

.state-dot {
  border-radius: 999px;
  box-shadow: 0 0 14px currentColor;
  height: 9px;
  width: 9px;
}

.state-dot.smooth {
  color: #22c55e;
}

.state-dot.congested {
  color: #ef4444;
}

.heatmap-main {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(0, 1fr) 156px;
}

.chart-wrapper {
  background:
    linear-gradient(rgba(56, 189, 248, 0.07) 1px, transparent 1px),
    linear-gradient(90deg, rgba(56, 189, 248, 0.07) 1px, transparent 1px),
    rgba(2, 8, 23, 0.28);
  background-size: 28px 28px;
  border: 1px solid rgba(56, 189, 248, 0.16);
  border-radius: 8px;
  height: 330px;
  min-width: 0;
  overflow: hidden;
  position: relative;
}

.chart {
  height: 100%;
  width: 100%;
}

.empty-mask {
  align-items: center;
  background: linear-gradient(180deg, rgba(8, 18, 33, 0.06), rgba(8, 18, 33, 0.7));
  bottom: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  justify-content: flex-end;
  left: 0;
  padding: 18px;
  pointer-events: none;
  position: absolute;
  right: 0;
  top: 0;
}

.empty-mask strong {
  color: #e0f2fe;
  font-size: 14px;
}

.empty-mask span {
  color: #93c5fd;
  font-size: 12px;
}

.metric-column {
  display: grid;
  gap: 10px;
}

.metric-card {
  background: rgba(15, 23, 42, 0.58);
  border: 1px solid rgba(56, 189, 248, 0.15);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-height: 92px;
  padding: 12px;
}

.metric-card span,
.metric-card small {
  color: #93c5fd;
  font-size: 12px;
}

.metric-card strong {
  color: #f8fafc;
  font-size: 24px;
  margin: 4px 0;
}

.region-list {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  margin-top: 14px;
}

.region-item {
  align-items: center;
  background: rgba(15, 23, 42, 0.52);
  border: 1px solid rgba(56, 189, 248, 0.13);
  border-radius: 8px;
  display: flex;
  gap: 10px;
  min-width: 0;
  padding: 10px;
}

.region-item strong {
  color: #e0f2fe;
  display: block;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.region-item small {
  color: #93c5fd;
  display: block;
  font-size: 12px;
  margin-top: 2px;
}

.region-color {
  border-radius: 4px;
  box-shadow: 0 0 12px currentColor;
  flex: 0 0 auto;
  height: 28px;
  width: 8px;
}

.legend {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: 12px 18px;
  justify-content: center;
  margin-top: 16px;
}

.legend-item {
  align-items: center;
  display: flex;
  gap: 7px;
}

.legend-color {
  border-radius: 4px;
  height: 12px;
  width: 22px;
}

.legend-color.smooth {
  background: #22c55e;
}

.legend-color.slow {
  background: #f59e0b;
}

.legend-color.congested {
  background: #ef4444;
}

.source-mark {
  border: 1px dashed #67e8f9;
  border-radius: 4px;
  height: 12px;
  width: 22px;
}

.legend-text {
  color: #bfdbfe;
  font-size: 13px;
}

@media (max-width: 900px) {
  .heatmap-header,
  .heatmap-main {
    grid-template-columns: 1fr;
  }

  .heatmap-header {
    display: grid;
  }

  .metric-column {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .traffic-heatmap-container {
    padding: 16px;
  }

  .chart-wrapper {
    height: 280px;
  }

  .metric-column {
    grid-template-columns: 1fr;
  }

  .heatmap-state {
    min-width: 0;
    width: 100%;
  }
}
</style>
