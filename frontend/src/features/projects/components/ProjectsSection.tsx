/**
 * 侧栏「项目」区：把用户自己的文档文件夹挂在这里，点一下就是本次任务的项目。
 *
 * 高度分配（第五十五轮）：项目区既不能把会话列表挤没，也不能被裁掉。
 * 做法是「可折叠 + 上限随窗口走」：标题行永远在（添加按钮也就永远点得到），
 * 内容区用 grid-rows 0fr/1fr 过渡做展开收起；列表自己 `max-h:[min(9.5rem,24vh)]`
 * 内滚，项目再多也只占这么高。窗口矮于 720px 时默认收起，把高度全让给会话列表；
 * 用户手点过折叠按钮就按用户的来（记住偏好）。
 */
import { useEffect, useRef, useState } from 'react';
import { timeAgo } from '../../../shared/lib/format';
import { FloatingMenu } from '../../../shared/ui/FloatingMenu';
import {
  IconChevronDown,
  IconChevronRight,
  IconDots,
  IconFolder,
  IconPlus,
  IconTrash,
  IconX,
} from '../../../shared/ui/Icons';
import { IconButton, SectionLabel, Skeleton, Tooltip } from '../../../shared/ui/primitives';
import { DirPickerModal } from '../../settings';
import type { ProjectSummary } from '../types';

function ProjectRowMenu({
  onOpenPage,
  onReveal,
  onRename,
  onRemove,
}: {
  onOpenPage: () => void;
  onReveal: () => void;
  onRename: () => void;
  onRemove: () => void;
}) {
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLSpanElement>(null);

  const itemClass =
    'flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-caption text-ink-soft transition-colors hover:bg-surface-hover';

  return (
    <>
      <span ref={anchorRef} className="inline-flex">
        <IconButton
          label="项目操作"
          tip={!open}
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
        width={152}
        label="项目操作"
      >
        {[
          { label: '打开项目', run: onOpenPage },
          { label: '在文件夹中显示', run: onReveal },
          { label: '重命名', run: onRename },
        ].map((item) => (
          <button
            key={item.label}
            type="button"
            role="menuitem"
            className={itemClass}
            onClick={() => {
              setOpen(false);
              item.run();
            }}
          >
            {item.label}
          </button>
        ))}
        <div className="my-1 border-t border-line" />
        <button
          type="button"
          role="menuitem"
          className={`${itemClass} text-danger hover:bg-danger-soft`}
          onClick={() => {
            setOpen(false);
            onRemove();
          }}
        >
          <IconTrash size={12} />
          移除（不删文件）
        </button>
      </FloatingMenu>
    </>
  );
}

/** 窗口矮于这个高度：项目区默认收起，高度让给会话列表。 */
const RAIL_SHORT_PX = 720;
/** 手动折叠偏好：'1' 展开 / '0' 收起 / 缺省按窗口自动。 */
const PROJECTS_PREF_KEY = 'oa:rail-projects-open';

function readProjectsPref(): boolean | null {
  try {
    const raw = window.localStorage.getItem(PROJECTS_PREF_KEY);
    return raw === null ? null : raw === '1';
  } catch {
    // 隐私模式 / 禁用存储：读不到就当「没表过态」，交给窗口高度决定
    return null;
  }
}

function writeProjectsPref(open: boolean) {
  try {
    window.localStorage.setItem(PROJECTS_PREF_KEY, open ? '1' : '0');
  } catch {
    // 写不进去只影响下次的默认值，本次交互照常
  }
}

export interface ProjectsSectionProps {
  projects: ProjectSummary[];
  status: 'idle' | 'loading' | 'ready' | 'error';
  error: string | null;
  activeId: string | null;
  onSelect: (project: ProjectSummary | null) => void;
  onOpenPage: (project: ProjectSummary) => void;
  onAdd: (path: string) => Promise<ProjectSummary | null>;
  onRemove: (projectId: string) => Promise<boolean>;
  onRename: (projectId: string, name: string) => Promise<boolean>;
  onReveal: (projectId: string) => Promise<{ opened: boolean; error: string | null }>;
  onNotice: (tone: 'info' | 'error', message: string) => void;
}

export function ProjectsSection({
  projects,
  status,
  error,
  activeId,
  onSelect,
  onOpenPage,
  onAdd,
  onRemove,
  onRename,
  onReveal,
  onNotice,
}: ProjectsSectionProps) {
  const [picking, setPicking] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [confirmRemoveId, setConfirmRemoveId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /*
   * 折叠状态：`openPref === null` 表示「没表过态」，就按窗口高度自动定
   * （矮窗口收起，省下的高度给会话列表）；一旦用户点过，就永远听用户的。
   */
  const [short, setShort] = useState(
    () => typeof window !== 'undefined' && window.innerHeight < RAIL_SHORT_PX,
  );
  const [openPref, setOpenPref] = useState<boolean | null>(() => readProjectsPref());
  const open = openPref ?? !short;

  useEffect(() => {
    const onResize = () => setShort(window.innerHeight < RAIL_SHORT_PX);
    onResize();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  const toggleOpen = () => {
    const next = !open;
    setOpenPref(next);
    writeProjectsPref(next);
  };

  const submitAdd = async (path: string) => {
    setBusy(true);
    try {
      const created = await onAdd(path);
      setPicking(false);
      if (created) {
        onSelect(created);
        onNotice('info', `已添加项目「${created.name}」，本次任务会带上其中的文档`);
      }
    } catch {
      // 具体原因由 useProjects 写进 error，这里不弹第二个提示
      setPicking(false);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mt-2 shrink-0 border-t border-line pt-1.5" aria-label="项目">
      {/* 标题行常驻：折叠时「添加项目」也还点得到，功能不随折叠丢失 */}
      <div className="flex items-center justify-between gap-1 px-3">
        <button
          type="button"
          onClick={toggleOpen}
          aria-expanded={open}
          aria-controls="rail-projects-body"
          title={open ? '收起项目，把高度让给会话列表' : '展开项目'}
          className="-ml-1 flex min-w-0 items-center gap-1 rounded-chip px-1 py-1 transition-colors hover:bg-surface-hover"
        >
          <SectionLabel>
            项目
            {projects.length > 0 ? (
              <span className="ml-1 font-normal text-faint">{projects.length}</span>
            ) : null}
          </SectionLabel>
          <IconChevronDown
            size={12}
            className={`shrink-0 text-faint transition-transform duration-[var(--dur-feedback)] ease-[var(--ease-out)] ${
              open ? '' : '-rotate-90'
            }`}
          />
        </button>
        <Tooltip label="添加本地文档文件夹" side="top">
          <IconButton label="添加项目" className="h-6 w-6" onClick={() => setPicking(true)}>
            <IconPlus size={13} />
          </IconButton>
        </Tooltip>
      </div>

      {/*
       * 折叠用 grid-rows 0fr→1fr：不需要预先知道内容高度，过渡也不会跳。
       * 收起时补 aria-hidden + inert，键盘 Tab 不会跑进看不见的项目行里。
       */}
      <div
        id="rail-projects-body"
        aria-hidden={open ? undefined : true}
        inert={!open}
        className={`grid transition-[grid-template-rows] duration-[var(--dur-enter)] ease-[var(--ease-out)] ${
          open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
        }`}
      >
        <div className="min-h-0 overflow-hidden">
          {/* 列表自身上限：项目再多也只占 min(9.5rem, 24vh)，剩下的高度留给会话 */}
          <div className="mt-1 max-h-[min(9.5rem,24vh)] overflow-y-auto px-2">
            {status === 'loading' && projects.length === 0 ? (
              <div className="space-y-1.5 px-1 py-1">
                {[0, 1].map((index) => (
                  <Skeleton key={index} className="h-3 w-3/4" />
                ))}
              </div>
            ) : status === 'error' ? (
              <p className="rounded-control border border-warn-line bg-warn-soft px-2 py-1.5 text-caption text-warn">
                {error ?? '项目加载失败'}
              </p>
            ) : projects.length === 0 ? (
              <button
                type="button"
                onClick={() => setPicking(true)}
                className="flex w-full items-center gap-2 rounded-control border border-dashed border-line px-2 py-1.5 text-left text-caption text-muted transition-colors hover:border-brand-line hover:text-ink"
              >
                <IconFolder size={13} className="shrink-0" />
                <span className="min-w-0 flex-1">添加文档文件夹</span>
                <IconPlus size={12} className="shrink-0" />
              </button>
            ) : (
              <ul className="space-y-0.5 pb-1">
                {projects.map((project) => {
                  const active = project.id === activeId;
                  const renaming = renamingId === project.id;
                  const confirming = confirmRemoveId === project.id;
                  return (
                    <li key={project.id} className="group relative">
                      {renaming ? (
                        <div className="flex items-center gap-1 rounded-control border border-brand-line bg-surface px-1.5 py-1">
                          <input
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            onKeyDown={(event) => {
                              if (event.key === 'Enter') {
                                void onRename(project.id, draft).then((ok) => {
                                  if (ok) setRenamingId(null);
                                });
                              }
                              if (event.key === 'Escape') setRenamingId(null);
                            }}
                            aria-label="项目名称"
                            className="h-6 min-w-0 flex-1 rounded-control border border-line px-1.5 text-caption text-ink focus:border-brand focus:outline-none"
                          />
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
                          onClick={() => onSelect(active ? null : project)}
                          className={`flex w-full items-center gap-1.5 rounded-control px-2 py-1 pr-7 text-left transition-colors ${
                            active
                              ? 'bg-brand-soft text-brand-strong'
                              : 'text-ink-soft hover:bg-surface-hover'
                          }`}
                          title={project.missing ? '文件夹已不存在，点右侧菜单移除' : project.path}
                        >
                          <IconFolder
                            size={13}
                            className={`shrink-0 ${active ? 'text-brand' : 'text-muted'}`}
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-mini font-medium">
                              {project.name}
                            </span>
                            <span className="mt-0.5 flex items-center gap-1 text-caption text-faint">
                              {project.missing ? (
                                <span className="text-danger">文件夹不在了</span>
                              ) : (
                                <>
                                  <span>{project.file_count} 个文档</span>
                                  {project.modified_at ? (
                                    <>
                                      <span>·</span>
                                      <span>{timeAgo(project.modified_at)}</span>
                                    </>
                                  ) : null}
                                </>
                              )}
                            </span>
                          </span>
                          <IconChevronRight size={11} className="shrink-0 text-faint" />
                        </button>
                      )}

                      {renaming ? null : (
                        <div className="absolute top-1/2 right-0.5 -translate-y-1/2">
                          {confirming ? (
                            <div className="flex items-center gap-0.5 rounded-chip bg-surface/95 px-1 py-0.5 shadow-card">
                              {/* 不再写「移除？」：红色提示字把这一行撑宽，还和下面的项目名挤在一起；
                                  两个图标的安全含义交给 tooltip（确认移除项目 / 取消移除）。 */}
                              <IconButton
                                label="确认移除项目"
                                tone="danger"
                                className="h-6 w-6"
                                onClick={() => {
                                  void onRemove(project.id).then((ok) => {
                                    if (ok && project.id === activeId) onSelect(null);
                                    setConfirmRemoveId(null);
                                  });
                                }}
                              >
                                <IconTrash size={12} />
                              </IconButton>
                              <IconButton
                                label="取消移除"
                                className="h-6 w-6"
                                onClick={() => setConfirmRemoveId(null)}
                              >
                                <IconX size={12} />
                              </IconButton>
                            </div>
                          ) : (
                            <div className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                              <ProjectRowMenu
                                onOpenPage={() => onOpenPage(project)}
                                onReveal={() => {
                                  void onReveal(project.id).then((result) => {
                                    if (!result.opened) {
                                      onNotice('error', result.error ?? '打不开这个文件夹');
                                    }
                                  });
                                }}
                                onRename={() => {
                                  setRenamingId(project.id);
                                  setDraft(project.name);
                                }}
                                onRemove={() => setConfirmRemoveId(project.id)}
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
        </div>
      </div>

      {picking ? (
        <DirPickerModal
          title="添加文档文件夹"
          initialPath=""
          confirmLabel={busy ? '正在添加…' : '添加这个文件夹'}
          note="这里只把你自己的文档文件夹登记成项目，不会移动或修改里面的文件。"
          onClose={() => setPicking(false)}
          onPick={(path) => void submitAdd(path)}
        />
      ) : null}
    </section>
  );
}
