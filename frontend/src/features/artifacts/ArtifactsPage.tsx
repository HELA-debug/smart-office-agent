import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { errorMessage } from '../../shared/lib/api';
import { saveRemoteFile } from '../../shared/lib/download';
import { formatBytes, formatDateTime } from '../../shared/lib/format';
import { Checkbox } from '../../shared/ui/Checkbox';
import {
  IconChevronDown,
  IconDownload,
  IconExternal,
  IconRefresh,
  IconRotate,
  IconTrash,
} from '../../shared/ui/Icons';
import { PageShell } from '../../shared/ui/PageShell';
import { Badge, Button, Card, CardEmpty, CardError, CardLoading } from '../../shared/ui/primitives';
import { Select } from '../../shared/ui/Select';
import { sessionsApi } from '../sessions';
import { ARTIFACT_TYPES, ARTIFACT_TYPE_LABELS, artifactTypeTone, artifactsApi } from './api';
import { ArtifactPreviewModal } from './components/ArtifactPreviewModal';
import type { ArtifactListQuery, TrashItem } from './api';
import type { PreviewTarget } from './components/ArtifactPreviewModal';
import type { ArtifactOut, ThreadOut } from '../../shared/api/types';
import type { ReactNode, Ref } from 'react';

type ViewKey = 'active' | 'trash';

/**
 * 产物中心：两个分类维度（文档类型 / 会话）+ 分页 + 预览 + 下载 + 回收站。
 *
 * 两个维度能叠加：选「W46 周报」+「PDF」= 那个会话产出的 PDF。
 * - **类型**回答「我要找什么格式的文件」；
 * - **会话**回答「这是哪次对话产出的」——产物本来就按会话归档（后端
 *   `artifacts.thread_id`），跨会话全铺在一屏里时，用户看到的是十几份同名的
 *   《周报.docx》，分不清哪份是哪次改的。
 *
 * 两个维度都做成**收起式的胶囊**（带小箭头，点开才浮出选项面板）：类型十来项、
 * 会话几十条，平铺成两整行会把筛选区顶成半屏，页面看着又乱又挤。收起后一行只占
 * 左侧一小块，当前选中的值写在胶囊上（「类型 PDF」），不展开也知道筛了什么。
 * 顶部「全部产物 / 回收站」这种主视图切换仍独占一整行，排在两个维度下面。
 *
 * 从工作台右栏「查看本会话全部产物」进来时，地址栏带 `?thread=<id>`：会话维度直接
 * 落在那个会话上，列表也只列它的产物。从左侧「产物中心」进来没有参数，就是全部会话。
 */
export function ArtifactsPage() {
  /**
   * 会话维度的事实来源放在地址栏：右栏入口要能深链定位、刷新不丢、也能把链接发给别人。
   * 类型维度留在组件内——它是「这一会儿想看什么格式」，换页/刷新重新选不算问题。
   */
  const [params, setParams] = useSearchParams();
  const threadId = params.get('thread') ?? '';
  const [sessions, setSessions] = useState<ThreadOut[]>([]);
  const [view, setView] = useState<ViewKey>('active');
  const [type, setType] = useState('');
  /** 哪个维度的选项面板正展开（同一时刻只开一个，两个面板叠在一起会互相挡） */
  const [menu, setMenu] = useState<'type' | 'session' | null>(null);
  const [page, setPage] = useState(1);
  // 每页限量：页面不无限拉长，超出部分经下拉选页浏览
  const pageSize = 12;

  const [artifacts, setArtifacts] = useState<ArtifactOut[]>([]);
  const [total, setTotal] = useState(0);
  const [trash, setTrash] = useState<TrashItem[]>([]);
  const [trashTotal, setTrashTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  // 选择集只覆盖「当前页」：翻页/换筛选自动清空，避免删掉看不见的项
  const [selected, setSelected] = useState<ReadonlySet<string>>(() => new Set());
  const [batchBusy, setBatchBusy] = useState(false);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);

  const clearSelection = useCallback(() => setSelected(new Set()), []);

  const toggleOne = useCallback((artifactId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(artifactId)) next.delete(artifactId);
      else next.add(artifactId);
      return next;
    });
  }, []);

  /**
   * 会话维度要的是「标题 + 该会话有几个产物」，正好是会话列表本来就带的字段
   * （`ThreadOut.artifact_count`），不用为这个维度再加接口。
   * 读失败只是少了一行分类，不该让整页报错——所以吞掉异常。
   */
  const refreshSessions = useCallback(async () => {
    try {
      const response = await sessionsApi.listThreads({ pageSize: 100 });
      setSessions(response.data.threads ?? []);
    } catch {
      // 保持上一次的列表：一次抖动就把整行分类清空，比显示旧数字更让人困惑
    }
  }, []);

  useEffect(() => {
    void refreshSessions();
  }, [refreshSessions]);

  /** 会话 chip：只留有产物的会话（空会话点进去是一片空白，纯噪音）。 */
  const sessionChips = useMemo(() => {
    const withArtifacts = sessions.filter(
      (thread) => thread.artifact_count > 0 || thread.thread_id === threadId,
    );
    return withArtifacts;
  }, [sessions, threadId]);

  /** 深链进来的会话即便不在前 100 条里，也要让用户看到自己「在哪」。 */
  const activeSession = sessionChips.find((thread) => thread.thread_id === threadId) ?? null;

  const switchType = (next: string) => {
    setType(next);
    setPage(1);
    clearSelection();
    // 选完就收：面板浮在列表上，开着会挡住刚筛出来的结果
    setMenu(null);
  };

  /**
   * 切会话：写回地址栏而不是只改 state。
   * 深链要能刷新复现、能发给别人；清成「全部对话」时把参数删掉，回到干净的 /artifacts。
   */
  const switchThread = (next: string) => {
    const search = new URLSearchParams(params);
    if (next) search.set('thread', next);
    else search.delete('thread');
    setParams(search, { replace: true });
    setPage(1);
    clearSelection();
    setMenu(null);
  };

  /**
   * 选中的会话 chip 进了视野才知道「定位成功了」：会话多的时候它可能排在横向滚动条
   * 外面，用户会以为筛选没生效。`block:'nearest'` 保证不会把页面纵向拽动。
   */
  const activeChipRef = useCallback((node: HTMLButtonElement | null) => {
    // jsdom 里没有这个方法（单测环境），别为了一个纯视觉动作把整页炸掉
    if (node && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest', inline: 'center' });
    }
  }, []);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  /** 下载：同一份文件点几次都要能落盘，所以每次都重新取 blob 再存（见 shared/lib/download）。 */
  const downloadArtifact = useCallback(async (artifactId: string, filename: string) => {
    try {
      await saveRemoteFile(artifactsApi.artifactDownloadUrl(artifactId), filename);
      setNotice(`已开始下载《${filename}》`);
    } catch (error) {
      setNotice(`下载失败：${errorMessage(error)}`);
    }
  }, []);

  const query = useMemo<ArtifactListQuery>(
    () => ({ threadId: threadId || undefined, type: type || undefined, page, pageSize }),
    [page, pageSize, threadId, type],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      // 回收站数量只是辅助信息：它读失败也不该让整个列表报错
      const [response, trashResult] = await Promise.all([
        artifactsApi.listArtifacts(query),
        Promise.resolve()
          .then(() => artifactsApi.listTrash(1, 100))
          .catch(() => null),
      ]);
      setArtifacts(response.data.artifacts);
      setTotal(response.data.total);
      setTrash(trashResult?.data.artifacts ?? []);
      setTrashTotal(trashResult?.data.total ?? 0);
      // 列表变化后剔除已不存在的选中项，避免计数虚高
      const live = new Set(response.data.artifacts.map((item) => item.artifact_id));
      setSelected((prev) => {
        if (prev.size === 0) return prev;
        const next = new Set([...prev].filter((id) => live.has(id)));
        return next.size === prev.size ? prev : next;
      });
    } catch (error) {
      setLoadError(errorMessage(error));
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  // 删除/筛选后当前页可能越界：收敛到最后一页
  useEffect(() => {
    if (total > 0 && page > Math.max(1, Math.ceil(total / pageSize))) {
      setPage(Math.max(1, Math.ceil(total / pageSize)));
    }
  }, [page, pageSize, total]);

  const activeTrashCount = trashTotal;
  const activeCount = view === 'trash' ? activeTrashCount : total;

  const selectedIds = useMemo(() => {
    // 选择集覆盖当前视图（全部产物 / 回收站）；只算当前页可见的条目，避免删掉看不见的项
    const visible =
      view === 'trash'
        ? trash.map((item) => item.artifact_id)
        : artifacts.map((item) => item.artifact_id);
    return visible.filter((id) => selected.has(id));
  }, [artifacts, selected, trash, view]);
  const currentIds =
    view === 'trash'
      ? trash.map((item) => item.artifact_id)
      : artifacts.map((item) => item.artifact_id);
  const allSelected = currentIds.length > 0 && selectedIds.length === currentIds.length;
  const partlySelected = selectedIds.length > 0 && !allSelected;

  const toggleAll = () => {
    setSelected(allSelected ? new Set() : new Set(currentIds));
  };

  const removeSelected = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`把选中的 ${selectedIds.length} 个产物移入回收站？之后可以恢复。`)) return;
    setBatchBusy(true);
    try {
      const response = await artifactsApi.deleteArtifacts(selectedIds);
      const { deleted, failed } = response.data;
      if (failed.length === 0) {
        setNotice(`已移入回收站 ${deleted} 个产物`);
      } else {
        setNotice(
          `已删除 ${deleted} 个，${failed.length} 个失败：${failed[0]?.message || '未知原因'}`,
        );
      }
      clearSelection();
      // 会话 chip 上的数字来自 artifact_count，删/恢复之后要跟着变，否则「3」永远不动
      await load();
      void refreshSessions();
    } catch (error) {
      setNotice(`批量删除失败：${errorMessage(error)}`);
    } finally {
      setBatchBusy(false);
    }
  };

  /** 回收站批量恢复：逐个调恢复接口，失败只报数，不中断其它条目。 */
  const restoreSelected = async () => {
    if (selectedIds.length === 0) return;
    setBatchBusy(true);
    try {
      const results = await Promise.allSettled(
        selectedIds.map((id) => artifactsApi.restoreArtifact(id)),
      );
      const failed = results.filter((result) => result.status === 'rejected').length;
      setNotice(
        failed === 0
          ? `已恢复 ${selectedIds.length} 个产物`
          : `已恢复 ${selectedIds.length - failed} 个，${failed} 个失败`,
      );
      clearSelection();
      // 会话 chip 上的数字来自 artifact_count，删/恢复之后要跟着变，否则「3」永远不动
      await load();
      void refreshSessions();
    } finally {
      setBatchBusy(false);
    }
  };

  /** 回收站批量彻底删除（不可恢复，二次确认）。 */
  const purgeSelected = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`彻底删除选中的 ${selectedIds.length} 个产物？删除后无法恢复。`)) return;
    setBatchBusy(true);
    try {
      const results = await Promise.allSettled(
        selectedIds.map((id) => artifactsApi.purgeArtifact(id)),
      );
      const failed = results.filter((result) => result.status === 'rejected').length;
      setNotice(
        failed === 0
          ? `已彻底删除 ${selectedIds.length} 个产物`
          : `已删除 ${selectedIds.length - failed} 个，${failed} 个失败`,
      );
      clearSelection();
      // 会话 chip 上的数字来自 artifact_count，删/恢复之后要跟着变，否则「3」永远不动
      await load();
      void refreshSessions();
    } finally {
      setBatchBusy(false);
    }
  };

  const restore = async (item: TrashItem) => {
    setBusyId(item.artifact_id);
    try {
      await artifactsApi.restoreArtifact(item.artifact_id);
      setNotice(`已恢复：${item.filename}`);
      // 会话 chip 上的数字来自 artifact_count，删/恢复之后要跟着变，否则「3」永远不动
      await load();
      void refreshSessions();
    } catch (error) {
      setNotice(`恢复失败：${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  };

  const purge = async (item: TrashItem) => {
    if (!window.confirm(`彻底删除「${item.filename}」？删除后无法恢复。`)) return;
    setBusyId(item.artifact_id);
    try {
      await artifactsApi.purgeArtifact(item.artifact_id);
      setNotice(`已彻底删除：${item.filename}`);
      // 会话 chip 上的数字来自 artifact_count，删/恢复之后要跟着变，否则「3」永远不动
      await load();
      void refreshSessions();
    } catch (error) {
      setNotice(`彻底删除失败：${errorMessage(error)}`);
    } finally {
      setBusyId(null);
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const viewTabs: { key: ViewKey; label: string; count: number }[] = [
    { key: 'active', label: '全部产物', count: total },
    { key: 'trash', label: '回收站', count: activeTrashCount },
  ];

  /** 胶囊上显示「当前筛的是什么」：收起状态也要能一眼看出筛了没 */
  const typeLabel = type ? (ARTIFACT_TYPE_LABELS[type] ?? type) : '全部类型';
  const threadLabel = threadId ? activeSession?.title || '这个会话' : '全部对话';
  const closeMenu = useCallback(() => setMenu(null), []);

  return (
    <PageShell
      title="产物中心"
      description="Agent 生成的所有产物：按文档类型和所属会话分类查看，可以预览、下载、用系统程序（WPS / Office）打开，误删了也能从回收站恢复。"
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => void load()}
          leading={<IconRefresh size={13} />}
          loading={loading}
        >
          刷新
        </Button>
      }
    >
      {notice ? (
        <div className="mb-3 rounded-control border border-brand-line bg-brand-soft px-3 py-2 text-caption text-brand-strong">
          {notice}
        </div>
      ) : null}

      <Card className="mb-5">
        {/* 两个分类维度收成胶囊：一行、只占左侧一小块，点开才浮出选项面板。
            它们能叠着用（会话 × 类型），所以是两个独立的下拉，不是二选一的开关。 */}
        {view === 'active' ? (
          <div className="flex flex-wrap items-center gap-2 px-4 py-2">
            <FilterMenu
              label="类型"
              value={typeLabel}
              active={Boolean(type)}
              open={menu === 'type'}
              onToggle={() => setMenu(menu === 'type' ? null : 'type')}
              onClose={closeMenu}
              widthRem={20}
              stacked
              visibleRows={8}
            >
              <FilterChip active={!type} onClick={() => switchType('')} full>
                全部类型
              </FilterChip>
              {ARTIFACT_TYPES.map((value) => (
                <FilterChip
                  key={value}
                  active={type === value}
                  onClick={() => switchType(value)}
                  full
                >
                  {ARTIFACT_TYPE_LABELS[value] ?? value}
                </FilterChip>
              ))}
            </FilterMenu>

            {sessionChips.length > 0 ? (
              <FilterMenu
                label="会话"
                value={threadLabel}
                active={Boolean(threadId)}
                open={menu === 'session'}
                onToggle={() => setMenu(menu === 'session' ? null : 'session')}
                onClose={closeMenu}
                widthRem={18}
                stacked
              >
                <FilterChip active={!threadId} onClick={() => switchThread('')} full>
                  全部对话
                </FilterChip>
                {sessionChips.map((thread) => {
                  const active = threadId === thread.thread_id;
                  return (
                    <FilterChip
                      key={thread.thread_id}
                      active={active}
                      onClick={() => switchThread(thread.thread_id)}
                      ref={active ? activeChipRef : undefined}
                      label={thread.title || '未命名会话'}
                      full
                    >
                      <span className="min-w-0 flex-1 truncate">
                        {thread.title || '未命名会话'}
                      </span>
                      {thread.artifact_count > 0 ? (
                        <span className="shrink-0 text-faint tabular-nums">
                          {thread.artifact_count}
                        </span>
                      ) : null}
                    </FilterChip>
                  );
                })}
              </FilterMenu>
            ) : null}
          </div>
        ) : null}

        {/* 主视图切换：全部产物 / 回收站（回收站带条数）。这一行仍独占整宽——
            它是主视图而不是细分类，位置放在两个维度下面，和改造前一样。 */}
        <div
          className={`flex flex-wrap items-center gap-2 px-4 py-2.5 ${
            view === 'active' ? 'border-t border-line' : ''
          }`}
        >
          {/* 视图切换：全部产物 / 回收站（回收站带条数） */}
          <div className="flex items-center gap-1 rounded-full border border-line bg-surface-sunken p-0.5">
            {viewTabs.map((tab) => {
              const active = view === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => {
                    // 切到回收站时筛选行整块收起（回收站按删除时间排，不筛类型/会话），
                    // 顺手把可能还开着面板关掉，免得切回来时它自己弹出来
                    setView(tab.key);
                    setMenu(null);
                  }}
                  aria-pressed={active}
                  className={`inline-flex h-7 items-center gap-1 rounded-full px-3 text-caption transition-colors ${
                    active
                      ? 'bg-surface font-medium text-ink shadow-card'
                      : 'text-muted hover:bg-surface-hover hover:text-ink'
                  }`}
                >
                  {tab.label}
                  {tab.count > 0 ? <span className="text-faint">{tab.count}</span> : null}
                </button>
              );
            })}
          </div>

          {view === 'trash' ? (
            <span className="text-caption text-faint">删除的产物会在这里保留，随时可以恢复</span>
          ) : null}

          <div className="ml-auto flex flex-wrap items-center gap-2">
            {currentIds.length > 0 ? (
              <label
                htmlFor="artifacts-select-all"
                className="flex cursor-pointer select-none items-center gap-1.5 text-caption text-muted"
              >
                <Checkbox
                  id="artifacts-select-all"
                  checked={allSelected}
                  indeterminate={partlySelected}
                  onChange={() => toggleAll()}
                  label="全选本页"
                  size="sm"
                />
                全选本页
              </label>
            ) : null}
            {selectedIds.length > 0 ? (
              <>
                <span className="text-caption font-medium text-brand-strong">
                  已选 {selectedIds.length} 项
                </span>
                {view === 'active' ? (
                  <Button
                    variant="danger"
                    size="sm"
                    loading={batchBusy}
                    onClick={() => void removeSelected()}
                    leading={<IconTrash size={13} />}
                  >
                    删除选中
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={batchBusy}
                      onClick={() => void restoreSelected()}
                      leading={<IconRotate size={13} />}
                    >
                      恢复选中
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      loading={batchBusy}
                      onClick={() => void purgeSelected()}
                      leading={<IconTrash size={13} />}
                    >
                      彻底删除
                    </Button>
                  </>
                )}
                <Button variant="ghost" size="sm" disabled={batchBusy} onClick={clearSelection}>
                  取消
                </Button>
              </>
            ) : null}
            <span className="text-caption text-faint">共 {activeCount} 个</span>
          </div>
        </div>
      </Card>

      {loading ? (
        <Card>
          <CardLoading label="正在加载产物…" rows={4} />
        </Card>
      ) : loadError ? (
        <Card>
          <CardError message={loadError} onRetry={() => void load()} />
        </Card>
      ) : view === 'trash' ? (
        trash.length === 0 ? (
          <Card>
            <CardEmpty label="回收站是空的" hint="删除产物后会先放进这里，确认不需要再彻底删除" />
          </Card>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {trash.map((item) => {
              const isSelected = selected.has(item.artifact_id);
              return (
                <Card
                  key={item.artifact_id}
                  className={`card-lift p-3.5 ${isSelected ? 'ring-1 ring-brand-line' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <Checkbox
                      checked={isSelected}
                      onChange={() => toggleOne(item.artifact_id)}
                      label={`选择 ${item.filename}`}
                      className="mt-[3px]"
                    />
                    <Badge tone={artifactTypeTone(item.type)}>
                      {ARTIFACT_TYPE_LABELS[item.type] ?? item.type}
                    </Badge>
                    <span className="ml-auto shrink-0 text-caption text-faint">
                      {formatBytes(item.size)}
                    </span>
                  </div>
                  <div className="mt-2 text-regular font-medium text-ink break-all">
                    {item.filename}
                  </div>
                  <div className="mt-1 text-caption text-faint">
                    删除于 {item.deleted_at ? formatDateTime(item.deleted_at) : '未知时间'}
                  </div>
                  <div className="mt-2.5 flex items-center gap-1.5">
                    <Button
                      variant="secondary"
                      size="sm"
                      loading={busyId === item.artifact_id}
                      onClick={() => void restore(item)}
                      leading={<IconRotate size={13} />}
                    >
                      恢复
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto text-danger"
                      loading={busyId === item.artifact_id}
                      onClick={() => void purge(item)}
                      leading={<IconTrash size={13} />}
                    >
                      彻底删除
                    </Button>
                  </div>
                </Card>
              );
            })}
          </div>
        )
      ) : artifacts.length === 0 ? (
        <Card>
          {threadId || type ? (
            <CardEmpty label="没有符合条件的产物" hint="换一个类型，或把会话切回「全部对话」看看" />
          ) : (
            <CardEmpty label="还没有产物" hint="在工作台完成一次运行后，生成的文档会出现在这里" />
          )}
        </Card>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {artifacts.map((artifact) => {
              const isSelected = selected.has(artifact.artifact_id);
              return (
                <Card
                  key={artifact.artifact_id}
                  // hover 要一眼看出来：边框变品牌色 + 阴影加深 + 轻微上浮（见 tokens.css .card-lift）
                  className={`card-lift p-3.5 ${isSelected ? 'ring-1 ring-brand-line' : ''}`}
                >
                  <div className="flex items-start gap-2">
                    <Checkbox
                      checked={isSelected}
                      onChange={() => toggleOne(artifact.artifact_id)}
                      label={`选择 ${artifact.filename}`}
                      className="mt-[3px]"
                    />
                    <Badge tone={artifactTypeTone(artifact.type)}>
                      {ARTIFACT_TYPE_LABELS[artifact.type] ?? artifact.type}
                    </Badge>
                    <span className="ml-auto shrink-0 text-caption text-faint">
                      {formatBytes(artifact.size)}
                    </span>
                  </div>
                  <div className="mt-2 text-regular font-medium text-ink break-all">
                    {artifact.filename}
                  </div>
                  <div className="mt-1 text-caption text-faint">
                    创建于 {formatDateTime(artifact.created_at)}
                  </div>
                  <div className="mt-2.5 flex items-center gap-1.5">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => void downloadArtifact(artifact.artifact_id, artifact.filename)}
                      leading={<IconDownload size={13} />}
                    >
                      下载
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setPreview(artifact)}
                      leading={<IconExternal size={13} />}
                    >
                      预览
                    </Button>
                  </div>
                </Card>
              );
            })}
          </div>

          {totalPages > 1 ? (
            <div className="mt-3 flex flex-wrap items-center justify-end gap-2 text-caption text-muted">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => {
                  setPage((value) => Math.max(1, value - 1));
                  clearSelection();
                }}
              >
                上一页
              </Button>
              <div className="flex items-center gap-1.5">
                <span className="shrink-0 text-faint">跳转</span>
                <Select
                  value={String(page)}
                  options={Array.from({ length: totalPages }, (_, index) => index + 1).map(
                    (value) => ({ value: String(value), label: `第 ${value} / ${totalPages} 页` }),
                  )}
                  onChange={(next) => {
                    setPage(Number(next));
                    clearSelection();
                  }}
                  ariaLabel="选择页码"
                  className="w-[8.5rem]"
                  minWidth={130}
                />
              </div>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => {
                  setPage((value) => Math.min(totalPages, value + 1));
                  clearSelection();
                }}
              >
                下一页
              </Button>
            </div>
          ) : null}
        </>
      )}

      {preview ? (
        <ArtifactPreviewModal artifact={preview} onClose={() => setPreview(null)} />
      ) : null}
    </PageShell>
  );
}

/**
 * 竖排面板里同时可见的行数。
 *
 * 会话会一直攒下去（几十上百条），面板要是跟着内容长高，边框迟早撑到屏幕外面去。
 * 所以高度按「整行」封顶：第 7 行开始就在面板内部滚，边框永远这么高。
 * 取整行而不是随便给个 max-height，是为了不出现「最后一行被切掉半截」——
 * 那看着像样式崩了，而不像「下面还有，可以滚」。
 */
const PANEL_VISIBLE_ROWS = 6;
/** 一行占的高度：chip 1.75rem + 行距 0.25rem */
const PANEL_ROW_STEP_REM = 2;

/** 按行数算面板的最大高度：rows 行内容 + 上下内边距（p-2），末尾减去一条行距 */
function panelMaxHeight(rows: number): string {
  return `calc(${rows * PANEL_ROW_STEP_REM}rem - 0.25rem + 1rem)`;
}

/**
 * 收起式的分类维度：一个带小箭头的胶囊，收起时只写着「类型 · PDF」这样的一行字，
 * 点开才在下方浮出选项面板。
 *
 * 为什么不平铺成一行 chip：类型十来项、会话几十条，平铺出来会把筛选区顶成半屏高，
 * 页面看着又乱又挤（而且一行放不下就只能横向滚，滚出来的还是方头方脑的滚动条）。
 * 收起后整块只占左侧一小块，选项再多也是点开才出现。
 *
 * 面板用绝对定位挂在胶囊下方、不做 portal：这张卡片就在页面顶部，不会被容器裁切；
 * 点外面或按 Esc 收起，选完选项也立刻收起——面板浮在列表上，开着会挡住刚筛出来的结果。
 */
function FilterMenu({
  label,
  value,
  active,
  open,
  onToggle,
  onClose,
  widthRem,
  stacked = false,
  visibleRows = PANEL_VISIBLE_ROWS,
  children,
}: {
  label: string;
  /** 当前选中的值，收起状态下写在胶囊上 */
  value: string;
  /** 是否筛过（筛过就一直带着品牌色，不点开也知道「现在不是全部」） */
  active: boolean;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  /** 平铺面板的宽度上限（rem）；竖排面板只把它当最大宽度用 */
  widthRem: number;
  /**
   * 竖排：一行一个选项，宽度按最长的那个走。
   *
   * 会话名长短差得远（「全部对话」四个字，旁边是「默认档验证 8」），平铺成 chip 云
   * 时短的那些凑不满一行，面板右侧会空出一大块——用户看到的就是「留那么多空白干嘛」。
   * 换成列表：每行都撑满同一列宽，数量靠右，没有长尾空白，读起来也像正常的会话菜单。
   */
  stacked?: boolean;
  /**
   * 面板最多同时露出几行，多了就在面板内滚。
   *
   * 会话会一直攒下去（几十上百条），高度必须封顶；类型是固定的几个类别，
   * 留点余量（多一种格式也不至于马上要滚），别让用户为一项「文本」去滚面板。
   */
  visibleRows?: number;
  children: ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  /** 面板下面还藏着一行以上：底部压一层渐隐，一眼看出「还能往下滚」 */
  const [moreBelow, setMoreBelow] = useState(false);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('mousedown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  /**
   * 滚动到底了就把渐隐收掉：滚到最下面还压着一层雾，
   * 用户会以为「最后一项被挡住了」，反而更慌。
   */
  useEffect(() => {
    if (!open) {
      setMoreBelow(false);
      return;
    }
    const node = panelRef.current;
    if (!node) return;
    const sync = () => {
      setMoreBelow(node.scrollHeight - node.scrollTop - node.clientHeight > 2);
    };
    sync();
    node.addEventListener('scroll', sync, { passive: true });
    // 选项是异步来的（会话列表比面板晚到）：内容变高也要重新判一次
    const watcher = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(sync);
    watcher?.observe(node);
    return () => {
      node.removeEventListener('scroll', sync);
      watcher?.disconnect();
    };
  }, [open]);

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={onToggle}
        className={`inline-flex h-8 max-w-[18rem] items-center gap-1.5 rounded-full border px-3 text-caption transition-colors ${
          open
            ? 'border-brand-line bg-brand-soft text-brand-strong'
            : active
              ? 'border-brand-line bg-surface text-ink hover:bg-brand-soft'
              : 'border-line bg-surface text-ink-soft hover:border-line-strong hover:bg-surface-hover hover:text-ink'
        }`}
      >
        <span className="shrink-0 text-faint">{label}</span>
        <span className="min-w-0 truncate font-medium">{value}</span>
        <IconChevronDown
          size={12}
          className={`shrink-0 text-muted transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open ? (
        <div className="absolute top-full left-0 z-30 mt-1.5">
          <div
            ref={panelRef}
            role="group"
            aria-label={`${label}筛选`}
            style={
              stacked
                ? {
                    maxWidth: `min(${widthRem}rem, calc(100vw - 2.5rem))`,
                    maxHeight: panelMaxHeight(visibleRows),
                  }
                : {
                    width: `${widthRem}rem`,
                    maxWidth: 'calc(100vw - 2.5rem)',
                    maxHeight: panelMaxHeight(visibleRows),
                  }
            }
            className={`overflow-x-hidden overflow-y-auto overscroll-contain rounded-card border border-line bg-surface p-2 shadow-pop ${
              // 竖排由内容定宽（fit-content）：宽度贴着最长那一行，短行也不留白
              stacked ? 'w-fit' : ''
            }`}
          >
            <div
              className={
                stacked
                  ? 'flex flex-col items-stretch gap-1'
                  : 'flex flex-wrap items-center gap-1.5'
              }
            >
              {children}
            </div>
          </div>

          {moreBelow ? (
            <div
              aria-hidden="true"
              className="pointer-events-none absolute inset-x-px bottom-px h-6 rounded-b-card bg-gradient-to-t from-surface to-transparent"
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/**
 * 分类选项。选中态用品牌色淡底 + 细边（和产物卡片上的 Badge 同一套色调），
 * 未选中保持透明边框——只换底色不动盒子尺寸，切换时选项不会左右抖。
 *
 * 一律全圆角：这是「按一下选一个」的胶囊，不是表格里的格子，带棱角会显得像输入框。
 * 也不用原生 title 提示——那个浮出来的方块提示框四角是硬的，比选项本身更扎眼。
 */
function FilterChip({
  active,
  onClick,
  label,
  full = false,
  ref,
  children,
}: {
  active: boolean;
  onClick: () => void;
  /** 名字被截断时的完整叫法（只给读屏用，不弹原生提示框） */
  label?: string;
  /** 竖排面板里撑满整行：名称在左、数量靠右，各行左右都对齐 */
  full?: boolean;
  ref?: Ref<HTMLButtonElement>;
  children: ReactNode;
}) {
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      aria-pressed={active}
      aria-label={label}
      className={`inline-flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-3 whitespace-nowrap text-caption transition-colors ${
        full ? 'w-full justify-between text-left' : ''
      } ${
        active
          ? 'border-brand-line bg-brand-soft font-medium text-brand-strong'
          : 'border-transparent bg-surface-sunken text-muted hover:bg-surface-hover hover:text-ink'
      }`}
    >
      {children}
    </button>
  );
}
