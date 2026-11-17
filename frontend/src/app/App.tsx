import { BrowserRouter, useLocation } from 'react-router-dom';
import { ServiceDownBanner } from '../shared/ui/ServiceDownBanner';
import { StaleBuildBanner } from '../shared/ui/StaleBuildBanner';
import { TitlebarDock } from '../shared/ui/TitlebarDock';
import { AppProviders } from './providers';
import { AppRouter } from './router';
import type { ReactNode } from 'react';

/**
 * 换页过渡：pathname 一变就换 key，让 `.route-enter` 的入场动画重放一次。
 *
 * 为什么不给每个 Link / navigate 挂 viewTransition：入口散在顶栏、工作台、
 * 产物卡片的跳转按钮里，十来处，漏一个就少一处有过渡。挂在这里只覆盖一次，
 * 以后新加的入口也自动带上。
 *
 * 只认 pathname、不认 search：`?thread=xxx` 这种同页筛选不该整页重放动画，
 * 否则筛选一次，卡片会跟着浮一下，反而显脏。
 */
function RouteTransition({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  return (
    <div key={pathname} className="route-enter">
      {children}
    </div>
  );
}

/** 应用入口组件：路由 + 全局 provider（错误边界等）。 */
export default function App() {
  return (
    <BrowserRouter>
      <AppProviders>
        {/* 独立窗口的标题栏让位层：挂在路由外面，任何页面都只有一条拖拽区 */}
        <TitlebarDock />
        {/* 本机服务断开时的提示：桌面图标只是窗口，服务才是程序本体 */}
        <ServiceDownBanner />
        {/* 前端产物比后端旧时的提示：本地没重新构建，看到的会是上一版界面 */}
        <StaleBuildBanner />
        {/* 过渡层必须在 Banner 之外、路由之内：提示条属于全局家具，不该跟着页面浮 */}
        <RouteTransition>
          <AppRouter />
        </RouteTransition>
      </AppProviders>
    </BrowserRouter>
  );
}
