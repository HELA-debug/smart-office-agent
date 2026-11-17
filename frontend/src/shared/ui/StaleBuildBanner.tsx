import { useEffect, useState } from 'react';
import { BUILD_ID, onStaleBuild, probeBuildFreshness } from '../lib/build-info';
import { IconRefresh } from './Icons';
import type { BuildMismatch } from '../lib/build-info';
import type { ReactNode } from 'react';

/**
 * 「跑的不是仓库这份代码」提示条。
 *
 * 为什么需要它：前端产物（`frontend/dist`）和 exe 都不进版本库，`git pull` 之后不重新构建，
 * 本地跑起来就是上一版界面——底部还挂着早就删掉的身份卡、项目区没有折叠箭头。用户看到的
 * 是「样式变差了」，其实是跑的不是这份代码。只靠文档提醒靠不住，所以让界面自己比对。
 *
 * 第五十七轮补了「谁旧了」：以前只看前端与后端 sha 是否相等，于是后端是个跨了提交还在跑
 * 的老进程时，提示会反过来怪前端没重建（照着做也没用）。现在按 kind 说清是重构建还是重启。
 */

const COPY: Record<
  BuildMismatch['kind'],
  { title: string; body: (m: BuildMismatch) => ReactNode; action: 'reload' | 'recheck' }
> = {
  frontend: {
    title: '这个窗口跑的是旧版界面',
    body: (m) => (
      <>
        前端构建 <span className="font-mono">{m.frontend}</span>，仓库已经到{' '}
        <span className="font-mono">{m.live || m.backend}</span>。本地改完代码要重新
        <span className="mx-1 rounded-chip bg-surface-soft px-1 py-[1px] font-mono text-[calc(11px*var(--font-scale))] text-ink">
          npm run build
        </span>
        （跑 exe 的话还要重打包），刷新后才会换成新界面。
      </>
    ),
    action: 'reload',
  },
  backend: {
    title: '服务端进程还是旧版本',
    body: (m) => (
      <>
        代码已经到 <span className="font-mono">{m.live}</span>，但后端进程加载的是{' '}
        <span className="font-mono">{m.backend}</span>。关掉启动窗口（那个黑窗口）再双击启动器就行，
        前端不用重建。
      </>
    ),
    action: 'recheck',
  },
  both: {
    title: '前端和后端都不是这份代码',
    body: (m) => (
      <>
        前端构建 <span className="font-mono">{m.frontend}</span>、后端进程{' '}
        <span className="font-mono">{m.backend}</span>，仓库当前{' '}
        <span className="font-mono">{m.live}</span>
        。先重新
        <span className="mx-1 rounded-chip bg-surface-soft px-1 py-[1px] font-mono text-[calc(11px*var(--font-scale))] text-ink">
          npm run build
        </span>
        ，再关掉启动窗口重新启动，刷新后就是新界面。
      </>
    ),
    action: 'reload',
  },
};

export function StaleBuildBanner() {
  const [stale, setStale] = useState<BuildMismatch | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => onStaleBuild((detail) => setStale(detail)), []);

  // 首屏对一次就够：这条提示不会自己变来变去，用户切回窗口时再看一次也无害
  useEffect(() => {
    void probeBuildFreshness();
    const onVisible = () => {
      if (document.visibilityState === 'visible') void probeBuildFreshness();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => document.removeEventListener('visibilitychange', onVisible);
  }, []);

  if (!stale || dismissed) return null;

  const copy = COPY[stale.kind];

  /** 后端旧的话刷新页面没有意义：就地再问一次健康检查，对上了就自己收起来。 */
  const recheck = async () => {
    const stillStale = await probeBuildFreshness();
    if (!stillStale) setStale(null);
  };

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="stale-build-banner"
      className="rise-in fixed left-1/2 z-40 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 rounded-card border border-warn-line bg-warn-soft px-3.5 py-3 text-ink shadow-pop"
      style={{ top: 'calc(var(--titlebar-h, 0px) + 12px)' }}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-[1px] shrink-0 text-warn">
          <IconRefresh size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-body font-medium">{copy.title}</p>
          <p className="mt-1 text-caption leading-relaxed text-ink-soft">{copy.body(stale)}</p>
          <p className="mt-1 text-caption text-faint">当前构建：{BUILD_ID}</p>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            className="rounded-control border border-line bg-surface px-2 py-1 text-caption font-medium text-ink transition-colors hover:bg-surface-hover"
            onClick={() => {
              if (copy.action === 'reload') window.location.reload();
              else void recheck();
            }}
          >
            {copy.action === 'reload' ? '刷新' : '重新检查'}
          </button>
          <button
            type="button"
            aria-label="忽略旧构建提示"
            className="rounded-control px-1.5 py-1 text-caption text-faint transition-colors hover:bg-surface-hover hover:text-ink"
            onClick={() => setDismissed(true)}
          >
            忽略
          </button>
        </div>
      </div>
    </div>
  );
}
