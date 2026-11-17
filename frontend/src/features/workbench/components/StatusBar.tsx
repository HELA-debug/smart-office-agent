import { friendlyEngineReason } from '../../../shared/lib/engine-reason';
import { toggleTheme, useTheme } from '../../../shared/lib/theme';
import {
  IconAlertTriangle,
  IconInfo,
  IconMoon,
  IconPanelLeft,
  IconPanelRight,
  IconRefresh,
  IconSun,
  IconX,
} from '../../../shared/ui/Icons';
import { Badge, Button, IconButton } from '../../../shared/ui/primitives';
import type { RunErrorInfo, RunMode } from '../../../shared/types/events';
import type { ConnectionState, HealthState, Notice } from '../state/workbench';

const CONNECTION: Record<ConnectionState, { label: string; className: string } | null> = {
  idle: null,
  connecting: { label: '连接中', className: 'bg-brand animate-pulse' },
  open: { label: '事件流已连接', className: 'bg-ok' },
  reconnecting: { label: '断线重连中', className: 'bg-warn animate-pulse' },
  closed: { label: '连接已关闭', className: 'bg-faint' },
};

export function StatusBar({
  health,
  mode,
  isMockMode,
  degraded,
  degradedReason,
  connection,
  runError,
  notice,
  onRetryRun,
  onRetryHealth,
  onDismissNotice,
  rightOpen,
  onToggleRightPanel,
  leftOpen,
  onToggleLeftPanel,
}: {
  health: HealthState;
  mode: RunMode | null;
  isMockMode: boolean;
  degraded: boolean;
  /** 降级原因：真实模型为什么没打通（Key / 网络 / 模型名） */
  degradedReason?: string;
  connection: ConnectionState;
  runError: RunErrorInfo | null;
  notice: Notice | null;
  onRetryRun: () => void;
  onRetryHealth: () => void;
  onDismissNotice: () => void;
  rightOpen: boolean;
  onToggleRightPanel: () => void;
  leftOpen: boolean;
  onToggleLeftPanel: () => void;
}) {
  const effectiveMode = mode ?? health.mode;
  const connectionMeta = CONNECTION[connection];
  const theme = useTheme();
  const themeLabel = theme === 'dark' ? '切换到浅色主题' : '切换到深色主题';

  return (
    <header className="shrink-0 border-b border-line bg-surface">
      {/*
        标题行：产品名 + 运行模式。
        以前这条横跨整个窗口，左栏被压到下面一截；现在它属于**对话区**，
        左栏从顶端直接开始（对齐参考软件的窗口结构）。
        右侧只放两枚图标：主题（太阳/月亮）+ 右栏开关——都是「切一下」的即时动作。
      */}
      <div className="flex h-12 items-center gap-2.5 px-3">
        <IconButton
          label={leftOpen ? '收起侧边栏' : '展开侧边栏'}
          onClick={onToggleLeftPanel}
          className="hidden md:inline-flex"
        >
          <IconPanelLeft size={16} />
        </IconButton>
        <span className="truncate text-mini font-semibold tracking-tight text-ink">
          office agent
        </span>

        {isMockMode ? (
          <Badge tone="brand" dot>
            本地 mock 事件流
          </Badge>
        ) : effectiveMode === 'mock' ? (
          // 徽标只有三个字，装不下「为什么是 mock」：原因挂在 title 上
          <Badge
            tone="warn"
            dot
            title={friendlyEngineReason(health.engineReason || degradedReason) || undefined}
          >
            mock 连接器
          </Badge>
        ) : effectiveMode === 'real' ? (
          <Badge tone="ok" dot>
            real 模型
          </Badge>
        ) : (
          <Badge tone="neutral" dot>
            模式未知
          </Badge>
        )}

        {connectionMeta ? (
          <span className="hidden items-center gap-1.5 text-caption text-muted md:inline-flex">
            <span className={`h-1.5 w-1.5 rounded-full ${connectionMeta.className}`} />
            {connectionMeta.label}
          </span>
        ) : null}

        <div className="ml-auto flex items-center gap-1">
          {/* 主题：只留一枚太阳/月亮图标，跟右栏开关同排。
              不上文字标签——标题行是「静默」的一行，图标一眼够用。 */}
          <IconButton label={themeLabel} onClick={toggleTheme}>
            {theme === 'dark' ? <IconSun size={16} /> : <IconMoon size={16} />}
          </IconButton>
          <IconButton
            label={rightOpen ? '收起右栏' : '展开右栏'}
            onClick={onToggleRightPanel}
            className={rightOpen ? 'bg-surface-sunken text-ink' : ''}
          >
            <IconPanelRight size={16} />
          </IconButton>
        </div>
      </div>

      {runError ? (
        <div className="flex min-h-8 flex-wrap items-center gap-2 border-b border-danger-line bg-danger-soft px-4 py-1 text-caption text-danger">
          <IconAlertTriangle size={13} />
          <span className="rounded-chip border border-danger-line bg-surface/60 px-1.5 py-[1px] font-mono font-medium">
            {runError.code}
          </span>
          <span className="min-w-0 flex-1 truncate">{runError.message}</span>
          {runError.retryable ? (
            <Button
              variant="secondary"
              size="sm"
              onClick={onRetryRun}
              leading={<IconRefresh size={12} />}
            >
              重试
            </Button>
          ) : null}
        </div>
      ) : null}

      {notice ? (
        <div
          className={`flex min-h-8 items-center gap-2 border-b px-4 py-1 text-caption ${
            notice.kind === 'error'
              ? 'border-danger-line bg-danger-soft text-danger'
              : 'border-brand-line bg-brand-soft text-brand-strong'
          }`}
        >
          <IconInfo size={13} />
          <span className="min-w-0 flex-1 truncate">
            {notice.text}
            {/* 成功提示不挂技术编号：只有出错时才需要这个号去查日志 */}
            {notice.kind === 'error' && notice.traceId ? (
              <span className="ml-1.5 font-mono text-faint">{notice.traceId}</span>
            ) : null}
          </span>
          <IconButton label="关闭提示" className="h-6 w-6" onClick={onDismissNotice}>
            <IconX size={12} />
          </IconButton>
        </div>
      ) : null}

      {!isMockMode && health.status === 'unreachable' ? (
        <div className="flex min-h-8 items-center gap-2 border-b border-warn-line bg-warn-soft px-4 py-1 text-caption text-warn">
          <IconAlertTriangle size={13} />
          <span className="min-w-0 flex-1 truncate">
            还没连上本地服务，暂时发不出任务。确认程序已启动后点「重试」，也可以先用演示模式看看效果。
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={onRetryHealth}
            leading={<IconRefresh size={12} />}
          >
            重试
          </Button>
        </div>
      ) : null}

      {isMockMode ? (
        // 窄屏改成上下两行：一行放说明、一行放链接。
        // 挤在一行时链接会插在折行文字的右边，把这段说明挖出一个缺口。
        <div className="flex flex-col gap-1 border-b border-brand-line bg-brand-soft px-4 py-1.5 text-caption text-brand-strong sm:min-h-7 sm:flex-row sm:items-center sm:gap-2 sm:py-1">
          <div className="flex min-w-0 items-start gap-1.5">
            <IconInfo size={12} className="mt-[3px] shrink-0" />
            <span className="min-w-0">
              当前为本地 mock 事件流（fixture）：事件格式与后端契约一致，不会产生真实外部副作用。
            </span>
          </div>
          <a
            href={window.location.pathname}
            className="shrink-0 self-start font-medium underline underline-offset-2 sm:ml-auto sm:self-auto"
          >
            切换到真实后端
          </a>
        </div>
      ) : null}

      {degraded ? (
        <div className="flex min-h-8 items-start gap-2 border-b border-warn-line bg-warn-soft px-4 py-1 text-caption text-warn">
          <IconAlertTriangle size={13} className="mt-[3px] shrink-0" />
          <span className="min-w-0">
            <b className="font-semibold">这一轮没有调用真实大模型</b>
            ：真实模型不可用，内容由本地模拟生成，不会产生任何费用。
            {degradedReason ? <> 原因：{friendlyEngineReason(degradedReason)}</> : null}
            <span className="text-warn/80">
              {' '}
              —— 去「设置 → 模型」换一把有效的 Key，点「测试连接」通过后立即切回真实模型。
            </span>
          </span>
        </div>
      ) : null}
    </header>
  );
}
