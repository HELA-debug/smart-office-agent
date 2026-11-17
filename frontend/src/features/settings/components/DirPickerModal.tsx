/**
 * 目录选择器：点着选，不用手打路径。
 *
 * 为什么不用浏览器原生的 `showDirectoryPicker()`：它只给句柄、拿不到绝对路径，
 * 而这个应用需要把绝对路径存到后端配置里。所以目录浏览走后端接口
 * （GET /storage/browse 只列子目录），这里只负责把结果画成两栏可点的列表。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { IconChevronLeft, IconFolder, IconPlus, IconRefresh } from '../../../shared/ui/Icons';
import { Button, IconButton, Modal } from '../../../shared/ui/primitives';
import { settingsApi } from '../api';
import type { BrowseOut } from '../api';

export function DirPickerModal({
  title,
  initialPath,
  onClose,
  onPick,
  note,
  confirmLabel,
}: {
  title: string;
  initialPath: string;
  onClose: () => void;
  onPick: (path: string) => void;
  /** 底部说明：不同场景（改存储位置 / 添加项目）说的话不一样。 */
  note?: string;
  confirmLabel?: string;
}) {
  const [browse, setBrowse] = useState<BrowseOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  // 连续点几层目录时，只用最后一次请求的结果，避免旧响应把界面顶回去
  const requestId = useRef(0);
  const nameInputRef = useRef<HTMLInputElement | null>(null);

  // 展开「新建文件夹」时把光标放进去，省一次点击（不用 autoFocus，避免无障碍告警）
  useEffect(() => {
    if (creating) nameInputRef.current?.focus();
  }, [creating]);

  const load = useCallback(async (path: string | null) => {
    const id = ++requestId.current;
    setLoading(true);
    try {
      const response = await settingsApi.browseDir(path);
      if (id !== requestId.current) return;
      setBrowse(response.data);
      setError(response.data.error);
    } catch {
      if (id !== requestId.current) return;
      setError('读不到这个位置，换一个文件夹试试');
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(initialPath || null);
  }, [initialPath, load]);

  const createFolder = async () => {
    const name = newName.trim();
    if (!name || !browse) return;
    setBusy(true);
    try {
      const response = await settingsApi.makeDir(browse.path, name);
      if (response.data.ok && response.data.path) {
        setCreating(false);
        setNewName('');
        await load(response.data.path);
      } else {
        setError(response.data.error ?? '新建失败');
      }
    } catch {
      setError('新建文件夹失败');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={title}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button variant="ghost" size="sm" onClick={onClose}>
            取消
          </Button>
          <Button
            variant="primary"
            size="sm"
            disabled={!browse || loading}
            onClick={() => browse && onPick(browse.path)}
          >
            {confirmLabel ?? '就选这个文件夹'}
          </Button>
        </>
      }
    >
      <div className="flex items-center gap-1">
        <IconButton
          label="上一层"
          disabled={!browse?.parent}
          onClick={() => void load(browse?.parent ?? null)}
        >
          <IconChevronLeft size={15} />
        </IconButton>
        <IconButton label="刷新" onClick={() => void load(browse?.path ?? null)}>
          <IconRefresh size={13} />
        </IconButton>
        <div className="mx-1 h-4 w-px bg-line" />
        <span className="shrink-0 text-caption text-faint">跳到</span>
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
          {(browse?.roots ?? []).map((root) => (
            <button
              key={root.path}
              type="button"
              onClick={() => void load(root.path)}
              className="shrink-0 rounded-chip px-1.5 py-0.5 text-caption text-muted transition-colors hover:bg-surface-hover hover:text-ink"
            >
              {root.name}
            </button>
          ))}
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() => setCreating((value) => !value)}
          leading={<IconPlus size={12} />}
        >
          新建文件夹
        </Button>
      </div>

      {/* 当前在哪：只看底部那行灰字太容易迷路，挪到内容上方单独一行 */}
      <div
        title={browse?.path ?? ''}
        className="mt-2 flex items-center gap-1.5 rounded-control bg-surface-sunken px-2 py-1"
      >
        <IconFolder size={12} className="shrink-0 text-muted" />
        <span className="min-w-0 truncate font-mono text-caption text-ink">
          {browse?.path ?? '正在读取…'}
        </span>
        {loading ? <span className="ml-auto shrink-0 text-caption text-faint">读取中…</span> : null}
      </div>

      {creating ? (
        <div className="mt-2 flex items-center gap-1.5">
          <input
            ref={nameInputRef}
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void createFolder();
              if (event.key === 'Escape') setCreating(false);
            }}
            aria-label="新文件夹名称"
            placeholder="新文件夹名称"
            className="h-8 min-w-0 flex-1 rounded-control border border-line bg-surface px-2 text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none"
          />
          <Button
            size="sm"
            loading={busy}
            disabled={!newName.trim()}
            onClick={() => void createFolder()}
          >
            创建
          </Button>
        </div>
      ) : null}

      {error ? (
        <p className="mt-2 rounded-control border border-warn-line bg-warn-soft px-2 py-1 text-caption text-warn">
          {error}
        </p>
      ) : null}

      <div className="mt-2 max-h-[19rem] min-h-[12rem] overflow-y-auto rounded-control border border-line bg-surface-soft p-1">
        {loading && !browse ? (
          <p className="px-2 py-3 text-caption text-faint">正在读取文件夹…</p>
        ) : browse && browse.dirs.length === 0 ? (
          <p className="px-2 py-3 text-caption text-faint">这里没有子文件夹，可以直接选它。</p>
        ) : (
          (browse?.dirs ?? []).map((dir) => (
            <button
              key={dir.path}
              type="button"
              onClick={() => void load(dir.path)}
              className="flex w-full items-center gap-2 rounded-control px-2 py-1.5 text-left text-caption text-ink-soft transition-colors hover:bg-surface hover:text-ink"
            >
              <IconFolder size={13} className="shrink-0 text-muted" />
              <span className="min-w-0 truncate">{dir.name}</span>
              <IconChevronLeft size={12} className="ml-auto shrink-0 rotate-180 text-faint" />
            </button>
          ))
        )}
      </div>

      <p className="mt-2 text-caption text-faint">
        {note ?? '只会列出文件夹，看不到里面的文件。选中之后，新文件才会存到这个位置。'}
      </p>
    </Modal>
  );
}
