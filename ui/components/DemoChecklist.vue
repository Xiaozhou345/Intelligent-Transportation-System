<script setup>
import { computed } from 'vue'
import { ElTag } from 'element-plus'

const props = defineProps({
  connectionStatus: {
    type: String,
    default: '未连接'
  },
  streamStatus: {
    type: String,
    default: '未连接'
  },
  devices: {
    type: Array,
    default: () => []
  },
  user: {
    type: Object,
    default: null
  },
  serverUrl: {
    type: String,
    default: ''
  },
  streamUrl: {
    type: String,
    default: ''
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

const onlineDeviceCount = computed(() => props.devices.filter(device => device.status === 'online').length)

const checks = computed(() => [
  {
    label: '后端 API / Socket.IO',
    ok: props.connectionStatus === '已连接' || props.connectionStatus === '演示模式',
    detail: props.connectionStatus
  },
  {
    label: '云端 MediaMTX 视频流',
    ok: props.streamStatus === '拉流中' || props.streamStatus === '演示流',
    detail: props.streamStatus
  },
  {
    label: '边端设备状态',
    ok: onlineDeviceCount.value > 0,
    detail: `${onlineDeviceCount.value}/${props.devices.length} 在线`
  },
  {
    label: '用户权限',
    ok: Boolean(props.user),
    detail: props.user ? `${props.user.username} / ${props.user.role}` : '未登录'
  },
  {
    label: '事件接收',
    ok: props.eventCount > 0,
    detail: `${props.eventCount} 条`
  },
  {
    label: '告警闭环',
    ok: props.alarmCount >= 0,
    detail: `${props.alarmCount} 条待处理`
  }
])

const readyCount = computed(() => checks.value.filter(item => item.ok).length)
const readiness = computed(() => Math.round((readyCount.value / checks.value.length) * 100))
const readinessType = computed(() => readiness.value >= 85 ? 'success' : readiness.value >= 60 ? 'warning' : 'danger')

const shortUrl = (url) => {
  if (!url) return '-'
  return url.replace(/^https?:\/\//, '').replace(/\/$/, '')
}
</script>

<template>
  <section class="demo-checklist">
    <div class="section-header">
      <div>
        <h2>演示检查清单</h2>
        <p>API、视频流、设备、权限与事件链路</p>
      </div>
      <ElTag :type="readinessType" size="large">{{ readiness }}%</ElTag>
    </div>

    <div class="check-list">
      <div v-for="item in checks" :key="item.label" class="check-item">
        <span :class="['check-dot', item.ok ? 'ok' : 'warn']"></span>
        <div>
          <strong>{{ item.label }}</strong>
          <em>{{ item.detail }}</em>
        </div>
      </div>
    </div>

    <div class="endpoint-grid">
      <div>
        <span>API</span>
        <strong>{{ shortUrl(serverUrl) }}</strong>
      </div>
      <div>
        <span>视频</span>
        <strong>{{ shortUrl(streamUrl) }}</strong>
      </div>
    </div>
  </section>
</template>

<style scoped>
.demo-checklist {
  background: linear-gradient(180deg, rgba(15, 23, 42, 0.9), rgba(8, 18, 33, 0.92));
  border: 1px solid rgba(56, 189, 248, 0.22);
  border-radius: 8px;
  box-shadow: 0 18px 38px rgba(2, 8, 23, 0.36), inset 0 1px 0 rgba(255, 255, 255, 0.05);
  color: #dbeafe;
  padding: 16px;
}

.section-header {
  align-items: flex-start;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-header h2 {
  color: #e0f2fe;
  font-size: 17px;
}

.section-header p {
  color: #93c5fd;
  font-size: 12px;
  margin-top: 4px;
}

.check-list {
  display: grid;
  gap: 9px;
}

.check-item {
  align-items: center;
  background: rgba(15, 23, 42, 0.58);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  display: grid;
  gap: 10px;
  grid-template-columns: 10px 1fr;
  padding: 9px 10px;
}

.check-dot {
  border-radius: 50%;
  height: 10px;
  width: 10px;
}

.check-dot.ok {
  background: #22c55e;
  box-shadow: 0 0 12px rgba(34, 197, 94, 0.6);
}

.check-dot.warn {
  background: #f59e0b;
  box-shadow: 0 0 12px rgba(245, 158, 11, 0.5);
}

.check-item strong {
  color: #e0f2fe;
  display: block;
  font-size: 13px;
}

.check-item em {
  color: #93c5fd;
  display: block;
  font-size: 12px;
  font-style: normal;
  margin-top: 2px;
}

.endpoint-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr;
  margin-top: 12px;
}

.endpoint-grid div {
  min-width: 0;
  background: rgba(14, 165, 233, 0.1);
  border: 1px solid rgba(56, 189, 248, 0.14);
  border-radius: 8px;
  padding: 9px 10px;
}

.endpoint-grid span,
.endpoint-grid strong {
  display: block;
}

.endpoint-grid span {
  color: #93c5fd;
  font-size: 12px;
}

.endpoint-grid strong {
  color: #e0f2fe;
  font-size: 12px;
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
