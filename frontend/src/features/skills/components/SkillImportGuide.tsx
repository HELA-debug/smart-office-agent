import { useRef, useState } from 'react';
import {
  IconCheck,
  IconDownload,
  IconFile,
  IconSparkle,
  IconSpinner,
  IconWand,
} from '../../../shared/ui/Icons';
import { Button, Modal } from '../../../shared/ui/primitives';
import type { SkillDraft } from '../api';
import type { ReactNode } from 'react';

/**
 * 「导入技能」的新手引导。
 *
 * 之前点「导入技能」直接弹系统文件选择框：用户手里没有符合格式的文件，
 * 也不知道文件该写成什么样，等于把门槛留给了用户。
 *
 * 这一版把说明压到最低理解成本（照着做就行，不需要懂任何术语）：
 *   1. 下载一个现成的文本文件（叫 SKILL.md）
 *   2. 照着高亮的三行改成自己的话，别的地方不用动
 *   3. 选这个文件导入，列表里立刻出现
 *
 * 三条设计约束：
 *   · 不出现 frontmatter / Markdown / 字段 这类词——用户只需要知道「改哪一行」；
 *   · 主按钮不藏在底部工具条里，跟着第 3 步走，读完就能点；
 *   · category / icon 这类可选项收进「进阶」，默认不占视线。
 */

const TEMPLATE = `---
name: my-skill
title: 我的技能
description: 一句话说清这个技能帮我做什么
triggers: [关键词1, 关键词2]
---

# 怎么做

1. 第一步做什么
2. 第二步做什么
3. 最后怎么检查对不对

# 注意

- 材料里没有的数字、人名、日期不要编
`;

/** 示例里的四行「改这里」：code 是文件里长什么样，note 是这句人话怎么解释 */
const SAMPLE: { code: string; note?: string; change?: boolean }[] = [
  { code: '---', note: '开头结尾这两行不用管' },
  { code: 'name: my-skill', note: '内部编号，别和已有的重名' },
  { code: 'title: 周报小助手', note: '① 换个名字', change: true },
  { code: 'description: 600 字周报，先结论后依据', note: '② 一句话说清要什么', change: true },
  { code: 'triggers: [周报, 写周报]', note: '③ 你会怎么说它', change: true },
  { code: '---' },
  { code: '# 怎么做' },
  { code: '1. 先读我上传的材料', note: '④ 按顺序写步骤', change: true },
  { code: '2. 写成 600 字' },
  { code: '3. 最后加一句总结' },
];

export function SkillImportGuide({
  onClose,
  onImport,
  importing,
  notice,
  onDraft,
  onUseDraft,
  drafting = false,
  draftError = null,
}: {
  onClose: () => void;
  onImport: (file: File) => void;
  importing: boolean;
  /** 导入结果（成功给技能名，失败给原因），由 useSkills 统一给 */
  notice: string | null;
  /** 让模型写一版；不传则不显示这块入口（没接大模型时） */
  onDraft?: (idea: string) => Promise<SkillDraft | null>;
  /** 用这张草稿导入 */
  onUseDraft?: (draft: SkillDraft) => void;
  drafting?: boolean;
  draftError?: string | null;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [idea, setIdea] = useState('');
  const [preview, setPreview] = useState<SkillDraft | null>(null);

  const downloadTemplate = () => {
    const blob = new Blob([TEMPLATE], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    // 中文文件名在部分系统上会乱码，保持 ASCII
    link.download = 'SKILL.md';
    link.click();
    URL.revokeObjectURL(url);
  };

  const askModel = async () => {
    if (!onDraft || !idea.trim() || drafting) return;
    const result = await onDraft(idea.trim());
    if (result) setPreview(result);
  };

  const failed = notice?.startsWith('导入失败') ?? false;
  const canAsk = Boolean(onDraft) && idea.trim().length > 0 && !drafting;

  return (
    <Modal
      title="做一个自己的技能"
      size="md"
      onClose={onClose}
      footer={
        <Button variant="ghost" size="sm" onClick={onClose}>
          关闭
        </Button>
      }
    >
      <input
        ref={inputRef}
        type="file"
        accept=".md,.markdown"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (!file) return;
          setFileName(file.name);
          onImport(file);
        }}
      />

      <p className="rounded-control bg-surface-sunken px-3 py-2 text-caption leading-relaxed text-ink-soft">
        技能就是一张便签：上面写清「这类活该怎么干」。放进这里，以后你一句话，它就照着便签做。
        <span className="mt-1 block text-faint">
          懒的话就让它替你写（下面那块）；想自己写，照着三步点也行。
        </span>
      </p>

      {onDraft ? (
        <div className="mt-2.5 rounded-control border border-brand-line bg-brand-soft/70 px-3 py-2.5">
          <div className="flex items-center gap-1.5 text-mini font-medium text-ink">
            <IconWand size={13} className="shrink-0 text-brand-strong" />
            不想自己写？说一句，让它替你写
          </div>
          <p className="mt-1 text-caption leading-relaxed text-muted">
            不用打开记事本。一句话说清你要它干什么，它就把便签写好放这儿，你看着满意就收下。
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <input
              value={idea}
              onChange={(event) => setIdea(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void askModel();
              }}
              aria-label="一句话说清你要什么"
              placeholder="把录音转成会议纪要，只留结论和待办"
              className="h-8 min-w-0 flex-1 rounded-control border border-line bg-surface px-2 text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none"
            />
            <Button
              variant="primary"
              size="sm"
              disabled={!canAsk}
              loading={drafting}
              onClick={() => void askModel()}
              leading={drafting ? undefined : <IconWand size={13} />}
            >
              {drafting ? '正在写…' : preview ? '再写一张' : '让模型写一张'}
            </Button>
          </div>
          {draftError ? <p className="mt-1 text-caption text-danger">{draftError}</p> : null}

          {preview ? (
            <div className="mt-2 overflow-hidden rounded-control border border-line bg-surface">
              <div className="flex items-center gap-1.5 border-b border-line px-2 py-1.5">
                <IconSparkle size={12} className="shrink-0 text-brand" />
                <span className="min-w-0 truncate text-caption font-medium text-ink">
                  {preview.title || preview.name}
                </span>
                <span className="ml-auto shrink-0 text-[calc(10.5px*var(--font-scale))] text-faint">
                  {preview.source === 'model' ? `由 ${preview.model || '模型'} 写` : '本地模板'}
                </span>
              </div>
              <pre className="max-h-36 overflow-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-[calc(11px*var(--font-scale))] leading-[1.6] text-ink-soft">
                {preview.markdown}
              </pre>
              <div className="flex items-center gap-2 border-t border-line px-2 py-1.5">
                <span className="min-w-0 flex-1 text-[calc(11px*var(--font-scale))] leading-relaxed text-faint">
                  {preview.note}
                </span>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={importing}
                  onClick={() => onUseDraft?.(preview)}
                  leading={importing ? <IconSpinner size={12} /> : <IconCheck size={12} />}
                >
                  就用这张
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <ol className="mt-3 space-y-3">
        <Step index={1} title="下一张空便签">
          <p className="text-caption leading-relaxed text-muted">
            点这个按钮会下载一个文件。用记事本或 Word 打开它，改完保存就行。
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-1.5"
            onClick={downloadTemplate}
            leading={<IconDownload size={12} />}
          >
            下载便签（SKILL.md）
          </Button>
        </Step>

        <Step index={2} title="照着高亮的三行，改成你自己的话">
          <p className="text-caption leading-relaxed text-muted">
            打开文件后长这样。只改带底色和编号的行，其余原样保留：
          </p>
          <div className="mt-1.5 overflow-hidden rounded-control border border-line bg-surface-sunken/60">
            {SAMPLE.map((line, index) => (
              <div
                key={`${index}-${line.code}`}
                className={`flex items-baseline gap-2 px-2.5 py-[2px] font-mono text-[calc(11px*var(--font-scale))] leading-[1.7] ${
                  line.change ? 'bg-brand-soft/60' : ''
                }`}
              >
                <code
                  className={`min-w-0 flex-1 truncate ${line.change ? 'text-ink' : 'text-ink-soft'}`}
                >
                  {line.code}
                </code>
                {line.note ? (
                  <span className="shrink-0 font-sans text-[calc(10.5px*var(--font-scale))] text-faint">
                    {line.note}
                  </span>
                ) : null}
              </div>
            ))}
          </div>
          <p className="mt-1.5 text-[calc(11px*var(--font-scale))] leading-relaxed text-faint">
            ③ 那行是关键：只有你说到这些词，它才会用上这张便签。多写几个说法更稳。
          </p>

          <details className="mt-1.5 text-[calc(11px*var(--font-scale))] text-faint">
            <summary className="cursor-pointer select-none hover:text-muted">
              想换图标或归类？点开看（可以不管）
            </summary>
            <p className="mt-1 leading-relaxed">
              加一行 <Code>category</Code> 归类：办公文档 / 表格数据 / 会议协作 / 内容写作 /
              文件处理； 加一行 <Code>icon</Code> 换图标：doc / sheet / minutes / retro / shield /
              book / terminal / folder / list / puzzle。
            </p>
          </details>
        </Step>

        <Step index={3} title="把这个文件选进来">
          <p className="text-caption leading-relaxed text-muted">
            点下面的按钮，找到刚才保存的文件，双击。导入后会出现在下面的「技能」列表里，随时能关掉。
          </p>
          <Button
            variant="primary"
            size="sm"
            className="mt-1.5"
            disabled={importing}
            onClick={() => inputRef.current?.click()}
            leading={importing ? <IconSpinner size={13} /> : <IconFile size={13} />}
          >
            {importing ? '正在导入…' : '选文件导入'}
          </Button>
          {fileName ? (
            <p className="mt-1.5 flex items-center gap-1.5 text-caption text-ink-soft">
              <IconFile size={12} className="shrink-0 text-faint" />
              <span className="truncate">{fileName}</span>
            </p>
          ) : null}
          {notice ? (
            <p
              className={`mt-1.5 flex items-start gap-1.5 rounded-control px-2 py-1.5 text-caption ${
                failed ? 'bg-danger-soft text-danger' : 'bg-ok-soft text-ok'
              }`}
            >
              {failed ? null : <IconCheck size={12} className="mt-0.5 shrink-0" />}
              <span>{notice}</span>
            </p>
          ) : null}
        </Step>
      </ol>

      <p className="mt-3 border-t border-line pt-2.5 text-[calc(11px*var(--font-scale))] leading-relaxed text-faint">
        不想自己写也没关系：技能库里已经有现成的（周报、会议纪要、数据速读…），
        点「添加」就能用，不用导入。
      </p>
    </Modal>
  );
}

function Step({ index, title, children }: { index: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-2.5">
      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-brand-soft text-[calc(11px*var(--font-scale))] font-semibold text-brand-strong">
        {index}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-mini font-medium text-ink">{title}</div>
        <div className="mt-0.5">{children}</div>
      </div>
    </li>
  );
}

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-surface-sunken px-1 py-[1px] font-mono">{children}</code>;
}
