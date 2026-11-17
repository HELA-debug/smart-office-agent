/**
 * 项目页：看一个文档文件夹里有什么，并把选中的文件带进新任务。
 *
 * 为什么要有这一页：左栏只放得下几行项目，用户要挑「这一份合同」时得有地方看全。
 * 选择结果通过路由 state 交给工作台（`/`），由它作为本次运行的项目与文件范围。
 */
import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { UPLOAD_FORMATS } from '../../shared/config/output-formats';
import { errorMessage } from '../../shared/lib/api';
import { formatBytes, timeAgo } from '../../shared/lib/format';
import {
  IconAlertTriangle,
  IconCheck,
  IconChevronLeft,
  IconFile,
  IconFolder,
  IconSearch,
} from '../../shared/ui/Icons';
import { Button, CardError, IconButton, Skeleton } from '../../shared/ui/primitives';
import { projectsApi } from './api';
import type { ProjectFile, ProjectSummary } from './types';

const TYPE_STYLE: Record<string, string> = {
  docx: 'bg-[#e8f0fe] text-[#1a56b8]',
  doc: 'bg-[#e8f0fe] text-[#1a56b8]',
  pdf: 'bg-[#fdeaea] text-[#b3261e]',
  xlsx: 'bg-[#e7f5ec] text-[#1d7a45]',
  xls: 'bg-[#e7f5ec] text-[#1d7a45]',
  csv: 'bg-[#e7f5ec] text-[#1d7a45]',
  md: 'bg-[#eef0f4] text-[#44506b]',
  txt: 'bg-[#eef0f4] text-[#44506b]',
  pptx: 'bg-[#fdf0e6] text-[#a34d10]',
};

export function ProjectPage() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<ProjectSummary | null>(null);
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<string[]>([]);
  const [revealError, setRevealError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    setStatus('loading');
    projectsApi
      .files(projectId, { signal: controller.signal })
      .then((response) => {
        if (!alive) return;
        setProject(response.data.project);
        setFiles(response.data.files);
        setStatus('ready');
      })
      .catch((cause: unknown) => {
        if (!alive || controller.signal.aborted) return;
        setError(errorMessage(cause));
        setStatus('error');
      });
    return () => {
      alive = false;
      controller.abort();
    };
  }, [projectId]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return files;
    return files.filter((file) => file.name.toLowerCase().includes(keyword));
  }, [files, query]);

  const toggle = (relPath: string) => {
    setSelected((current) =>
      current.includes(relPath)
        ? current.filter((item) => item !== relPath)
        : [...current, relPath],
    );
  };

  const start = (relPaths: string[]) => {
    navigate('/', {
      state: {
        projectId,
        projectName: project?.name ?? '',
        projectFiles: relPaths,
      },
    });
  };

  const openFolder = async () => {
    setRevealError(null);
    const result = await projectsApi
      .reveal(projectId)
      .then((response) => ({ opened: response.data.opened, error: response.data.error ?? null }))
      .catch((cause: unknown) => ({ opened: false, error: errorMessage(cause) }));
    if (!result.opened) setRevealError(result.error ?? '打不开这个文件夹');
  };

  return (
    /* 独立窗口里给窗口按钮让位：这一页自带顶栏，顶栏不能钻到 — □ ✕ 底下
       （网页态 --titlebar-h 是 0，样式与之前一致） */
    <div
      className="flex h-dvh flex-col overflow-hidden bg-canvas text-ink"
      style={{ paddingTop: 'var(--titlebar-h, 0px)' }}
    >
      <header className="flex shrink-0 items-center gap-2 border-b border-line bg-canvas px-4 py-2.5">
        <Link
          to="/"
          className="flex items-center gap-1 rounded-control px-1.5 py-1 text-caption text-muted transition-colors hover:bg-surface-hover hover:text-ink"
        >
          <IconChevronLeft size={13} />
          工作台
        </Link>
        <div className="mx-1 h-4 w-px bg-line" />
        <IconFolder size={15} className="shrink-0 text-brand" />
        <div className="min-w-0">
          <h1 className="truncate text-mini font-semibold">{project?.name ?? '项目'}</h1>
          <p className="truncate font-mono text-caption text-faint">{project?.path ?? projectId}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => void openFolder()}>
            打开文件夹
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={files.length === 0}
            onClick={() => start(selected)}
          >
            {selected.length > 0 ? `用选中的 ${selected.length} 个文件开始` : '用整个项目开始'}
          </Button>
        </div>
      </header>

      {revealError ? (
        <p className="border-b border-warn-line bg-warn-soft px-4 py-1.5 text-caption text-warn">
          {revealError}
        </p>
      ) : null}

      <div className="mx-auto flex min-h-0 w-full max-w-[62rem] flex-1 flex-col px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 min-w-0 flex-1 items-center gap-1.5 rounded-control border border-line bg-surface px-2">
            <IconSearch size={13} className="shrink-0 text-faint" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按文件名筛选"
              aria-label="按文件名筛选"
              className="min-w-0 flex-1 bg-transparent text-caption text-ink placeholder:text-faint focus:outline-none"
            />
          </div>
          <span className="shrink-0 text-caption text-faint">
            {filtered.length} / {files.length} 个文档
          </span>
          {selected.length > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setSelected([])}>
              清空选择
            </Button>
          ) : null}
        </div>

        <div className="mt-2 min-h-0 flex-1 overflow-y-auto rounded-card border border-line bg-surface">
          {status === 'loading' ? (
            <div className="space-y-2 p-3">
              {[0, 1, 2, 3].map((index) => (
                <Skeleton key={index} className="h-4 w-full" />
              ))}
            </div>
          ) : status === 'error' ? (
            <CardError message={error ?? '项目加载失败'} onRetry={() => navigate(0)} />
          ) : filtered.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <p className="text-mini font-medium text-ink">
                {files.length === 0 ? '这个文件夹里还没有文档' : '没有匹配的文件'}
              </p>
              <p className="mt-1 text-caption text-faint">
                {files.length === 0
                  ? `支持 ${UPLOAD_FORMATS.join(' / ')} 等常见文档，放进去再回来刷新即可。`
                  : '换个关键词试试。'}
              </p>
            </div>
          ) : (
            <table className="w-full border-collapse text-caption">
              <thead className="sticky top-0 z-10 bg-surface-soft text-faint">
                <tr>
                  <th className="w-9 px-2 py-1.5" aria-label="选择" />
                  <th className="px-2 py-1.5 text-left font-medium">文件名</th>
                  <th className="w-16 px-2 py-1.5 text-left font-medium">类型</th>
                  <th className="w-20 px-2 py-1.5 text-left font-medium">大小</th>
                  <th className="w-24 px-2 py-1.5 text-left font-medium">修改时间</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((file) => {
                  const checked = selected.includes(file.rel_path);
                  return (
                    <tr
                      key={file.rel_path}
                      className={`border-t border-line transition-colors ${
                        checked ? 'bg-brand-soft' : 'hover:bg-surface-hover'
                      }`}
                    >
                      <td className="px-2 py-1.5 align-middle">
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={checked}
                          aria-label={`选择 ${file.name}`}
                          onClick={() => toggle(file.rel_path)}
                          className={`grid h-4 w-4 place-items-center rounded-xs border transition-colors ${
                            checked
                              ? 'border-brand bg-brand text-white'
                              : 'border-line-strong bg-surface text-transparent hover:border-brand'
                          }`}
                        >
                          <IconCheck size={10} />
                        </button>
                      </td>
                      <td className="px-2 py-1.5">
                        <div className="flex items-center gap-1.5">
                          <IconFile size={13} className="shrink-0 text-muted" />
                          <span className="truncate font-medium text-ink">{file.name}</span>
                          {file.rel_path.includes('/') ? (
                            <span className="shrink-0 truncate text-caption text-faint">
                              {file.rel_path.split('/').slice(0, -1).join('/')}/
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="px-2 py-1.5">
                        <span
                          className={`rounded-chip px-1.5 py-px text-[calc(10px*var(--font-scale))] font-semibold uppercase ${
                            TYPE_STYLE[file.ext] ?? 'bg-surface-sunken text-muted'
                          }`}
                        >
                          {file.ext || '文件'}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 text-right tabular-nums text-muted">
                        {formatBytes(file.size)}
                      </td>
                      <td className="px-2 py-1.5 text-right text-faint">
                        {timeAgo(file.modified_at)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="mt-2 flex items-center gap-1.5 text-caption text-faint">
          <IconAlertTriangle size={11} className="shrink-0" />
          这里只读取文件名与大小；点「开始」后由 Agent 读取内容，不会改动原文件。
          {selected.length > 0 ? (
            <IconButton label="清除选择" className="ml-1 h-5 w-5" onClick={() => setSelected([])}>
              <span className="text-[calc(10px*var(--font-scale))]">×</span>
            </IconButton>
          ) : null}
        </p>
      </div>
    </div>
  );
}
