/**
 * 本机服务「在线 / 断开」的被动状态：HTTP 层顺手记一笔，界面订阅后给提示。
 *
 * 为什么不做轮询：用户不用的时候不该一直发请求，轮询还容易在浏览器休眠后
 * 变成一串超时噪声。真正的需求是「点了没反应」或「界面停在那儿不动」时有话可说，
 * 所以每次请求成功/失败顺手广播一次就够。
 *
 * 背景（产品事实，界面文案据此写）：桌面图标 —— 包括「安装到本机」装出来的窗口 ——
 * 只是浏览器窗口，指向 http://127.0.0.1:8000，本身不含服务端。黑窗口一关、
 * 电脑重启过，服务就没了，此时界面还能显示已加载的内容，但任何请求都会失败。
 */
import { API_V1_BASE } from '../config/runtime';

export const BACKEND_STATUS_EVENT = 'office-agent:backend-status';

export type BackendStatus = 'online' | 'offline';

/** 请求成功（哪怕 HTTP 4xx/5xx：能收到响应就说明服务活着）→ online */
export function emitBackendStatus(status: BackendStatus): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<BackendStatus>(BACKEND_STATUS_EVENT, { detail: status }));
}

/** 订阅状态变化，返回退订函数（React effect 直接 return 它）。 */
export function onBackendStatus(handler: (status: BackendStatus) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<BackendStatus>).detail;
    if (detail === 'online' || detail === 'offline') handler(detail);
  };
  window.addEventListener(BACKEND_STATUS_EVENT, listener);
  return () => window.removeEventListener(BACKEND_STATUS_EVENT, listener);
}

/**
 * 主动探一次（「重试」按钮用）：能拿到健康响应就算恢复。
 *
 * 不抛异常——按钮的语义是「再试一下」，失败就是失败，界面保持提示即可。
 */
export async function probeBackend(timeoutMs = 4000): Promise<boolean> {
  if (typeof fetch !== 'function') return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_V1_BASE}/health`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
    });
    if (response.ok) {
      emitBackendStatus('online');
      return true;
    }
    return false;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
