import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    /**
     * 串行执行测试文件（关闭文件级并行）。
     *
     * 并行时每个 worker 都要加载一份 jsdom + React，本项目 20+ 测试文件会让 worker
     * 触发 V8 的 "Zone Allocation failed - process out of memory"，
     * 表现为「部分测试文件静默不执行、覆盖率虚低到 22%」，比 OOM 崩溃更难发现。
     * 串行后单进程内存可控（约 30s 跑完 600+ 用例），结果稳定可复现。
     */
    fileParallelism: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
    restoreMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      // 不做清理，直接覆盖写入：clean 会调用系统回收站 API，在受限环境里会失败并中断整轮测试。
      // 产物每次都会被同名覆盖，不残留脏数据。
      clean: false,
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/main.tsx',
        'src/app/**',
        'src/test/**',
        'src/shared/api/generated/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/index.ts',
        // 纯类型模块无运行时语句，计入会拉低且无意义
        'src/shared/types/api.ts',
      ],
      /**
       * 覆盖率门槛（评审 P1-7）：已达到 DoD 第 13 条的 60% 目标。
       * 当前实测 72.05 / 63.37 / 63.07 / 73.15（语句 / 分支 / 函数 / 行）。
       * 门槛按 60 卡，四项一起提，避免只挑容易的指标刷数值；
       * 分支与函数天然低于语句（可选参数、错误分支），所以不按最高项一刀切。
       */
      thresholds: {
        statements: 60,
        branches: 60,
        functions: 60,
        lines: 60,
      },
    },
  },
});
