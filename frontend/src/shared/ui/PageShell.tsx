import { Link, NavLink } from 'react-router-dom';
import { FEATURE_FLAGS, NAV_ITEMS } from '../config/feature-flags';
import { toggleTheme, useTheme } from '../lib/theme';
import { IconChevronLeft, IconLogo, IconMoon, IconSun } from './Icons';
import { IconButton, Tooltip } from './primitives';
import type { ReactNode } from 'react';

/** 顶部导航项：位置固定，不随各页右侧动作按钮变化而左右移动。 */
function NavLinks({ className }: { className: string }) {
  const navItems = NAV_ITEMS.filter((item) => FEATURE_FLAGS[item.key]);
  return (
    <nav className={className} aria-label="页面导航">
      {navItems.map((item) => (
        <Tooltip
          key={item.key}
          side="bottom"
          label={item.real ? item.description : `${item.description}（即将上线）`}
        >
          <NavLink
            to={item.path}
            className={({ isActive }) =>
              `rounded-full px-3.5 py-1.5 text-regular font-medium transition-colors ${
                isActive
                  ? 'bg-brand-soft text-brand-strong'
                  : 'text-muted hover:bg-surface-hover hover:text-ink'
              }`
            }
          >
            {item.label}
          </NavLink>
        </Tooltip>
      ))}
    </nav>
  );
}

/** 二级页面统一外壳：顶部导航 + 内容容器（产物/审计/设置/知识库共用）。 */
export function PageShell({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const theme = useTheme();

  return (
    /* 独立窗口里给窗口按钮让位：外壳底色顶到窗口最上沿，不留浏览器画的标题栏
       （网页态 --titlebar-h 是 0，样式与之前完全一致） */
    <div className="flex h-dvh flex-col bg-canvas" style={{ paddingTop: 'var(--titlebar-h, 0px)' }}>
      {/* 顶栏与页面同色（bg-canvas，不再铺一层 surface）：
          标题栏区、顶栏、内容区连成一片，翻页时窗口上方不会出现「亮一档的横条」。
          分隔交给下面这条 1px 描边，层级仍看得出来，但没有色块拼接的割裂感。 */}
      <header className="relative flex h-13 shrink-0 items-center gap-2.5 border-b border-line bg-canvas px-4">
        <Tooltip label="回到工作台" side="bottom">
          <Link to="/" className="flex items-center gap-2">
            <IconLogo size={21} />
            {/* 窄屏只留图标：品牌名 + 页面标题 + 右侧动作按钮在 390 下会把顶栏挤出屏幕 */}
            <span className="hidden text-regular font-semibold text-ink sm:inline">
              Office Agent
            </span>
          </Link>
        </Tooltip>
        <span className="h-4 w-px bg-line" />
        <h1 className="text-regular font-semibold text-ink">{title}</h1>

        {/* 宽屏：导航绝对居中，任何页面的动作按钮都不会把它推来推去 */}
        <NavLinks className="absolute left-1/2 hidden -translate-x-1/2 items-center gap-3.5 lg:flex" />

        <div className="ml-auto flex items-center gap-3">
          {/* 中等宽度放不下居中导航，退回行内排布 */}
          <NavLinks className="hidden items-center gap-3.5 md:flex lg:hidden" />
          <span className="hidden h-4 w-px bg-line md:block lg:hidden" />
          {/* 每个页面都能一键回工作台，不只靠左上角 logo。
              窄屏这条与 logo 重复且最占地方，收掉。 */}
          <Link
            to="/"
            className="hidden h-8 items-center gap-1 rounded-full border border-line bg-surface px-3 text-mini font-medium text-ink-soft transition-colors hover:border-line-strong hover:bg-surface-hover hover:text-ink sm:inline-flex"
          >
            <IconChevronLeft size={13} />
            返回首页
          </Link>
          <IconButton label={theme === 'dark' ? '切换到浅色' : '切换到深色'} onClick={toggleTheme}>
            {theme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
          </IconButton>
          {actions}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-y-auto">
        {/* 顶部导航两侧还有余白，内容区跟着放宽一档：1100 → 1280，产物卡片不至于挤成窄条 */}
        <div className="mx-auto w-full max-w-[1280px] px-7 py-6">
          {description ? (
            <p className="mb-4 text-body leading-relaxed text-muted">{description}</p>
          ) : null}
          {children}
        </div>
      </main>
    </div>
  );
}
