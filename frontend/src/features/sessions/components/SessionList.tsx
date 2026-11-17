import { useEffect, useMemo, useRef, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { FEATURE_FLAGS, NAV_ITEMS } from '../../../shared/config/feature-flags';
import { timeAgo } from '../../../shared/lib/format';
import { FloatingMenu } from '../../../shared/ui/FloatingMenu';
import {
  IconBook,
  IconCheck,
  IconChevronLeft,
  IconChevronRight,
  IconDots,
  IconFile,
  IconList,
  IconLogo,
  IconPanelLeft,
  IconPencil,
  IconPin,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconSettings,
  IconSparkle,
  IconTrash,
  IconX,
} from '../../../shared/ui/Icons';
import {
  Badge,
  Button,
  CardError,
  IconButton,
  Skeleton,
  Tooltip,
} from '../../../shared/ui/primitives';
import { useToast } from '../../../shared/ui/toast-context';
import { ExportMenu } from './ExportMenu';
import type { ThreadSummary } from '../../../shared/types/api';
import type { ComponentType, MouseEvent as ReactMouseEvent, ReactNode, SVGProps } from 'react';

const NAV_ICON = {
  settings: IconSettings,
  knowledge: IconBook,
  skills: IconSparkle,
  artifacts: IconFile,
  audit: IconList,
} as const;

type Glyph = ComponentType<SVGProps<SVGSVGElement> & { size?: number }>;

export interface SessionListProps {
  sessions: ThreadSummary[];
  sessionsStatus: 'idle' | 'loading' | 'ready' | 'error';
  sessionsError: string | null;
  activeThreadId: string | null;
  total: number;
  page: number;
  pageSize: number;
  /** 左栏是否收起为图标条（与右栏收起互相独立）。 */
  collapsed: boolean;
  onToggleCollapsed: () => void;
  onNew: () => void;
  onSelect: (threadId: string) => void;
  onRetry: () => void;
  onRename: (threadId: string, title: string) => void;
  onTogglePin: (threadId: string, pinned: boolean) => void;
  onDelete: (threadId: string) => void;
  onPage: (page: number) => void;
  /** 批量清理：一次删一串，返回是否成功（成功后组件退出选择模式）。 */
  onBulkDelete: (threadIds: string[]) => Promise<boolean>;
  /** 「选中全部 N 个」用：跨页把整个会话列表的 ID 取回来（分页只给了当前页）。 */
  onLoadAllIds: () => Promise<string[]>;
  /** 拖完一行后按新顺序回调（只含当前这一页看见的会话）。 */
  onReorder: (threadIds: string[]) => void;
  /** 项目区插槽：放在导航与会话列表之间，由工作台注入。 */
  projectsSlot?: ReactNode;
}

/** 会话条目操作菜单（⋮）：置顶 / 重命名 / 复制标题 / 删除，portal 浮层，点面板外自动收起。 */
function SessionRowMenu({
  title,
  pinned,
  onTogglePin,
  onRename,
  onDelete,
}: {
  title: string;
  pinned: boolean;
  onTogglePin: () => void;
  onRename: () => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const toast = useToast();

  // 复制以前是静默的：点了根本不知道成没成（浏览器还可能直接拒掉剪贴板权限）
  const copyTitle = async () => {
    try {
      await navigator.clipboard.writeText(title);
      toast.show('已复制会话标题', { tone: 'ok' });
    } catch {
      toast.show('复制失败：浏览器拒绝了剪贴板权限', { tone: 'warn' });
    }
  };

  const itemClass =
    'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-caption text-ink-soft transition-colors hover:bg-surface-hover';
  const shortcutClass = 'ml-auto shrink-0 font-mono text-[calc(10px*var(--font-scale))] text-faint';

  return (
    <>
      <span ref={anchorRef} className="inline-flex">
        <IconButton
          label="更多操作"
          // 同上：气泡会盖住上一行，这一行里不放悬浮提示
          tip={false}
          aria-expanded={open}
          className={`h-6 w-6 ${open ? 'bg-surface-sunken text-ink' : ''}`}
          onClick={() => setOpen((value) => !value)}
        >
          <IconDots size={13} />
        </IconButton>
      </span>
      <FloatingMenu
        open={open}
        onClose={() => setOpen(false)}
        anchorRef={anchorRef}
        width={168}
        label="会话操作"
      >
        <button
          type="button"
          role="menuitem"
          className={itemClass}
          onClick={() => {
            setOpen(false);
            onTogglePin();
          }}
        >
          <IconPin size={12} className={pinned ? 'text-warn' : 'text-muted'} />
          {pinned ? '取消置顶' : '置顶'}
          <span className={shortcutClass}>Ctrl+Shift+P</span>
        </button>
        <button
          type="button"
          role="menuitem"
          className={itemClass}
          onClick={() => {
            setOpen(false);
            onRename();
          }}
        >
          <IconPencil size={12} className="text-muted" />
          重命名
          <span className={shortcutClass}>Ctrl+Shift+R</span>
        </button>
        <button
          type="button"
          role="menuitem"
          className={itemClass}
          onClick={() => {
            setOpen(false);
            void copyTitle();
          }}
        >
          <IconFile size={12} className="text-muted" />
          复制标题
        </button>
        <div className="my-1 border-t border-line" />
        <button
          type="button"
          role="menuitem"
          className={`${itemClass} text-danger hover:bg-danger-soft`}
          onClick={() => {
            setOpen(false);
            onDelete();
          }}
        >
          <IconTrash size={12} />
          删除
        </button>
      </FloatingMenu>
    </>
  );
}

type FlyoutPayload = { label: string; hint?: string; x: number; y: number } | null;

/** 收起态左侧图标条：悬停浮出名称（参照桌面端侧栏的浮现标签）。 */
function RailItem({
  icon: Icon,
  label,
  hint,
  active,
  to,
  onHover,
  onClick,
}: {
  icon: Glyph;
  label: string;
  hint?: string;
  active?: boolean;
  /** 有 to 时渲染路由链接，否则渲染普通按钮。 */
  to?: string;
  onHover: (payload: FlyoutPayload) => void;
  onClick?: () => void;
}) {
  const itemClass = (isActive: boolean) =>
    `flex h-9 w-9 items-center justify-center rounded-control transition-colors ${
      isActive || active
        ? 'bg-surface-hover text-ink'
        : 'text-muted hover:bg-surface-hover hover:text-ink'
    }`;

  const onEnter = (event: ReactMouseEvent<HTMLDivElement>) => {
    // 视口坐标 + fixed：外层容器是 overflow-hidden（宽度动画），绝对定位浮层会被裁掉
    const rect = event.currentTarget.getBoundingClientRect();
    onHover({ label, hint, x: rect.right + 8, y: rect.top + rect.height / 2 });
  };

  return (
    <div
      className="relative flex justify-center"
      onMouseEnter={onEnter}
      onMouseLeave={() => onHover(null)}
    >
      {to ? (
        <NavLink to={to} aria-label={label} className={({ isActive }) => itemClass(isActive)}>
          <Icon size={17} />
        </NavLink>
      ) : (
        <button type="button" aria-label={label} onClick={onClick} className={itemClass(false)}>
          <Icon size={17} />
        </button>
      )}
    </div>
  );
}

export function SessionList({
  sessions,
  sessionsStatus,
  sessionsError,
  activeThreadId,
  total,
  page,
  pageSize,
  collapsed,
  onToggleCollapsed,
  onNew,
  onSelect,
  onRetry,
  onRename,
  onTogglePin,
  onDelete,
  onPage,
  onBulkDelete,
  onLoadAllIds,
  onReorder,
  projectsSlot,
}: SessionListProps) {
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  /** 批量清理模式：勾选 + 一次删一串。选中集合跨页保留（翻页不丢），这才叫「整个清理」。 */
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [confirmBulk, setConfirmBulk] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  /** 会话搜索：只过滤标题，条数一多（26+）靠翻页找太慢 */
  const [query, setQuery] = useState('');
  const [flyout, setFlyout] = useState<FlyoutPayload>(null);
  /** 拖动排序：正在拖的会话 + 松手会落在哪一行的哪一侧 */
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropAt, setDropAt] = useState<{ id: string; edge: 'before' | 'after' } | null>(null);

  const keyword = query.trim().toLowerCase();
  const visibleSessions = useMemo(
    () =>
      keyword
        ? sessions.filter((session) =>
            (session.title || '未命名会话').toLowerCase().includes(keyword),
          )
        : sessions,
    [sessions, keyword],
  );

  const pageCount = Math.max(1, Math.ceil(total / Math.max(1, pageSize)));
  const activeSession = sessions.find((session) => session.thread_id === activeThreadId);
  const allPageSelected =
    sessions.length > 0 && sessions.every((item) => selected.has(item.thread_id));

  const startSelecting = () => {
    setConfirmDeleteId(null);
    setRenamingId(null);
    setSelected(new Set());
    setConfirmBulk(false);
    setSelecting(true);
  };

  const exitSelecting = () => {
    setSelecting(false);
    setSelected(new Set());
    setConfirmBulk(false);
  };

  const toggleSelected = (threadId: string) => {
    setConfirmBulk(false);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(threadId)) next.delete(threadId);
      else next.add(threadId);
      return next;
    });
  };

  /** 全选/取消本页：跨页选中是刻意的，翻页再点一次就是「整页 4 页都选上」。 */
  const togglePageSelection = () => {
    setConfirmBulk(false);
    setSelected((prev) => {
      const next = new Set(prev);
      for (const item of sessions) {
        if (allPageSelected) next.delete(item.thread_id);
        else next.add(item.thread_id);
      }
      return next;
    });
  };

  /** 选中全部（跨页）：分页只给了当前页，这里让上层把整份列表的 ID 捞回来。 */
  const selectEverywhere = async () => {
    setConfirmBulk(false);
    const ids = await onLoadAllIds();
    setSelected(new Set(ids));
  };

  /**
   * 批量删除：第一次点只把按钮变成「确认删除 N 个」，第二次才真删。
   * 批量是不可撤销的（软删虽然能捞回，但界面没有回收站），所以必须留一步。
   */
  const runBulkDelete = async () => {
    if (selected.size === 0 || bulkBusy) return;
    if (!confirmBulk) {
      setConfirmBulk(true);
      return;
    }
    setBulkBusy(true);
    const ok = await onBulkDelete([...selected]);
    setBulkBusy(false);
    setConfirmBulk(false);
    if (ok) {
      setSelecting(false);
      setSelected(new Set());
    }
  };

  // 选择模式下 Esc 退出（此时 Ctrl+D 不再删当前会话，否则「删的」和「选的」对不上）
  useEffect(() => {
    if (!selecting) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setSelecting(false);
      setSelected(new Set());
      setConfirmBulk(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [selecting]);

  /**
   * 会话快捷键（只有置顶/重命名在菜单里标了，删除不标——见下）：
   * Ctrl+Shift+P 置顶 / Ctrl+Shift+R 重命名 / Ctrl+D 直接删除。
   * 焦点在输入框里时一律不拦，否则会抢掉用户打字时的按键。
   */
  useEffect(() => {
    if (!activeSession || selecting) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (!event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      const tag = target?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || target?.isContentEditable) return;

      const key = event.key.toLowerCase();
      if (event.shiftKey && key === 'p') {
        event.preventDefault();
        onTogglePin(activeSession.thread_id, !activeSession.pinned);
        return;
      }
      if (event.shiftKey && key === 'r') {
        event.preventDefault();
        setRenamingId(activeSession.thread_id);
        setRenameDraft(activeSession.title);
        return;
      }
      if (!event.shiftKey && key === 'd') {
        event.preventDefault();
        setConfirmDeleteId(null);
        onDelete(activeSession.thread_id);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [activeSession, onTogglePin, onDelete, selecting]);

  /**
   * 拖完落位：把被拖的那条从当前顺序里摘出来，插到落点行的前面/后面。
   *
   * 只回传「当前这一页看得见的会话」的新顺序，整份顺序由工作台补齐——
   * 左栏是分页的，前端这里只知道眼前这几条。
   */
  const commitDrop = () => {
    if (!dragId || !dropAt) return;
    const ids = visibleSessions.map((item) => item.thread_id).filter((id) => id !== dragId);
    const target = ids.indexOf(dropAt.id);
    if (target < 0) {
      setDragId(null);
      setDropAt(null);
      return;
    }
    ids.splice(dropAt.edge === 'before' ? target : target + 1, 0, dragId);
    setDragId(null);
    setDropAt(null);
    onReorder(ids);
  };

  const navItems = NAV_ITEMS.filter((item) => FEATURE_FLAGS[item.key]);

  const submitRename = (threadId: string) => {
    const title = renameDraft.trim();
    if (title) onRename(threadId, title);
    setRenamingId(null);
  };

  /* ---------------------------------------------------------------- 收起态 */
  if (collapsed) {
    return (
      <aside className="window-inset-top relative flex h-full w-[3.25rem] shrink-0 flex-col items-center gap-1 overflow-visible rounded-panel border border-line bg-surface pt-2 pb-2 shadow-panel">
        <div className="mb-1 flex h-8 w-8 items-center justify-center">
          <IconLogo size={19} />
        </div>

        <RailItem icon={IconPlus} label="新建会话" onHover={setFlyout} onClick={onNew} />
        <RailItem
          icon={IconPanelLeft}
          label="展开侧边栏"
          onHover={setFlyout}
          onClick={onToggleCollapsed}
        />

        <div className="my-1 h-px w-6 bg-line" />

        {navItems.map((item) => (
          <RailItem
            key={item.key}
            icon={NAV_ICON[item.key]}
            label={item.label}
            hint={item.real ? item.description : '即将上线'}
            to={item.path}
            onHover={setFlyout}
          />
        ))}

        {/* 收起态只留导航图标：会话条目一进来就是一列认不出的文件图标，还会把
            52px 的窄条拖出一条滚动条（第五十七轮）。会话列表只在展开态渲染，
            收起/展开的切换交给外层宽度动画，这里不留占位、不留空块。 */}

        {flyout ? (
          <div
            className="pointer-events-none fixed z-50 -translate-y-1/2 rounded-control border border-line bg-surface px-2.5 py-1.5 shadow-pop"
            style={{ left: flyout.x, top: flyout.y }}
          >
            <div className="max-w-[15rem] truncate text-mini font-medium text-ink">
              {flyout.label}
            </div>
            {flyout.hint ? (
              <div className="max-w-[15rem] truncate text-caption text-faint">{flyout.hint}</div>
            ) : null}
          </div>
        ) : null}
      </aside>
    );
  }

  /* ---------------------------------------------------------------- 展开态 */
  /*
   * 展开态的高度分配（第五十五轮）：
   * 品牌 / 新建 / 搜索 / 导航是固定块；项目区可折叠、列表自身有上限；会话列
   * `flex-1 min-h-[7rem]` 吃掉所有剩余高度并独立滚动。aside 用 `overflow-y-auto`
   * 兜底——真到了窗口矮到放不下 7rem 会话区的地步，整栏滚动而不是把列表裁掉。
   */
  return (
    <aside className="window-inset-top flex h-full w-rail shrink-0 flex-col overflow-x-hidden overflow-y-auto rounded-panel border border-line bg-surface shadow-panel">
      {/* 品牌区：名称 + 版本 + 收起 */}
      <div className="flex items-start gap-2 px-3 pt-2.5 pb-2">
        <IconLogo size={20} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-mini leading-tight font-semibold text-ink">
            Office Agent
          </div>
          <div className="mt-0.5 text-[calc(10px*0.9*var(--font-scale))] leading-tight text-faint">
            V0.2.0 · 本地
          </div>
        </div>
        <Tooltip label="收起侧边栏" side="bottom">
          <IconButton label="收起侧边栏" className="h-6 w-6" onClick={onToggleCollapsed}>
            <IconPanelLeft size={14} />
          </IconButton>
        </Tooltip>
      </div>

      {/* 新建 + 搜索 */}
      <div className="px-2">
        <button
          type="button"
          onClick={onNew}
          className="flex h-9 w-full items-center gap-2.5 rounded-control px-2.5 text-left text-mini font-semibold text-ink transition-colors hover:bg-surface-hover"
        >
          <span className="flex h-5 w-5 items-center justify-center rounded-full border border-line-strong text-ink-soft">
            <IconPlus size={12} />
          </span>
          新建会话
        </button>

        <label className="mt-0.5 flex h-8 items-center gap-1.5 rounded-control bg-surface-soft px-2 focus-within:bg-surface-sunken">
          <IconSearch size={13} className="shrink-0 text-faint" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索会话"
            aria-label="搜索会话"
            className="min-w-0 flex-1 bg-transparent text-caption text-ink placeholder:text-faint focus:outline-none"
          />
          {query ? (
            <button
              type="button"
              aria-label="清空搜索"
              onClick={() => setQuery('')}
              className="shrink-0 rounded-chip p-0.5 text-faint transition-colors hover:text-ink"
            >
              <IconX size={10} />
            </button>
          ) : null}
        </label>
      </div>

      {/* 导航：图标 + 文字行 */}
      <nav className="mt-1 px-2" aria-label="功能导航">
        {navItems.map((item) => {
          const Icon = NAV_ICON[item.key];
          return (
            <NavLink
              key={item.key}
              to={item.path}
              className={({ isActive }) =>
                `flex h-8 items-center gap-2.5 rounded-control px-2.5 text-mini font-medium transition-colors ${
                  isActive
                    ? 'bg-surface-hover text-ink'
                    : item.real
                      ? 'text-ink-soft hover:bg-surface-hover hover:text-ink'
                      : 'text-faint hover:bg-surface-hover'
                }`
              }
            >
              <Icon size={16} className="shrink-0" />
              <span className="truncate">{item.label}</span>
              {!item.real ? (
                <span className="ml-auto shrink-0 text-[calc(10px*0.9*var(--font-scale))] text-faint">
                  即将上线
                </span>
              ) : null}
            </NavLink>
          );
        })}
      </nav>

      {projectsSlot}

      {/* 会话列表：唯一一块弹性的区域，剩余高度全归它，自己滚 */}
      <div className="mt-2 flex min-h-[7rem] flex-1 flex-col">
        <div className="flex items-center justify-between px-3 pb-1">
          {selecting ? (
            <span className="text-caption font-medium text-faint">
              已选 <span className="text-ink">{selected.size}</span> / 本页 {sessions.length}
            </span>
          ) : (
            <span className="text-caption font-medium text-faint">
              会话{total > 0 ? <span className="ml-1">{total}</span> : null}
            </span>
          )}
          <div className="flex items-center gap-0.5">
            {selecting ? (
              <IconButton label="退出批量清理" className="h-6 w-6" onClick={exitSelecting}>
                <IconX size={12} />
              </IconButton>
            ) : (
              <>
                <IconButton
                  label="批量清理会话"
                  className="h-6 w-6"
                  onClick={startSelecting}
                  disabled={total === 0}
                >
                  <IconTrash size={12} />
                </IconButton>
                <IconButton label="刷新会话列表" className="h-6 w-6" onClick={onRetry}>
                  <IconRefresh size={12} />
                </IconButton>
              </>
            )}
          </div>
        </div>

        {/* 列表一直铺到面板底部：底部身份卡已删掉，这段高度全部留给会话行 */}
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2" data-testid="session-list">
          {sessionsStatus === 'loading' && sessions.length === 0 ? (
            <div className="space-y-2 px-1 py-1">
              {[0, 1, 2].map((index) => (
                <div key={index} className="space-y-1">
                  <Skeleton className="h-3 w-4/5" />
                  <Skeleton className="h-2.5 w-2/5" />
                </div>
              ))}
            </div>
          ) : sessionsStatus === 'error' ? (
            <CardError message={sessionsError ?? '会话加载失败'} onRetry={onRetry} />
          ) : sessions.length === 0 ? (
            <div className="px-2 py-6 text-center text-caption text-faint">
              还没有会话，发送第一条任务即可创建
            </div>
          ) : visibleSessions.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <div className="text-caption text-faint">没有匹配的会话</div>
              <button
                type="button"
                onClick={() => setQuery('')}
                className="mt-1 text-caption text-brand underline underline-offset-2"
              >
                清空搜索
              </button>
            </div>
          ) : (
            <ul className="space-y-0.5">
              {visibleSessions.map((session) => {
                const active = session.thread_id === activeThreadId;
                const renaming = renamingId === session.thread_id;
                const confirming = confirmDeleteId === session.thread_id;
                const checked = selected.has(session.thread_id);
                // 置顶的是另一组，拖了也会被排回去；批量清理/重命名时整行是别的作用。
                const canDrag = !selecting && !renaming && !keyword && !session.pinned;
                const dragging = dragId === session.thread_id;
                const dropEdge = dropAt?.id === session.thread_id ? dropAt.edge : null;
                return (
                  <li
                    key={session.thread_id}
                    draggable={canDrag}
                    onDragStart={(event) => {
                      // draggable=false 时浏览器本来就不会派发 dragstart；
                      // 这里再挡一道，免得测试环境/合成事件把置顶的拖起来
                      if (!canDrag) {
                        event.preventDefault();
                        return;
                      }
                      setDragId(session.thread_id);
                      setConfirmDeleteId(null);
                      event.dataTransfer.effectAllowed = 'move';
                      event.dataTransfer.setData('text/plain', session.thread_id);
                    }}
                    onDragEnd={() => {
                      setDragId(null);
                      setDropAt(null);
                    }}
                    onDragOver={(event) => {
                      if (!dragId || dragId === session.thread_id || session.pinned) return;
                      event.preventDefault();
                      event.dataTransfer.dropEffect = 'move';
                      // 落点看指针在行的上半还是下半：上半插到它前面，下半插到它后面
                      const rect = event.currentTarget.getBoundingClientRect();
                      const edge = event.clientY < rect.top + rect.height / 2 ? 'before' : 'after';
                      setDropAt((prev) =>
                        prev?.id === session.thread_id && prev.edge === edge
                          ? prev
                          : { id: session.thread_id, edge },
                      );
                    }}
                    onDragLeave={(event) => {
                      // 从行里移到子元素上不算离开：只在真正离开这一行时收起指示线
                      if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
                      setDropAt((prev) => (prev?.id === session.thread_id ? null : prev));
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      commitDrop();
                    }}
                    className={`group relative ${dragging ? 'opacity-40' : ''}`}
                  >
                    {/* 落点指示：一道 2px 的品牌色横线，压在行与行之间 */}
                    {dropEdge ? (
                      <span
                        aria-hidden
                        className={`pointer-events-none absolute inset-x-1 z-10 h-0.5 rounded-full bg-brand ${
                          dropEdge === 'before' ? '-top-px' : '-bottom-px'
                        }`}
                      />
                    ) : null}
                    {renaming ? (
                      <div className="flex items-center gap-1 rounded-control bg-surface-soft px-1.5 py-1">
                        <input
                          value={renameDraft}
                          onChange={(event) => setRenameDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') submitRename(session.thread_id);
                            if (event.key === 'Escape') setRenamingId(null);
                          }}
                          aria-label="会话标题"
                          className="h-6 min-w-0 flex-1 rounded-control border border-line bg-surface px-1.5 text-caption text-ink focus:border-brand focus:outline-none"
                        />
                        <IconButton
                          label="保存标题"
                          className="h-6 w-6 text-ok"
                          onClick={() => submitRename(session.thread_id)}
                        >
                          <IconCheck size={12} />
                        </IconButton>
                        <IconButton
                          label="取消重命名"
                          className="h-6 w-6"
                          onClick={() => setRenamingId(null)}
                        >
                          <IconX size={12} />
                        </IconButton>
                      </div>
                    ) : (
                      <button
                        type="button"
                        // 选择模式下整行就是复选框（可勾可选、键盘可操作），不再承担「切会话」
                        role={selecting ? 'checkbox' : undefined}
                        aria-checked={selecting ? checked : undefined}
                        onClick={() =>
                          selecting
                            ? toggleSelected(session.thread_id)
                            : onSelect(session.thread_id)
                        }
                        className={`flex h-8 w-full items-center gap-1.5 rounded-control px-2.5 text-left transition-colors ${
                          selecting
                            ? checked
                              ? 'bg-brand-soft text-brand-strong'
                              : 'hover:bg-surface-hover'
                            : active
                              ? 'bg-surface-hover'
                              : 'hover:bg-surface-hover'
                        }`}
                      >
                        {selecting ? (
                          <span
                            aria-hidden
                            className={`grid h-3.5 w-3.5 shrink-0 place-items-center rounded-xs border transition-colors ${
                              checked
                                ? 'border-brand-border bg-brand-solid text-white'
                                : 'border-line-strong bg-surface'
                            }`}
                          >
                            {checked ? <IconCheck size={9} /> : null}
                          </span>
                        ) : null}
                        {session.pinned ? (
                          <IconPin size={11} className="shrink-0 text-warn" />
                        ) : null}
                        <span
                          className={`min-w-0 flex-1 truncate text-mini ${
                            active ? 'font-semibold text-ink' : 'text-ink-soft group-hover:text-ink'
                          }`}
                        >
                          {session.title || '未命名会话'}
                        </span>
                        {/* 右侧「产物数 + 时间」与 hover 时的操作条占同一个位置：
                            这里淡出而不是隐藏（hidden 会把自己的宽度让出去，标题就伸到
                            操作条底下，看着像字被按钮压住）。min-w 兜住操作条那 60px，
                            只有一行时也不会露出来。 */}
                        <span className="flex min-w-[3.75rem] shrink-0 items-center justify-end gap-1.5 transition-opacity group-hover:opacity-0 group-has-[:focus-visible]:opacity-0">
                          {session.artifact_count && !selecting ? (
                            <Badge tone="neutral">{session.artifact_count} 产物</Badge>
                          ) : null}
                          {!selecting ? (
                            <span className="shrink-0 text-caption text-faint">
                              {timeAgo(session.updated_at)}
                            </span>
                          ) : null}
                        </span>
                      </button>
                    )}

                    {renaming || selecting ? null : (
                      <div className="absolute top-1/2 right-1 -translate-y-1/2">
                        {confirming ? (
                          <div className="flex items-center gap-0.5 rounded-chip border border-line bg-surface px-1 py-0.5 shadow-card">
                            <IconButton
                              label="确认删除会话"
                              tone="danger"
                              className="h-5 w-5"
                              onClick={() => {
                                onDelete(session.thread_id);
                                setConfirmDeleteId(null);
                              }}
                            >
                              <IconCheck size={11} />
                            </IconButton>
                            <IconButton
                              label="取消删除"
                              className="h-5 w-5"
                              onClick={() => setConfirmDeleteId(null)}
                            >
                              <IconX size={11} />
                            </IconButton>
                          </div>
                        ) : (
                          // 操作条只在「指针压在这一行」或「菜单真开着」时出现。
                          // 以前用的是 focus-within：鼠标点完再移走，按钮还带着焦点，
                          // 操作条就一直挂在那儿（看着像 hover 效果消失了不了）。
                          <div className="flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 has-[button[aria-expanded=true]]:opacity-100 has-[button:focus-visible]:opacity-100">
                            {/* 导出与 ⋮ 并排：导出是「拿走一份」，⋮ 是「改这个会话」 */}
                            <ExportMenu session={session} />
                            <SessionRowMenu
                              title={session.title}
                              pinned={Boolean(session.pinned)}
                              onTogglePin={() => onTogglePin(session.thread_id, !session.pinned)}
                              onRename={() => {
                                setRenamingId(session.thread_id);
                                setRenameDraft(session.title);
                                setConfirmDeleteId(null);
                              }}
                              onDelete={() => setConfirmDeleteId(session.thread_id)}
                            />
                          </div>
                        )}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        {selecting ? (
          <div className="shrink-0 border-t border-line px-2 py-1.5">
            <Button
              variant="danger"
              size="sm"
              className={`w-full ${confirmBulk ? 'ring-2 ring-danger-line' : ''}`}
              disabled={selected.size === 0 || bulkBusy}
              loading={bulkBusy}
              leading={bulkBusy ? undefined : <IconTrash size={12} />}
              onClick={() => void runBulkDelete()}
            >
              {confirmBulk ? `确认删除 ${selected.size} 个` : `删除选中（${selected.size}）`}
            </Button>
            <div className="mt-1 flex items-center justify-between text-caption text-faint">
              <button
                type="button"
                className="rounded-chip px-1 py-0.5 transition-colors hover:bg-surface-hover hover:text-ink"
                onClick={togglePageSelection}
              >
                {allPageSelected ? '取消本页' : '全选本页'}
              </button>
              {total > sessions.length ? (
                <button
                  type="button"
                  className="rounded-chip px-1 py-0.5 transition-colors hover:bg-surface-hover hover:text-ink"
                  onClick={() => void selectEverywhere()}
                >
                  选中全部 {total} 个
                </button>
              ) : (
                <span>Esc 退出</span>
              )}
            </div>
          </div>
        ) : null}

        {pageCount > 1 ? (
          <div className="flex shrink-0 items-center justify-between px-2 py-1 text-caption text-faint">
            <IconButton
              label="上一页"
              className="h-6 w-6"
              disabled={page <= 1}
              onClick={() => onPage(Math.max(1, page - 1))}
            >
              <IconChevronLeft size={12} />
            </IconButton>
            <span>
              第 {page}/{pageCount} 页 · {total} 个
            </span>
            <IconButton
              label="下一页"
              className="h-6 w-6"
              disabled={page >= pageCount}
              onClick={() => onPage(Math.min(pageCount, page + 1))}
            >
              <IconChevronRight size={12} />
            </IconButton>
          </div>
        ) : null}
      </div>
    </aside>
  );
}
