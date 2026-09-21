import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * 按模式注入 CSP（Content-Security-Policy）：
 * - 生产（Electron file:// 加载）：script-src 严格限制，禁止内联脚本执行（防 XSS）
 * - 开发：react-refresh 需要内联脚本，放宽 script-src，其余指令与生产一致
 * 注意：简历预览 HTML 本身不含 <script>，严格 CSP 不影响预览；
 * style-src 必须保留 'unsafe-inline'（页面大量使用内联 style 属性）。
 */
function cspPlugin(): Plugin {
  let mode = 'production';
  return {
    name: 'inject-csp',
    config(_config: unknown, env: { mode: string }) {
      mode = env.mode;
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html: string) {
        const isProd = mode === 'production';
        const scriptSrc = isProd ? "'self' file: blob:" : "'self' 'unsafe-inline'";
        const policy = [
          "default-src 'self'",
          `script-src ${scriptSrc}`,
          "style-src 'self' 'unsafe-inline'",
          'img-src * data: blob: file:',
          "font-src 'self' data: file:",
          "connect-src 'self' http://127.0.0.1:8765 ws://127.0.0.1:8765 http://localhost:8765 ws://localhost:8765",
          'frame-src http://127.0.0.1:8765 http://localhost:8765 https:',
          "worker-src 'self' blob:",
          "object-src 'none'",
          "base-uri 'self'",
          "form-action 'self'",
        ].join('; ');
        return html.replace(
          '<title>',
          `<meta http-equiv="Content-Security-Policy" content="${policy}">\n    <title>`,
        );
      },
    },
  };
}

export default defineConfig({
  plugins: [react(), cspPlugin()],
  base: './',
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      '/agent': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        ws: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
