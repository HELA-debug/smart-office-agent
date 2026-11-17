/** 运行时开关（演示/联调）。 */
import type { RunMode } from '../types/events';

const params = new URLSearchParams(window.location.search);

/**
 * 本地 mock 事件流：
 * - 显式 `?mock=1` 或 `VITE_MOCK=1` 时启用；
 * - 用与 SSE 完全相同的事件序列驱动同一套 reducer，便于演示兜底与无后端截图。
 */
export const IS_MOCK_MODE = params.get('mock') === '1' || import.meta.env.VITE_MOCK === '1';

/** 函数形式：供 feature 层按需调用（便于测试时 mock）。 */
export function isMockMode(): boolean {
  return IS_MOCK_MODE;
}

/**
 * 运行模式调试覆盖：`?run_mode=mock` 或 VITE_RUN_MODE=mock|real。
 * 用于真实模型不可用时的演示/联调兜底，随每次 POST /runs/stream 的 mode 字段下发。
 */
export const RUN_MODE_OVERRIDE: RunMode | null = (() => {
  const fromQuery = params.get('run_mode');
  const fromEnv = import.meta.env.VITE_RUN_MODE;
  const value = fromQuery ?? fromEnv;
  return value === 'mock' || value === 'real' ? value : null;
})();

/** 后端 old base（v0.1 兼容路径，开发走 Vite 代理；生产由 Nginx 反代）。 */
export const API_BASE = '/api';

/** 后端 v1 base（B1 之后的正式契约；旧 /api 仅保留兼容）。 */
export const API_V1_BASE = '/api/v1';

/** 非流式请求默认超时。 */
export const REQUEST_TIMEOUT_MS = 15_000;

/** 文件上传超时（解析大文件更慢）。 */
export const UPLOAD_TIMEOUT_MS = 120_000;

/** SSE 断线自动重连的最大尝试次数与退避基数。 */
export const SSE_MAX_RECONNECTS = 3;
export const SSE_RECONNECT_BASE_DELAY_MS = 800;
