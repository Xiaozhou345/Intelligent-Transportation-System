<script setup>
import { computed } from 'vue'

const props = defineProps({
  connectionStatus: {
    type: String,
    default: '未连接'
  },
  reconnectCount: {
    type: Number,
    default: 0
  },
  devices: {
    type: Array,
    default: () => []
  },
  systemData: {
    type: Object,
    default: () => ({})
  },
  serverUrl: {
    type: String,
    default: ''
  },
  streamUrl: {
    type: String,
    default: ''
  },
  activeSceneLabel: {
    type: String,
    default: '车辆检测'
  },
  simulationMode: {
    type: Boolean,
    default: false
  }
})

const onlineDevices = computed(() => props.devices.filter(device => device.status === 'online').length)
const edgeDevice = computed(() => props.devices.find(device => device.status === 'online') || props.devices[0] || null)

const streamStatus = computed(() => {
  if (props.systemData.stream_status === 'streaming') return '拉流中'
  if (props.systemData.stream_status === 'disconnected') return '已断开'
  return props.connectionStatus === '已连接' || props.connectionStatus === '演示模式' ? '待确认' : '未连接'
})

const cloudStatus = computed(() => {
  if (props.simulationMode) return { text: '演示模式', className: 'status-warning' }
  if (props.connectionStatus === '已连接') return { text: '在线', className: 'status-ok' }
  if (props.connectionStatus === '连接中' || props.connectionStatus === '重连中') return { text: '连接中', className: 'status-warning' }
  return { text: '离线', className: 'status-danger' }
})

const shortUrl = (url) => {
  if (!url) return '-'
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '')
}
</script>

<template>
  <section class="cloud-edge-status">
    <div class="section-title">
      <div>
        <h2>云边端链路</h2>
        <p>边端采集、云端分析、前端展示</p>
      </div>
      <span :class="['status-pill', cloudStatus.className]">{{ cloudStatus.text }}</span>
    </div>

    <div class="pipeline">
      <div class="node">
        <div class="node-icon">EDGE</div>
        <div class="node-title">边端设备</div>
        <div class="node-value">{{ edgeDevice?.device_id || '未接入' }}</div>
        <div class="node-meta">{{ onlineDevices }}/{{ devices.length }} 在线</div>
      </div>
      <div class="flow-line"></div>
      <div class="node">
        <div class="node-icon">AI</div>
        <div class="node-title">云端服务</div>
        <div class="node-value">{{ shortUrl(serverUrl) }}</div>
        <div class="node-meta">重连 {{ reconnectCount }} 次</div>
      </div>
      <div class="flow-line"></div>
      <div class="node">
        <div class="node-icon">UI</div>
        <div class="node-title">前端大屏</div>
        <div class="node-value">{{ activeSceneLabel }}</div>
        <div class="node-meta">实时展示</div>
      </div>
    </div>

    <div class="link-metrics">
      <div>
        <span>视频流</span>
        <strong>{{ streamStatus }}</strong>
      </div>
      <div>
        <span>码率</span>
        <strong>{{ systemData.bitrate || '-' }} kbps</strong>
      </div>
      <div>
        <span>流地址</span>
        <strong>{{ shortUrl(streamUrl) }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.cloud-edge-status {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
}

.section-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.section-title h2 {
  color: #e0f2fe;
  font-size: 17px;
  margin-bottom: 4px;
}

.section-title p {
  color: #7dd3fc;
  font-size: 12px;
}

.status-pill {
  border-radius: 999px;
  color: #ffffff;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 10px;
  white-space: nowrap;
}

.status-ok {
  background: #059669;
  box-shadow: 0 0 14px rgba(16, 185, 129, 0.52);
}

.status-warning {
  background: #d97706;
  box-shadow: 0 0 14px rgba(245, 158, 11, 0.45);
}

.status-danger {
  background: #dc2626;
  box-shadow: 0 0 14px rgba(239, 68, 68, 0.45);
}

.pipeline {
  display: grid;
  grid-template-columns: 1fr 32px 1fr 32px 1fr;
  align-items: center;
  gap: 8px;
}

.node {
  min-width: 0;
  border: 1px solid rgba(56, 189, 248, 0.2);
  border-radius: 8px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.62);
  box-shadow: inset 0 0 20px rgba(14, 165, 233, 0.06);
}

.node-icon {
  align-items: center;
  background: linear-gradient(135deg, rgba(34, 211, 238, 0.22), rgba(37, 99, 235, 0.24));
  border: 1px solid rgba(125, 211, 252, 0.35);
  border-radius: 6px;
  color: #67e8f9;
  display: inline-flex;
  font-size: 11px;
  font-weight: 800;
  height: 26px;
  justify-content: center;
  margin-bottom: 8px;
  min-width: 38px;
  padding: 0 8px;
}

.node-title {
  color: #93c5fd;
  font-size: 12px;
}

.node-value {
  color: #f8fafc;
  font-size: 14px;
  font-weight: 700;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-meta {
  color: #7dd3fc;
  font-size: 12px;
  margin-top: 4px;
}

.flow-line {
  height: 2px;
  background: linear-gradient(90deg, rgba(34, 211, 238, 0.2), #22d3ee);
  box-shadow: 0 0 12px rgba(34, 211, 238, 0.6);
  position: relative;
}

.flow-line::after {
  content: '';
  position: absolute;
  right: -1px;
  top: -4px;
  border-bottom: 5px solid transparent;
  border-left: 8px solid #22d3ee;
  border-top: 5px solid transparent;
}

.link-metrics {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-top: 14px;
}

.link-metrics div {
  min-width: 0;
  border-radius: 8px;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.14);
  padding: 10px;
}

.link-metrics span {
  color: #93c5fd;
  display: block;
  font-size: 12px;
}

.link-metrics strong {
  color: #e0f2fe;
  display: block;
  font-size: 13px;
  margin-top: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 900px) {
  .pipeline,
  .link-metrics {
    grid-template-columns: 1fr;
  }

  .flow-line {
    display: none;
  }
}
</style>
