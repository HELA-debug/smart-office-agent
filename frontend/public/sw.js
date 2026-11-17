/* eslint-disable no-restricted-globals */
/**
 * Service Worker：让「安装成桌面端」这件事真的成立。
 *
 * 浏览器只在**有 manifest + 有 Service Worker + 能从 localhost/https 访问**时
 * 才认为这个站可以安装（会抛 beforeinstallprompt）。之前没有这两个文件，
 * 所以「一键安装」永远走不到，只能给手动指引——那不是真的实现。
 *
 * 策略：
 * - 导航请求：网络优先，断网回落到缓存的 index.html（离线也能打开外壳）；
 * - 静态资源（Vite 出的 /assets/*）：缓存优先 + 后台更新；
 * - /api/ 一律不缓存（数据必须实时，缓存了会看到旧会话/旧产物）。
 */

/* 版本号由构建注入（vite.config.ts 的 swVersionPlugin 把 __SW_VERSION__ 换成
   `<git sha>-<构建时间>`）。写死常量的话每次构建字节相同，浏览器认为 SW 没变，
   装成桌面端的窗口就会一直用缓存里的旧外壳——那正是「本地看起来和预览不一样」的成因之一。 */
const VERSION = '__SW_VERSION__';
const SHELL_CACHE = `office-agent-shell-${VERSION}`;
const ASSET_CACHE = `office-agent-assets-${VERSION}`;
const SHELL_FILES = ['/', '/index.html', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(SHELL_FILES))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== ASSET_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  // 只接管同源请求；接口与事件流不碰
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/events')) return;
  // 开发态（vite dev）的源码与 HMR 请求一律直连：缓存它们会让改代码不生效
  if (
    url.pathname.startsWith('/src/') ||
    url.pathname.startsWith('/@') ||
    url.pathname.startsWith('/node_modules/') ||
    url.searchParams.has('t')
  ) {
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match('/index.html').then((cached) => cached ?? Response.error()),
      ),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            void caches.open(ASSET_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => cached ?? Response.error());
      return cached ?? network;
    }),
  );
});
