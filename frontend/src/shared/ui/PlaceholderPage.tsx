import { Link } from 'react-router-dom';
import { FEATURE_FLAGS, PLACEHOLDER_NAV } from '../config/feature-flags';
import { toggleTheme, useTheme } from '../lib/theme';
import {
  IconArrowRight,
  IconBook,
  IconChevronLeft,
  IconLogo,
  IconMoon,
  IconSparkle,
  IconSun,
} from './Icons';
import { Badge, Button, IconButton } from './primitives';
import type { PlaceholderRoute } from '../config/feature-flags';

const ICONS = {
  knowledge: IconBook,
  skills: IconSparkle,
} as const;

/**
 * 占位页（计划书 6.4）：路由已注册、入口可点、有「即将上线」空状态。
 * 知识库是独立的大规模检索模块，已拆到 features/knowledge，由 router 直接指向，
 * 不再从这里渲染——避免把它和「插件 / 技能」那套卡片商店混在一起。
 */
export function PlaceholderPage({ routeKey }: { routeKey: PlaceholderRoute }) {
  // hooks 必须在任何 early return 之前调用，否则每次渲染顺序不一致
  const theme = useTheme();
  const entry = PLACEHOLDER_NAV.find((item) => item.key === routeKey) ?? PLACEHOLDER_NAV[0];
  if (!entry) return null;

  const Icon = ICONS[entry.key as keyof typeof ICONS] ?? IconBook;
  const enabled = FEATURE_FLAGS[entry.key];

  return (
    <div className="flex h-dvh flex-col bg-canvas" style={{ paddingTop: 'var(--titlebar-h, 0px)' }}>
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-canvas px-4">
        <Link to="/" className="flex items-center gap-2">
          <IconLogo size={20} />
          <span className="text-regular font-semibold text-ink">Office Agent</span>
        </Link>
        <span className="h-4 w-px bg-line" />
        <span className="text-mini text-muted">{entry.label}</span>
        <div className="ml-auto flex items-center gap-1.5">
          <Link
            to="/"
            className="inline-flex h-8 items-center gap-1 rounded-full border border-line bg-surface px-3 text-mini font-medium text-ink-soft transition-colors hover:border-line-strong hover:bg-surface-hover hover:text-ink"
          >
            <IconChevronLeft size={13} />
            返回首页
          </Link>
          <IconButton label={theme === 'dark' ? '切换到浅色' : '切换到深色'} onClick={toggleTheme}>
            {theme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
          </IconButton>
        </div>
      </header>

      <main className="flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-[520px] rounded-card border border-line bg-surface p-8 text-center shadow-card">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-sunken text-muted">
            <Icon size={22} />
          </div>
          <div className="mt-4 flex justify-center">
            <Badge tone="brand">即将上线</Badge>
          </div>
          <h1 className="mt-3 text-title font-semibold text-ink">{entry.label}</h1>
          <p className="mt-2 text-mini text-muted">{entry.description}，将在 V1.0 提供。</p>

          {!enabled ? (
            <p className="mt-3 rounded-control border border-warn-line bg-warn-soft px-3 py-2 text-caption text-warn">
              该入口当前被 featureFlags.ts 关闭，直接访问仍可看到本页；开启开关后导航可见。
            </p>
          ) : null}

          <div className="mt-6 flex items-center justify-center gap-2">
            <Link to="/">
              <Button variant="primary" size="md" trailing={<IconArrowRight size={14} />}>
                返回首页
              </Button>
            </Link>
            <Button
              variant="ghost"
              size="md"
              onClick={() => {
                window.history.back();
              }}
            >
              返回上一页
            </Button>
          </div>

          <div className="mt-6 border-t border-line pt-3 text-caption text-faint">
            本版只交付工作台主链路；知识库已有独立检索入口，其余入口保留路由与入口。
          </div>
        </div>
      </main>
    </div>
  );
}
