<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElTag, ElAlert } from 'element-plus'
import websocketManager from './utils/websocketManager'

const connectionStatus = ref('未连接')
const reconnectCount = ref(0)
const showError = ref(false)
const errorMessage = ref('')

const statusMap = {
  disconnected: '未连接',
  connecting: '连接中',
  connected: '已连接',
  reconnecting: '重连中',
  error: '连接失败'
}

const statusTypeMap = {
  disconnected: 'danger',
  connecting: 'warning',
  connected: 'success',
  reconnecting: 'warning',
  error: 'danger'
}

onMounted(() => {
  websocketManager.onMessage((data) => {
    console.log('WebSocket 消息:', data)
  })

  websocketManager.onStatusChange((status, count) => {
    connectionStatus.value = statusMap[status] || status
    reconnectCount.value = count

    if (status === 'disconnected' && count >= 10) {
      showError.value = true
      errorMessage.value = 'WebSocket 连接失败，已达到最大重试次数'
    } else if (status === 'connected') {
      showError.value = false
    }
  })

  websocketManager.connect('ws://192.168.1.100:5000/ws/results')
})

onUnmounted(() => {
  websocketManager.disconnect()
})
</script>

<template>
  <div class="app-container">
    <header class="header">
      <div class="header-content">
        <h1>交通监控系统</h1>
        <div class="status-container">
          <span class="status-label">连接状态：</span>
          <ElTag :type="statusTypeMap[connectionStatus === '已连接' ? 'connected' : connectionStatus === '重连中' ? 'reconnecting' : connectionStatus === '连接中' ? 'connecting' : 'disconnected']" size="large">
            {{ connectionStatus }}
            <span v-if="connectionStatus === '重连中'" class="reconnect-count">
              ({{ reconnectCount }}/{{ websocketManager.maxReconnectAttempts }})
            </span>
          </ElTag>
        </div>
      </div>
    </header>

    <main class="main-content">
      <ElAlert
        v-if="showError"
        title="连接错误"
        :description="errorMessage"
        type="error"
        show-icon
        :closable="false"
      />

      <div class="message-area">
        <h2>控制台日志</h2>
        <div class="log-tip">
          <p>WebSocket 消息将在浏览器控制台中打印。</p>
          <p>按 F12 打开开发者工具查看。</p>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.app-container {
  min-height: 100vh;
  background-color: #f5f7fa;
}

.header {
  background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
  color: white;
  padding: 16px 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 1400px;
  margin: 0 auto;
}

.header h1 {
  font-size: 24px;
  font-weight: 600;
}

.status-container {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-label {
  font-size: 14px;
}

.reconnect-count {
  margin-left: 4px;
  font-size: 12px;
}

.main-content {
  max-width: 1400px;
  margin: 24px auto;
  padding: 0 24px;
}

.message-area {
  background: white;
  border-radius: 8px;
  padding: 24px;
  margin-top: 16px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.message-area h2 {
  font-size: 18px;
  color: #303133;
  margin-bottom: 16px;
}

.log-tip {
  color: #909399;
  font-size: 14px;
  line-height: 1.8;
}
</style>
