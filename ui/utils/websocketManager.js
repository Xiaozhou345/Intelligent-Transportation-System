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
  }

  connect(url) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      return
    }

    this.url = url
    this.reconnectCount = 0
    this._createConnection()
  }

  _createConnection() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    try {
      this.ws = new WebSocket(this.url)
      this.status = 'connecting'
      this._notifyStatusChange()

      this.ws.onopen = () => {
        this.status = 'connected'
        this.reconnectCount = 0
        this._notifyStatusChange()
      }

      this.ws.onmessage = (event) => {
        if (this.onMessageCallback) {
          this.onMessageCallback(event.data)
        }
      }

      this.ws.onerror = () => {
        this.status = 'error'
        this._notifyStatusChange()
        this._handleReconnect()
      }

      this.ws.onclose = () => {
        if (this.status !== 'connected') {
          this._handleReconnect()
        }
      }
    } catch (error) {
      this.status = 'error'
      this._notifyStatusChange()
      this._handleReconnect()
    }
  }

  _handleReconnect() {
    if (this.reconnectCount >= this.maxReconnectAttempts) {
      this.status = 'disconnected'
      this._notifyStatusChange()
      return
    }

    this.reconnectCount++
    this.status = 'reconnecting'
    this._notifyStatusChange()

    this.reconnectTimer = setTimeout(() => {
      this._createConnection()
    }, this.reconnectInterval)
  }

  _notifyStatusChange() {
    if (this.onStatusChangeCallback) {
      this.onStatusChangeCallback(this.status, this.reconnectCount)
    }
  }

  send(data) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(typeof data === 'object' ? JSON.stringify(data) : data)
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
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.status = 'disconnected'
    this.reconnectCount = 0
    this._notifyStatusChange()
  }

  getStatus() {
    return this.status
  }
}

const websocketManager = new WebSocketManager()

export default websocketManager
