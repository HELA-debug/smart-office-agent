import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './app/App';
import { logBuildInfo } from './shared/lib/build-info';
import { watchForRebuild } from './shared/lib/build-watch';
import { installDropGuard } from './shared/lib/drop-guard';
import { initTheme } from './shared/lib/theme';
import './styles/tokens.css';

// 首屏渲染前定好主题与缩放，避免浅色闪一下再切深色
initTheme();

// 文件拖到输入框以外的地方时，别让浏览器把整个应用换成那个文件
installDropGuard();

// 控制台留一行构建号：本地看到的界面和预期不一致时，先对一下这是哪一版
logBuildInfo();

const container = document.getElementById('root');
if (!container) {
  throw new Error('root element not found');
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

/**
 * 注册 Service Worker：安装成桌面端的前提（浏览器要求有 SW + manifest 才允许安装）。
 *
 * 开发态也注册：不然在 localhost 上看不到「一键安装」，无从验证。
 * sw.js 里对 /src/、/@vite、HMR 带 ?t= 的请求一律直连不缓存，改代码照样即时生效。
 */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/sw.js').catch(() => {
      /* 注册失败（隐私模式 / 老浏览器）：安装入口自动回落到手动指引 */
    });
  });
}

/**
 * 桌面端装的是一份静态构建：服务端重新构建后，已经开着的窗口不会自己知道。
 * 这里在首屏和每次切回窗口时对一下入口脚本名，换了就重新加载 —— 网页端刚做完的
 * 改动，桌面窗口切回来就能看到（开发态不需要，Vite 自己会热更新）。
 */
if (import.meta.env.PROD) {
  watchForRebuild();
}
