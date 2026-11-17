/**
 * 桌面端（PWA）安装能力。
 *
 * 为什么单独放一层：浏览器只在页面加载早期抛一次 `beforeinstallprompt`，
 * 监听必须在模块作用域完成——组件晚挂载就永远收不到。所以这里维护一份「安装事件」的
 * 订阅表，组件只需要 get / subscribe，不用自己抢那一次事件。
 */

export type Platform = 'windows' | 'macos' | 'linux' | 'ios' | 'android' | 'other';

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>;
}

let deferredPrompt: InstallPromptEvent | null = null;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((notify) => notify());
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeinstallprompt', (event) => {
    // 不拦的话 Chrome 会自己弹一条迷你横幅，和我们右栏的入口打架
    event.preventDefault();
    deferredPrompt = event as InstallPromptEvent;
    emit();
  });
  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    emit();
  });
}

/** 当前设备类型：安装步骤要按平台给不同文案。 */
export function detectPlatform(): Platform {
  if (typeof navigator === 'undefined') return 'other';
  const ua = navigator.userAgent;
  if (/android/i.test(ua)) return 'android';
  if (/iphone|ipad|ipod/i.test(ua)) return 'ios';
  if (/windows/i.test(ua)) return 'windows';
  if (/mac os x|macintosh/i.test(ua)) return 'macos';
  if (/linux/i.test(ua)) return 'linux';
  return 'other';
}

export const PLATFORM_LABEL: Record<Platform, string> = {
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
  ios: 'iPhone / iPad',
  android: 'Android',
  other: '当前设备',
};

/** 已经以桌面端 / 独立窗口方式打开时，不再劝人安装。 */
export function isStandalone(): boolean {
  if (typeof window === 'undefined') return false;
  // window-controls-overlay 是现在桌面端的默认形态（见 shared/lib/titlebar.ts）：
  // 只认 standalone 的话，装好的人还会看到「安装桌面端」。
  const overlay = window.matchMedia?.('(display-mode: window-controls-overlay)').matches ?? false;
  const displayStandalone = window.matchMedia?.('(display-mode: standalone)').matches ?? false;
  const iosStandalone = (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return overlay || displayStandalone || iosStandalone;
}

/** 现在能不能一键安装（浏览器抛过 beforeinstallprompt）。 */
export function canInstall(): boolean {
  return deferredPrompt !== null;
}

/** 订阅「安装能力变化」（安装完成 / 浏览器抛出事件）。返回取消订阅。 */
export function subscribeInstall(notify: () => void): () => void {
  listeners.add(notify);
  return () => listeners.delete(notify);
}

/** 调起安装；返回用户是否接受。 */
export async function promptInstall(): Promise<'accepted' | 'dismissed' | 'unavailable'> {
  const event = deferredPrompt;
  if (!event) return 'unavailable';
  await event.prompt();
  const choice = await event.userChoice;
  if (choice.outcome === 'accepted') {
    deferredPrompt = null;
    emit();
  }
  return choice.outcome;
}

/** 部署时可选：真实的桌面安装包地址（没配就只做浏览器安装引导）。 */
export function desktopDownloadUrl(): string | null {
  const env = import.meta.env as unknown as Record<string, string | undefined>;
  const url = env.VITE_DESKTOP_DOWNLOAD_URL;
  return url && url.trim() ? url : null;
}
