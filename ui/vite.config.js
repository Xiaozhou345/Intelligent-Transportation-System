import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, './')
    }
  },
  server: {
    proxy: {
      '/socket.io': {
        target: 'http://172.20.10.4:5000',
        ws: true,
        changeOrigin: true,
        secure: false
      }
    }
  }
})