import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_DEV_API_TARGET || 'http://127.0.0.1:5000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': resolve(__dirname, './')
      }
    },
    server: {
      proxy: {
        '/socket.io': {
          target: apiTarget,
          ws: true,
          changeOrigin: true,
          secure: false
        }
      }
    }
  }
})
