/**
 * 桌面端安装能力单测：平台判定和「已是独立窗口」这两件事决定文案与按钮，
 * 判错了就会给 iPhone 用户推 "下载 .exe"。
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { canInstall, detectPlatform, isStandalone, PLATFORM_LABEL, promptInstall } from './desktop';

function withUserAgent(userAgent: string) {
  vi.stubGlobal('navigator', { ...navigator, userAgent });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('detectPlatform', () => {
  it.each([
    ['Mozilla/5.0 (Windows NT 10.0; Win64; x64)', 'windows'],
    ['Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 'macos'],
    ['Mozilla/5.0 (X11; Linux x86_64)', 'linux'],
    ['Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)', 'ios'],
    ['Mozilla/5.0 (Linux; Android 14; Pixel 8)', 'android'],
    ['某个不认识的内嵌浏览器', 'other'],
  ])('%s → %s', (ua, expected) => {
    withUserAgent(ua);
    expect(detectPlatform()).toBe(expected);
  });

  it('每个平台都有中文可读的标签', () => {
    expect(PLATFORM_LABEL.windows).toBe('Windows');
    expect(PLATFORM_LABEL.ios).toBe('iPhone / iPad');
    expect(PLATFORM_LABEL.other).toBe('当前设备');
  });
});

describe('isStandalone', () => {
  it('display-mode: standalone 视为已安装', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }));
    expect(isStandalone()).toBe(true);
  });

  it('window-controls-overlay 也算已安装（现在桌面端默认这个形态）', () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn((query: string) => ({ matches: query.includes('window-controls-overlay') })),
    );
    expect(isStandalone()).toBe(true);
  });

  it('iOS 的 navigator.standalone 也算', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
    vi.stubGlobal('navigator', { ...navigator, standalone: true });
    expect(isStandalone()).toBe(true);
  });

  it('普通浏览器标签页里不算', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }));
    expect(isStandalone()).toBe(false);
  });
});

describe('安装能力', () => {
  it('浏览器没抛过 beforeinstallprompt 时不可安装、调起也返回 unavailable', async () => {
    expect(canInstall()).toBe(false);
    await expect(promptInstall()).resolves.toBe('unavailable');
  });
});
