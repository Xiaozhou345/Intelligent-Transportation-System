import { io } from 'socket.io-client'

// ============================================================
// 🎮 模拟模式开关
// true  = 使用模拟数据（后端未启动时使用）
// false = 连接真实后端 WebSocket
// ============================================================
const envSimulationMode = import.meta.env.VITE_SIMULATION_MODE
const SIMULATION_MODE = envSimulationMode === undefined ? false : envSimulationMode !== 'false'

// ============================================================
// 模拟数据生成器
// ============================================================
class MockDataGenerator {
  constructor() {
    this.eventTypes = [
      'plate_recognition',
      'traffic_density',
      'illegal_parking',
      'road_anomaly'
    ]
    this.plates = ['京A12345', '京B67890', '沪C11223', '粤D44556', '苏E77889']
    this.owners = ['张三', '李四', '王五', '赵六', '孙七']
  }

  generate() {
    const eventType = this.eventTypes[Math.floor(Math.random() * this.eventTypes.length)]
    const timestamp = new Date().toISOString()
    const deviceId = 'mobile_001'

    const baseData = {
      event_type: eventType,
      timestamp: timestamp,
      device_id: deviceId,
      status: Math.random() > 0.2 ? 'normal' : 'warning'
    }

    switch (eventType) {
      case 'plate_recognition':
        return {
          ...baseData,
          data: {
            plate_number: this.plates[Math.floor(Math.random() * this.plates.length)],
            is_in_whitelist: Math.random() > 0.5,
            decision: Math.random() > 0.5 ? 'allow' : 'deny'
          },
          bbox: [100 + Math.random() * 200, 80 + Math.random() * 100, 120 + Math.random() * 200, 100 + Math.random() * 100]
        }

      case 'traffic_density':
        return {
          ...baseData,
          data: {
            regions: [
              { region_id: 'road_A', vehicle_count: Math.floor(Math.random() * 8), status: this._getDensityStatus(), color: this._getDensityColor() },
              { region_id: 'road_B', vehicle_count: Math.floor(Math.random() * 8), status: this._getDensityStatus(), color: this._getDensityColor() },
              { region_id: 'road_C', vehicle_count: Math.floor(Math.random() * 8), status: this._getDensityStatus(), color: this._getDensityColor() },
              { region_id: 'road_D', vehicle_count: Math.floor(Math.random() * 8), status: this._getDensityStatus(), color: this._getDensityColor() }
            ]
          }
        }

      case 'illegal_parking':
        return {
          ...baseData,
          data: {
            track_id: Math.floor(Math.random() * 100),
            stay_time: 20 + Math.random() * 40,
            threshold: 30
          },
          bbox: [200 + Math.random() * 200, 150 + Math.random() * 100, 220 + Math.random() * 200, 170 + Math.random() * 100],
          status: Math.random() > 0.5 ? 'warning' : 'normal'
        }

      case 'road_anomaly':
        return {
          ...baseData,
          data: {
            anomaly_type: ['unknown_object', 'fallen_object', 'debris'][Math.floor(Math.random() * 3)],
            affected_lane: ['lane_1', 'lane_2', 'lane_3'][Math.floor(Math.random() * 3)],
            duration_frames: Math.floor(10 + Math.random() * 30)
          },
          bbox: [300 + Math.random() * 150, 200 + Math.random() * 100, 320 + Math.random() * 150, 220 + Math.random() * 100],
          status: 'warning'
        }

      default:
        return baseData
    }
  }

  _getDensityStatus() {
    const val = Math.random()
    if (val < 0.33) return 'smooth'
    if (val < 0.66) return 'slow'
    return 'congested'
  }

  _getDensityColor() {
    const val = Math.random()
    if (val < 0.33) return 'green'
    if (val < 0.66) return 'yellow'
    return 'red'
  }
}

// ============================================================
// WebSocket 管理器（支持模拟模式）
// ============================================================
class WebSocketManager {
  constructor() {
    this.ws = null
    this.url = null
    this.reconnectInterval = 3000
    this.maxReconnectAttempts = 10
    this.reconnectCount = 0
    this.onMessageCallback = null
    this.onStatusChangeCallback = null
    this.reconnectTimer = null
    this.status = 'disconnected'
    this.mockTimer = null
    this.mockGenerator = new MockDataGenerator()
    this.isSimulation = SIMULATION_MODE
  }

  connect(url) {
    this.url = url

    // 模拟模式：不真实连接，直接生成模拟数据
    if (this.isSimulation) {
      this.status = 'simulating'
      this._notifyStatusChange()
      this._startMockData()
      return
    }

    // 真实连接模式
    if (this.ws && this.ws.connected) {
      return
    }

    this.reconnectCount = 0
    this._createConnection()
  }

  _createConnection() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    try {
      this.ws = io(this.url, {
        auth: { token: import.meta.env.VITE_API_TOKEN || '' },
        // 允许 polling 握手/降级，再自动升级到 WebSocket。
        // 部分 FRP/Nginx 未正确转发 Upgrade 头时，强制 websocket 会完全无法连接。
        transports: ['polling', 'websocket'],
        upgrade: true,
        reconnection: false,
        timeout: 10000
      })
      this.status = 'connecting'
      this._notifyStatusChange()

      this.ws.on('connect', () => {
        this.status = 'connected'
        this.reconnectCount = 0
        this._notifyStatusChange()
        console.log('✅ Socket.IO 连接成功')
      })

      this.ws.on('analysis_result', (data) => {
        if (this.onMessageCallback) {
          this.onMessageCallback(data)
        }
      })

      this.ws.on('connection_status', (data) => {
        if (this.onMessageCallback) {
          this.onMessageCallback({ event_type: 'connection_status', data })
        }
      })

      this.ws.on('anomaly_mode_updated', (data) => {
        if (this.onMessageCallback) {
          this.onMessageCallback({
            event_type: 'anomaly_mode_updated',
            timestamp: new Date().toISOString(),
            status: data.status || 'normal',
            data
          })
        }
      })

      this.ws.on('scene_switched', (data) => {
        if (this.onMessageCallback) {
          this.onMessageCallback({
            event_type: 'scene_switched',
            timestamp: new Date().toISOString(),
            status: 'normal',
            data
          })
        }
      })

      this.ws.on('devices_list', (data) => {
        if (this.onMessageCallback) {
          this.onMessageCallback({
            event_type: 'devices_list',
            timestamp: new Date().toISOString(),
            status: 'normal',
            data
          })
        }
      })

      this.ws.on('connect_error', (error) => {
        console.error('❌ Socket.IO 连接错误:', error)
        this.status = 'error'
        this._notifyStatusChange()
        this._handleReconnect()
      })

      this.ws.on('disconnect', () => {
        if (this.status !== 'simulating') {
          this._handleReconnect()
        }
      })
    } catch (error) {
      console.error('❌ Socket.IO 连接异常:', error)
      this.status = 'error'
      this._notifyStatusChange()
      this._handleReconnect()
    }
  }

  _handleReconnect() {
    if (this.reconnectCount >= this.maxReconnectAttempts) {
      this.status = 'disconnected'
      this._notifyStatusChange()
      console.warn('⚠️ 达到最大重试次数，停止重连')
      return
    }

    this.reconnectCount++
    this.status = 'reconnecting'
    this._notifyStatusChange()
    console.log(`🔄 第 ${this.reconnectCount} 次重连尝试...`)

    this.reconnectTimer = setTimeout(() => {
      this._createConnection()
    }, this.reconnectInterval)
  }

  _notifyStatusChange() {
    if (this.onStatusChangeCallback) {
      this.onStatusChangeCallback(this.status, this.reconnectCount)
    }
  }

  // ============================================================
  // 🎮 模拟数据模式
  // ============================================================
  _startMockData() {
    if (this.mockTimer) {
      clearInterval(this.mockTimer)
    }

    console.log('🟡 [模拟模式] 已启用，每 3-5 秒生成一条模拟数据')

    // 立即发送一条
    this._sendMockData()

    // 定时发送
    this.mockTimer = setInterval(() => {
      this._sendMockData()
    }, 3000 + Math.random() * 2000)
  }

  _sendMockData() {
    if (!this.onMessageCallback) return

    const data = this.mockGenerator.generate()
    console.log('🟡 [模拟数据]', data.event_type, data)

    // 模拟网络延迟
    this.onMessageCallback(data)
  }

  // ============================================================
  // 公共方法
  // ============================================================
  send(data) {
    if (this.isSimulation) {
      console.log('🟡 [模拟模式] 发送指令:', data)
      return true
    }

    if (this.ws && this.ws.connected) {
      this.ws.emit('client_command', data)
      return true
    }
    return false
  }

  sendEvent(eventName, data = {}) {
    if (this.isSimulation) {
      console.log('🟡 [模拟模式] 发送事件:', eventName, data)
      return true
    }

    if (this.ws && this.ws.connected) {
      this.ws.emit(eventName, data)
      return true
    }
    return false
  }

  onMessage(callback) {
    this.onMessageCallback = callback
  }

  onStatusChange(callback) {
    this.onStatusChangeCallback = callback
  }

  disconnect() {
    if (this.mockTimer) {
      clearInterval(this.mockTimer)
      this.mockTimer = null
    }
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.disconnect()
      this.ws = null
    }
    this.status = 'disconnected'
    this.reconnectCount = 0
    this._notifyStatusChange()
    console.log('🔌 WebSocket 已断开')
  }

  getStatus() {
    return this.status
  }

  isSimulating() {
    return this.isSimulation
  }

  // 切换模拟模式（动态切换）
  setSimulationMode(enabled) {
    this.isSimulation = enabled
    if (enabled) {
      this.disconnect()
      this.status = 'simulating'
      this._notifyStatusChange()
      this._startMockData()
    } else {
      if (this.mockTimer) {
        clearInterval(this.mockTimer)
        this.mockTimer = null
      }
      if (this.url) {
        this.connect(this.url)
      }
    }
  }
}

// ============================================================
// 导出单例
// ============================================================
const websocketManager = new WebSocketManager()

export default websocketManager
