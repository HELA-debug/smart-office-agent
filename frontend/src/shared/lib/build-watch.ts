/**
 * 构建更新检测：让「装成桌面端」的窗口跟上网页端。
 *
 * 桌面窗口装好之后往往一开就是一整天，而服务端换了新构建（vite 的入口脚本带
 * 内容哈希，名字会变）。窗口里跑的还是旧脚本，用户看到的就是「网页端改了，
 * 桌面端没变」——最容易被当成 bug。这里只做一件事：发现服务端入口脚本换了名字，
 * 就自动刷新一次。
 *
 * 为什么不靠 Service Worker：sw.js 本身是静态文件，构建不改变它的字节，
 * 浏览器就不会触发更新，`controllerchange` 也就永远不响。
 */

/** 两次检查的最小间隔：切回来太快时别连着发请求。 */
const CHECK_INTERVAL_MS = 60_000;

/** 从一段 HTML 里取出模块入口脚本地址（dist/index.html 里形如 /assets/index-xxxx.js）。 */
export function pickEntryScript(html: string): string | null {
  const match = html.match(/<script[^>]*\btype="module"[^>]*\bsrc="([^"]+)"/i);
  if (match?.[1]) return match[1];
  // 属性顺序不保证（vite 版本差异），再按 src 在前匹配一次
  const fallback = html.match(/<script[^>]*\bsrc="([^"]+\.js)"[^>]*\btype="module"/i);
  return fallback?.[1] ?? null;
}

/** 页面当前真正在跑的入口脚本。 */
function currentEntry(): string | null {
  const script = document.querySelector<HTMLScriptElement>('script[type="module"][src]');
  return script?.getAttribute('src') ?? null;
}

function reloadOnce(): void {
  const key = 'oa:build-reloaded-at';
  const last = Number(sessionStorage.getItem(key) ?? '0');
  // 服务端缓存没配对时可能「刷完还是旧的」，加个 30 秒闸门避免刷新循环
  if (Date.now() - last < 30_000) return;
  sessionStorage.setItem(key, String(Date.now()));
  window.location.reload();
}

/**
 * 开始盯着服务端的构建：页面加载后查一次，之后每次切回窗口时再查。
 * 返回取消函数（测试/卸载时用）。
 */
export function watchForRebuild(): () => void {
  const mine = currentEntry();
  if (!mine) return () => {};

  let lastCheckedAt = 0;
  let stopped = false;

  const check = () => {
    if (stopped) return;
    const now = Date.now();
    if (now - lastCheckedAt < CHECK_INTERVAL_MS) return;
    lastCheckedAt = now;

    void fetch('/index.html', { cache: 'no-store' })
      .then((response) => (response.ok ? response.text() : ''))
      .then((html) => {
        if (stopped) return;
        const next = pickEntryScript(html);
        // 取不到（离线 / 服务挂了）：保持现状，不要因为一次失败就刷掉用户正在看的页面
        if (next && next !== mine) reloadOnce();
      })
      .catch(() => {
        /* 离线时静默：等下次切回来再试 */
      });
  };

  const onVisible = () => {
    if (document.visibilityState === 'visible') check();
  };

  // 首屏先跑起来再查，别和字体/首屏渲染抢带宽
  const timer = window.setTimeout(check, 3000);
  document.addEventListener('visibilitychange', onVisible);

  return () => {
    stopped = true;
    window.clearTimeout(timer);
    document.removeEventListener('visibilitychange', onVisible);
  };
}
