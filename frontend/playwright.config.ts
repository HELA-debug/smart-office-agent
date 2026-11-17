import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright 骨架：用本机 Chromium 内核浏览器（channel: 'msedge'，Edge 与 Chrome 同内核），
 * 不额外下载浏览器。本机未安装 Chrome 时回退 Edge。
 * 空状态冒烟不依赖后端；后端联调的 E2E 在 B5 补齐。
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 8_000 },
  // 串行执行：本机（笔记本）并发多实例 Edge 会触发 worker 崩溃，
  // 串行后稳定全绿，用例数量小（<20）对耗时几乎无影响。
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'msedge' },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
