/**
 * 输入框「+」菜单里的技能面板（第六十轮：技能不再是工具栏上的独立胶囊）。
 *
 * 为什么收进来：输入框工具栏上原来并排放着「+ / 审批 / 技能」三个入口，
 * 技能和「加文件、改产物格式」是同一类事——都是给这一轮补输入条件，
 * 却单独占了一个常驻位置，还让右侧的模型区被挤窄。现在它作为加号菜单里的
 * 一个二级面板，和「产物格式」共用同一套「悬停展开、选完即收」的交互。
 *
 * 面板本身不带边框/圆角：外层由菜单统一提供卡片外壳，避免双层描边。
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Checkbox } from '../../../shared/ui/Checkbox';
import {
  IconChevronRight,
  IconPlus,
  IconSparkle,
  IconSpinner,
  IconX,
} from '../../../shared/ui/Icons';
import { IconButton } from '../../../shared/ui/primitives';
import type { SkillItem } from '../api';

export interface SkillsPanelProps {
  items: SkillItem[];
  status: 'loading' | 'ready' | 'error';
  promptChars: number;
  busyName: string | null;
  notice: string | null;
  onToggle: (name: string, enabled: boolean) => void;
  onRemove: (name: string) => void;
  /** 打开「导入技能」引导（文件选择在引导里做，不在这个面板里） */
  onImportGuide: () => void;
  /** 点「管理」跳转前收起菜单（不传也能跳，菜单随页面卸载） */
  onNavigate?: () => void;
  disabled?: boolean;
}

export function SkillsPanel({
  items,
  status,
  promptChars,
  busyName,
  notice,
  onToggle,
  onRemove,
  onImportGuide,
  onNavigate,
  disabled = false,
}: SkillsPanelProps) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const enabled = items.filter((item) => item.enabled).length;
  const importing = busyName === '__import__';

  return (
    <div className="w-[22rem] max-w-[calc(100vw-4rem)]">
      <header className="flex items-center gap-1.5 px-3 py-2 pb-1.5">
        <IconSparkle size={13} className="shrink-0 text-brand" />
        <span className="text-caption font-semibold text-ink">技能</span>
        {status === 'ready' ? (
          <span className="min-w-0 truncate text-caption text-muted">
            {enabled}/{items.length} 启用 · 提示词 {promptChars} 字
          </span>
        ) : null}
        <Link
          to="/skills"
          onClick={onNavigate}
          className="ml-auto flex shrink-0 items-center gap-0.5 rounded-chip px-1.5 py-0.5 text-caption text-muted transition-colors hover:bg-surface-hover hover:text-ink"
        >
          管理
          <IconChevronRight size={11} />
        </Link>
      </header>

      <div className="max-h-[14rem] overflow-y-auto overscroll-contain border-t border-line">
        {status === 'loading' ? (
          <p className="px-3 py-6 text-center text-caption text-muted">正在读取技能…</p>
        ) : status === 'error' ? (
          <p className="px-3 py-6 text-center text-caption text-danger">
            读不到技能列表，检查后端是否在跑
          </p>
        ) : items.length === 0 ? (
          <p className="px-3 py-6 text-center text-caption text-muted">
            还没有技能，点下面「导入技能」建一个试试
          </p>
        ) : (
          items.map((skill) => (
            <div
              key={skill.name}
              className="group flex items-start gap-2 px-3 py-2 transition-colors hover:bg-surface-hover"
            >
              <Checkbox
                checked={skill.enabled}
                disabled={busyName === skill.name}
                onChange={(next) => onToggle(skill.name, next)}
                label={`启用技能 ${skill.title}`}
                size="sm"
                className="mt-0.5"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-caption font-medium text-ink" title={skill.name}>
                  {skill.title}
                </p>
                <p className="mt-0.5 line-clamp-1 text-caption text-muted">
                  {skill.description || '没有写说明'}
                </p>
              </div>
              {confirming === skill.name ? (
                <span className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => {
                      setConfirming(null);
                      onRemove(skill.name);
                    }}
                    className="rounded-chip bg-danger-soft px-1.5 py-0.5 text-[calc(10px*var(--font-scale))] font-medium text-danger"
                  >
                    删除
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirming(null)}
                    className="rounded-chip px-1.5 py-0.5 text-[calc(10px*var(--font-scale))] text-muted hover:bg-surface-hover"
                  >
                    取消
                  </button>
                </span>
              ) : (
                <IconButton
                  label={`删除技能 ${skill.title}`}
                  className="h-5 w-5 shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                  disabled={busyName === skill.name}
                  onClick={() => setConfirming(skill.name)}
                >
                  <IconX size={11} />
                </IconButton>
              )}
            </div>
          ))
        )}
      </div>

      <footer className="flex items-center gap-2 border-t border-line px-3 py-2">
        <button
          type="button"
          onClick={onImportGuide}
          disabled={disabled || importing}
          className="inline-flex shrink-0 items-center gap-1 rounded-chip border border-line bg-surface-soft px-2 py-1 text-caption text-ink-soft transition-colors hover:border-brand-line hover:text-ink disabled:opacity-50"
        >
          {importing ? <IconSpinner size={11} /> : <IconPlus size={11} />}
          导入技能
        </button>
        <span className="min-w-0 truncate text-caption text-muted">
          {notice ?? '启用后写进系统提示词，下一轮生效'}
        </span>
      </footer>
    </div>
  );
}
