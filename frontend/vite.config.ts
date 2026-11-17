import { execSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

/**
 * 构建指纹：`<git 短 sha>-<YYYYMMDDHHmm>`。
 *
 * 为什么需要它：`frontend/dist` 与打包好的 exe 都在 .gitignore 里，`git pull` 只更新源码，
 * 不重新构建的话，本地跑起来看到的还是旧界面——而界面上没有任何东西能说明这一点，
 * 于是很容易被当成「样式/清晰度坏了」。有了指纹，页面里（设置 → 关于）和 /api/v1/health
 * 的 git_sha 一比，就知道是谁旧了。
 */
function gitShortSha(): string {
  try {
    return execSync('git rev-parse --short HEAD', {
      stdio: ['ignore', 'pipe', 'ignore'],
    })
      .toString()
      .trim();
  } catch {
    return 'nogit';
  }
}

function stamp(): string {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}`;
}

/**
 * 把构建号写进 `dist/sw.js`。
 *
 * public/ 里的文件是原样拷贝的：之前 sw.js 的 `VERSION` 写死 `v3`，每构建一次字节都一样，
 * 浏览器就认为「这个 Service Worker 没变」，装成桌面端的窗口会一直用缓存里的旧外壳。
 * 每次构建换一个版本号，SW 才会真的走到 install → 清旧缓存 → 换新外壳。
 */
function swVersionPlugin(buildId: string) {
  return {
    name: 'oa-sw-version',
    apply: 'build' as const,
    closeBundle() {
      const target = fileURLToPath(new URL('./dist/sw.js', import.meta.url));
      if (!existsSync(target)) return;
      const source = readFileSync(target, 'utf8');
      if (!source.includes('__SW_VERSION__')) return;
      writeFileSync(target, source.replaceAll('__SW_VERSION__', buildId), 'utf8');
    },
  };
}

// https://vite.dev/config/
export default defineConfig(({ mode, command }) => {
  // 默认代理到本地 8000；联调时可用 VITE_API_TARGET 指向别的后端端口。
  const env = loadEnv(mode, '.', '');
  const apiTarget = env.VITE_API_TARGET || 'http://127.0.0.1:8000';
  const buildId = `${gitShortSha()}-${stamp()}`;

  if (command === 'serve') {
    // 启动时把真实代理目标打出来。换了后端端口却忘记同步 VITE_API_TARGET 时，
    // 页面照样渲染成功、只是数据全空——看着像「页面没出来」，而终端这行能一眼抓到。
    console.log(`\n  [oa] API 代理 → ${apiTarget}`);
    if (!env.VITE_API_TARGET) {
      console.log('  [oa] 未设 VITE_API_TARGET，用的是默认 8000\n');
    }
  }

  return {
    plugins: [react(), tailwindcss(), swVersionPlugin(buildId)],
    define: {
      __BUILD_ID__: JSON.stringify(buildId),
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        // 所有 /api 请求（含 SSE）都走这里。
        // timeout/proxyTimeout 置 0：SSE 连接要长时间保持（运行中 + 审批挂起 180s）。
        // Accept-Encoding: identity：不让中间层压缩/缓冲事件流。
        '/api': {
          target: apiTarget,
          changeOrigin: true,
          timeout: 0,
          proxyTimeout: 0,
          headers: {
            'Accept-Encoding': 'identity',
          },
        },
      },
    },
  };
});
