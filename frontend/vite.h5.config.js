import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'home-flow-h5-root',
      configureServer(server) {
        server.middlewares.use((req, _res, next) => {
          if (req.url === '/') req.url = '/h5.html'
          next()
        })
      },
    },
  ],
  server: {
    host: '0.0.0.0',
    port: 5172,
  },
  build: {
    outDir: 'dist-h5',
    rollupOptions: {
      input: 'h5.html',
    },
  },
})
