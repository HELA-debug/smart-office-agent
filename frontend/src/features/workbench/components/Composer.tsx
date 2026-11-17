import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  APPROVAL_MODES,
  APPROVAL_MODE_HINTS,
  APPROVAL_MODE_LABELS,
} from '../../../shared/config/approval-modes';
import { docStyleSummary } from '../../../shared/config/doc-style';
import {
  OUTPUT_FORMATS,
  OUTPUT_FORMAT_COMPACT,
  OUTPUT_FORMAT_LABELS,
  MEDIA_KIND_LABELS,
  UPLOAD_ACCEPT,
  extOfFilename,
} from '../../../shared/config/output-formats';
import { ApiError } from '../../../shared/lib/api';
import { MAX_DROP_FILES, captureDrop, expandDrop, type DropCapture } from '../../../shared/lib/drop-files';
import { DROP_FILES_EVENT, type DropFilesDetail } from '../../../shared/lib/drop-guard';
import { formatBytes } from '../../../shared/lib/format';
import {
  IconAlertTriangle,
  IconArrowUp,
  IconCheck,
  IconCheckCircle,
  IconChevronRight,
  IconClock,
  IconDoc,
  IconFile,
  IconFolder,
  IconMic,
  IconPaperclip,
  IconPdf,
  IconPlus,
  IconSettings,
  IconSheet,
  IconShield,
  IconSlides,
  IconSparkle,
  IconSpinner,
  IconStop,
  IconText,
  IconWand,
  IconX,
} from '../../../shared/ui/Icons';
import { IconButton, Tooltip } from '../../../shared/ui/primitives';
import { Select } from '../../../shared/ui/Select';
import { uploadTypeLabel } from '../../artifacts';
import { promptsApi } from '../api/prompts';
import { ComposerQuickAccess } from './ComposerQuickAccess';
import { DocStylePanel } from './DocStylePanel';
import { QueuedMessages } from './QueuedMessages';
import type { ApprovalMode } from '../../../shared/config/approval-modes';
import type { DocStyle } from '../../../shared/config/doc-style';
import type { OutputFormat } from '../../../shared/config/output-formats';
import type { QueuedMessage, UploadItem } from '../state/workbench';
import type {
  ChangeEvent,
  ComponentType,
  DragEvent,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode,
  RefObject,
} from 'react';

/** 上传 accept 与产物格式都从 shared/config 取：这里不再手写第二份清单。 */

/** 产物格式在菜单里的图标：和产物中心的类型图标保持一致，用户不用重新认一遍。 */
const FORMAT_ICONS: Record<OutputFormat, ComponentType<{ size?: number; className?: string }>> = {
  docx: IconDoc,
  pdf: IconPdf,
  xlsx: IconSheet,
  pptx: IconSlides,
  txt: IconText,
};

/** 输入框下方那行提示的两种语气：warn 说「缺什么」，info 说「刚做了什么」。 */
type HintTone = 'warn' | 'info';

interface Hint {
  text: string;
  tone: HintTone;
}

function UploadChip({
  upload,
  onRemove,
  onRetry,
}: {
  upload: UploadItem;
  onRemove: () => void;
  onRetry?: () => void;
}) {
  const isError = upload.status === 'error';
  const isUploading = upload.status === 'uploading';
  /** 还没开会话：文件在本地排队，等发送任务时才上传 */
  const isStaged = upload.status === 'staged';
  /** 文件已经收下，但文字还在识别（图片 OCR / 录音转写）：既不是失败也不是可用 */
  const recognizing = upload.media_status === 'processing';
  const mediaFailed = upload.media_status === 'failed';
  const mediaLabel = upload.media_kind ? MEDIA_KIND_LABELS[upload.media_kind] : '';

  const chip = (
    <div
      className={`flex max-w-full items-center gap-2 rounded-control border py-1 pr-1 pl-1.5 text-caption shadow-card transition-colors ${
        isError || mediaFailed
          ? 'border-danger-line bg-danger-soft text-danger'
          : isStaged
            ? 'border-line-strong bg-surface-sunken text-ink-soft hover:border-brand-line hover:bg-surface-hover'
            : isUploading || recognizing
              ? 'border-brand-line bg-brand-soft text-ink-soft'
              : 'border-line-strong bg-surface-sunken text-ink-soft hover:border-brand-line hover:bg-surface-hover'
      }`}
    >
      {/* 状态灯：深一档的圆底把图标托起来，比裸图标更容易一眼扫到 */}
      <span
        className={`grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface ${
          isError || mediaFailed
            ? 'text-danger'
            : isUploading || recognizing
              ? 'text-brand'
              : isStaged
                ? 'text-muted'
                : 'text-ok'
        }`}
      >
        {isError || mediaFailed ? (
          <IconAlertTriangle size={12} />
        ) : isUploading || recognizing ? (
          <IconSpinner size={12} className="animate-spin" />
        ) : isStaged ? (
          <IconFile size={12} />
        ) : (
          <IconCheckCircle size={12} />
        )}
      </span>
      <span className="shrink-0 rounded-chip bg-brand-soft px-1.5 py-px text-[calc(10px*var(--font-scale))] font-semibold tracking-wide text-brand ring-1 ring-brand-line">
        {mediaLabel || uploadTypeLabel(upload.filename, upload.ext)}
      </span>
      <span className="max-w-[11.25rem] truncate font-medium text-ink">{upload.filename}</span>
      <span className="shrink-0 tabular-nums text-faint">
        {isUploading
          ? `上传中 ${upload.progress ?? 0}%`
          : isError
            ? '失败'
            : isStaged
              ? '待发送'
              : recognizing
                ? '识别中…'
                : mediaFailed
                  ? '识别失败'
                  : upload.note
                    ? '读不出文字'
                    : upload.chars != null
                      ? `${upload.chars} 字`
                      : formatBytes(upload.size)}
      </span>
      {isUploading ? (
        <span className="h-1 w-10 shrink-0 overflow-hidden rounded-full bg-surface-hover">
          <span
            className="block h-full rounded-full bg-brand transition-all"
            style={{ width: `${upload.progress ?? 0}%` }}
          />
        </span>
      ) : null}
      {/* 识别失败才给重试：模型没下完、机器忙不过来时不用删了重传 */}
      {mediaFailed && onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-chip px-1.5 py-px font-medium text-brand-strong transition-colors hover:bg-surface hover:underline"
        >
          重试
        </button>
      ) : null}
      <IconButton
        label="移除"
        className="h-5 w-5 shrink-0 hover:bg-surface-hover"
        onClick={onRemove}
        disabled={isUploading}
      >
        <IconX size={11} />
      </IconButton>
    </div>
  );

  // 文件名本身就在卡上，再挂一个跟着鼠标的提示纯属噪音；失败原因与
  // 「读不出文字」的说明值得用提示补充（后者要告诉用户换成什么格式）
  const failure = upload.error ?? upload.media_error ?? upload.note;
  return failure ? (
    <Tooltip label={failure} side="top">
      {chip}
    </Tooltip>
  ) : (
    chip
  );
}

/** 菜单里二级分组的选项：图标沿用产物中心的类型图标，用户不用重新认一遍 */
interface MenuGroupOption<T extends string> {
  value: T;
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  /** 右侧备注（如「同素材」） */
  note?: string;
}

/**
 * 菜单里的一个「悬停展开」分组：折叠时只占一行（带当前值），
 * 指针移上去才在右侧弹出二级面板，选完即收。
 *
 * 为什么不直接把选项平铺在菜单里：产物格式四项 + 三条跳转叠起来接近一屏，
 * 菜单像一张设置页；折叠成一行后菜单整体只有五行的体积，需要改格式时多移动一次鼠标即可。
 */
function ComposerMenuGroup<T extends string>({
  label,
  icon: GroupIcon,
  summary,
  options = [],
  value,
  open,
  onOpen,
  onLeave,
  onClose,
  onSelect,
  panel,
}: {
  label: string;
  icon: ComponentType<{ size?: number; className?: string }>;
  /** 收起状态下也看得到「现在选的是哪个 / 有几项启用」 */
  summary?: string;
  /** 选项列表：和 panel 二选一 */
  options?: MenuGroupOption<T>[];
  value?: T;
  open: boolean;
  onOpen: () => void;
  onLeave: () => void;
  onClose: () => void;
  onSelect?: (next: T) => void;
  /** 自定义二级面板（技能列表这类富内容），给了它就不再渲染选项 */
  panel?: ReactNode;
}) {
  const flyoutRef = useRef<HTMLDivElement>(null);
  /** 二级面板顶到视口边缘时整体内收的距离 */
  const [shift, setShift] = useState({ x: 0, y: 0 });

  useLayoutEffect(() => {
    if (!open) {
      setShift({ x: 0, y: 0 });
      return;
    }
    const element = flyoutRef.current;
    if (!element) return;
    const rect = element.getBoundingClientRect();
    const overflowRight = rect.right - (window.innerWidth - 8);
    const overflowLeft = 8 - rect.left;
    const overflowBottom = rect.bottom - (window.innerHeight - 8);
    const overflowTop = 8 - rect.top;
    setShift({
      // 面板可能比菜单宽（技能面板）：向右溢出就内收，向左溢出再推回来
      x: overflowRight > 0 ? -overflowRight : overflowLeft > 0 ? overflowLeft : 0,
      y: overflowBottom > 0 ? -overflowBottom : overflowTop > 0 ? overflowTop : 0,
    });
  }, [open]);

  const rowClass =
    'flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-mini text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink';

  return (
    <div className="relative" onPointerEnter={onOpen} onPointerLeave={onLeave}>
      <button
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={open}
        // 触屏没有悬停：点一下也能开；键盘 Tab 到这一行同样展开
        onFocus={onOpen}
        onClick={() => (open ? onClose() : onOpen())}
        className={`${rowClass} ${open ? 'bg-surface-hover text-ink' : ''}`}
      >
        <GroupIcon size={15} className={open ? 'text-brand' : 'text-muted'} />
        {/* 分组名不参与压缩：被省略号截成「产物…」等于没写 */}
        <span className="shrink-0">{label}</span>
        {summary ? (
          <span className="ml-auto min-w-0 truncate text-caption text-faint">{summary}</span>
        ) : null}
        <IconChevronRight
          size={12}
          className={`shrink-0 text-faint transition-[translate] duration-[var(--dur-feedback)] ${
            open ? 'translate-x-0.5 text-muted' : ''
          }`}
        />
      </button>

      {/* 收起时用 visibility + inert 藏起来：既不可点、也不进 Tab 和无障碍树，还能保留淡出过渡 */}
      <div
        ref={flyoutRef}
        role="menu"
        aria-label={label}
        aria-hidden={open ? undefined : true}
        inert={!open}
        style={{ marginTop: shift.y, marginLeft: shift.x }}
        className={`absolute top-0 left-full z-10 pl-1.5 transition-[opacity,translate,visibility] duration-[var(--dur-enter)] ease-[var(--ease-out)] ${
          open
            ? 'visible translate-x-0 opacity-100'
            : 'pointer-events-none invisible -translate-x-1 opacity-0'
        }`}
      >
        <div
          className={
            panel
              ? 'overflow-hidden rounded-card border border-line bg-surface shadow-pop'
              : 'w-[13.5rem] rounded-card border border-line bg-surface p-1 shadow-pop'
          }
        >
          {panel ??
            options.map((option) => {
              const OptionIcon = option.icon;
              const selected = option.value === value;
              return (
                <button
                  key={option.value}
                  type="button"
                  role="menuitemradio"
                  aria-checked={selected}
                  className={`${rowClass} ${selected ? 'text-ink' : ''}`}
                  onClick={() => onSelect?.(option.value)}
                >
                  <OptionIcon size={15} className={selected ? 'text-brand' : 'text-muted'} />
                  <span className={`flex-1 truncate ${selected ? 'font-medium' : ''}`}>
                    {option.label}
                  </span>
                  {option.note ? (
                    <span className="shrink-0 text-[calc(10px*var(--font-scale))] text-faint">
                      {option.note}
                    </span>
                  ) : null}
                  {selected ? <IconCheck size={12} className="shrink-0 text-brand" /> : null}
                </button>
              );
            })}
        </div>
      </div>
    </div>
  );
}

/**
 * 输入框左侧「+」：圆形按钮 + 弹出菜单。
 *
 * 这里是输入区的**唯一设置入口**：添加文件、产物格式、技能、文档格式，再加「设置」。
 * 面板底色跟主题走（浅色主题是白卡片、暗色主题是深卡），不再压成一块纯黑——
 * 浅色界面里点开加号会突然掉下一块黑方块，和输入框、对话区完全不搭。
 * 体积上只保留五行的量：
 *
 * - 「产物中心」「审计用量」**已经从这里去掉**：它们是「回头翻」的页面，摆在
 *   输入框旁边每天都在那儿，却几乎没人点；右栏和运行摘要卡里都有入口。
 *   位置让给「文档格式」——那一排才是发稿前真会调的（字体/字号/字形/行距/缩进/对齐），
 *   抄的是 WPS 段落与字体工具栏，不另造一套叫法；
 * - 审批策略**不再出现在面板里**——加号右边本来就有一个常驻胶囊，同一份状态抄两遍
 *   只会让人怀疑「两边是不是不一样」，删除面板内部那一份，胶囊成为唯一入口；
 * - 剩下的产物格式折叠成一行（右侧显示当前值），悬停才弹出四选一，
 *   需要时才展开的二级设置不该在菜单里常驻四行。
 */
function ComposerPlusMenu({
  disabled,
  onPickFiles,
  outputFormat,
  onOutputFormatChange,
  uploads,
  skillsPanel,
  skillsSummary,
  docStyle,
  onDocStyleChange,
}: {
  disabled?: boolean;
  /** 打开系统文件选择器：文档、图片、录音、视频一次都给全 */
  onPickFiles: () => void;
  outputFormat: OutputFormat;
  onOutputFormatChange: (format: OutputFormat) => void;
  /** 用来标出「和第一个素材同格式」的那一项（对应原下拉里的「默认·同素材」） */
  uploads: UploadItem[];
  /** 技能面板（由页面组装），作为菜单里的二级分组 */
  skillsPanel?: ReactNode;
  /** 收起时显示「2/2 启用」这类摘要 */
  skillsSummary?: string;
  /** 文档格式：字体 / 字号 / 字型 / 行距 / 首行缩进 / 对齐，随这一轮一起发出去 */
  docStyle?: DocStyle;
  onDocStyleChange?: (next: DocStyle) => void;
}) {
  const [open, setOpen] = useState(false);
  /** 同一时间只展开一个二级面板：两个都开着会互相遮挡，也说不清焦点在哪 */
  const [openGroup, setOpenGroup] = useState<'format' | 'skills' | 'style' | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const closeTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // Esc 先收二级面板，再收整张菜单：两次按键的粒度符合「一层一层退出」
      if (openGroup) {
        setOpenGroup(null);
        return;
      }
      setOpen(false);
    };
    document.addEventListener('mousedown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('mousedown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, openGroup]);

  // 菜单收起时二级面板一并归位，下次打开不会「记忆」着上次展开的分组
  useEffect(() => {
    if (!open) setOpenGroup(null);
  }, [open]);

  useEffect(
    () => () => {
      if (closeTimer.current) window.clearTimeout(closeTimer.current);
    },
    [],
  );

  /** 鼠标从行移到二级面板要跨过 6px 间隙，留一点宽容时间，别一闪就收 */
  const scheduleGroupClose = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    closeTimer.current = window.setTimeout(() => setOpenGroup(null), 160);
  };
  const openFormatGroup = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    setOpenGroup('format');
  };
  const openSkillsGroup = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    setOpenGroup('skills');
  };
  const openStyleGroup = () => {
    if (closeTimer.current) window.clearTimeout(closeTimer.current);
    setOpenGroup('style');
  };

  const rowClass =
    'flex w-full items-center gap-2.5 rounded-control px-2.5 py-2 text-left text-mini text-ink-soft transition-colors hover:bg-surface-hover hover:text-ink';

  const sourceFormat = uploads.length > 0 ? extOfFilename(uploads[0]?.filename ?? '') : '';
  const formatOptions: MenuGroupOption<OutputFormat>[] = OUTPUT_FORMATS.map((format) => ({
    value: format,
    label: OUTPUT_FORMAT_LABELS[format],
    icon: FORMAT_ICONS[format],
    note: sourceFormat === format ? '同素材' : undefined,
  }));

  const trigger = (
    <button
      type="button"
      aria-label={`更多输入选项（产物 ${OUTPUT_FORMAT_LABELS[outputFormat]}）`}
      aria-expanded={open}
      aria-haspopup="menu"
      disabled={disabled}
      onClick={() => setOpen((value) => !value)}
      className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
        open
          ? 'bg-surface-hover text-ink'
          : 'bg-surface-sunken text-ink-soft hover:bg-surface-hover hover:text-ink'
      } disabled:opacity-50`}
    >
      <IconPlus size={14} />
    </button>
  );

  return (
    <div ref={rootRef} className="relative">
      {/* 菜单展开时不挂 tooltip：气泡会浮在菜单上，把刚点开的内容压住 */}
      {open ? (
        trigger
      ) : (
        <Tooltip label={`更多输入选项 · 产物 ${OUTPUT_FORMAT_LABELS[outputFormat]}`} side="top">
          {trigger}
        </Tooltip>
      )}

      {open ? (
        <div
          role="menu"
          aria-label="更多输入选项"
          onPointerLeave={scheduleGroupClose}
          className="absolute bottom-full left-0 z-30 mb-2 w-[16rem] rounded-card border border-line bg-surface p-1 shadow-pop"
        >
          {/* 「添加文件」就是打开系统对话框，不再先问「加什么类型」：
              对话框永远开在同一个位置，分五类也定位不到具体文件夹，
              多一层选择只是多一次点击。收什么格式由 accept 一次给全，
              图片/录音/视频的文字识别在后台自动做，用户不用先声明类型。 */}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              onPickFiles();
            }}
            className={rowClass}
          >
            <IconPaperclip size={15} className="text-muted" />
            <span className="flex-1 truncate">添加文件</span>
          </button>

          <div className="my-1 h-px bg-line" />

          <ComposerMenuGroup
            label="产物格式"
            icon={IconFile}
            summary={OUTPUT_FORMAT_COMPACT[outputFormat]}
            options={formatOptions}
            value={outputFormat}
            open={openGroup === 'format'}
            onOpen={openFormatGroup}
            onLeave={scheduleGroupClose}
            onClose={() => setOpenGroup(null)}
            onSelect={(format) => {
              onOutputFormatChange(format);
              setOpen(false);
            }}
          />

          {skillsPanel ? (
            <ComposerMenuGroup
              label="技能"
              icon={IconSparkle}
              summary={skillsSummary}
              panel={skillsPanel}
              open={openGroup === 'skills'}
              onOpen={openSkillsGroup}
              onLeave={scheduleGroupClose}
              onClose={() => setOpenGroup(null)}
            />
          ) : null}

          {onDocStyleChange ? (
            <ComposerMenuGroup
              label="文档格式"
              icon={IconWand}
              summary={docStyleSummary(docStyle ?? {})}
              panel={
                // 面板不随每次点选关闭：字体、字号、行距常常要连着改三项，
                // 每点一次就收起来等于让用户重新展开三遍。
                <DocStylePanel value={docStyle ?? {}} onChange={onDocStyleChange} />
              }
              open={openGroup === 'style'}
              onOpen={openStyleGroup}
              onLeave={scheduleGroupClose}
              onClose={() => setOpenGroup(null)}
            />
          ) : null}

          <div className="my-1 h-px bg-line" />

          <Link to="/settings" role="menuitem" onClick={() => setOpen(false)} className={rowClass}>
            <IconSettings size={15} className="text-muted" />
            <span className="flex-1 truncate">设置</span>
            <IconChevronRight size={12} className="shrink-0 text-faint" />
          </Link>
        </div>
      ) : null}
    </div>
  );
}

/**
 * 增强提示词：把「整理成周报」补成「任务 / 输出格式 / 篇幅 / 要求」四段。
 *
 * 三件事必须让用户看得见：正在增强（转圈）、增强完了（一句话说明来源）、没写成（说明原因）。
 * 按钮本身不做 native disabled：空输入时点它是有意义的操作——把焦点送回输入框并说清缺什么。
 */
function ComposerEnhance({
  text,
  outputFormat,
  disabled,
  onEnhanced,
  onNotice,
  focusInput,
}: {
  text: string;
  outputFormat: OutputFormat;
  disabled?: boolean;
  onEnhanced: (next: string, note: string) => void;
  onNotice: (hint: Hint) => void;
  /** 空输入时把焦点送回输入框：和发送按钮的处理保持一致 */
  focusInput?: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // 组件卸载（切会话/关页面）时把在飞的请求掐掉，别让 setState 落到已卸载的组件上
  useEffect(() => () => abortRef.current?.abort(), []);

  const run = async () => {
    if (loading || disabled) return;
    const source = text.trim();
    if (!source) {
      onNotice({ text: '先写一句需求，再点增强提示词', tone: 'warn' });
      focusInput?.();
      return;
    }
    const controller = new AbortController();
    abortRef.current = controller;
    setLoading(true);
    try {
      const result = await promptsApi.enhance({ text: source, outputFormat }, controller.signal);
      if (!result.data.text) {
        onNotice({ text: '这次没能增强出可用内容，原文已保留', tone: 'warn' });
        return;
      }
      onEnhanced(result.data.text, result.data.note);
    } catch (error) {
      if (error instanceof ApiError && error.code === 'ABORTED') return;
      const message = error instanceof ApiError ? error.message : '增强失败，请稍后再试';
      onNotice({ text: `增强失败：${message}（原文已保留）`, tone: 'warn' });
    } finally {
      setLoading(false);
      abortRef.current = null;
    }
  };

  return (
    <Tooltip label={loading ? '正在增强…' : '增强提示词'} side="top">
      <button
        type="button"
        aria-label="增强提示词"
        aria-busy={loading}
        onClick={run}
        className={`relative flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
          loading ? 'text-brand' : 'text-muted hover:bg-surface-hover hover:text-ink'
        } disabled:cursor-not-allowed disabled:opacity-45`}
      >
        {loading ? (
          <span
            aria-hidden
            className="absolute inset-0 animate-spin rounded-full border-2 border-brand-line border-t-brand"
          />
        ) : null}
        <IconWand size={15} className={loading ? 'opacity-40' : ''} />
      </button>
    </Tooltip>
  );
}

/** 语音输入：浏览器支持 Web Speech 时可用，否则禁用并说明。 */
function ComposerMic({ disabled, onText }: { disabled?: boolean; onText: (text: string) => void }) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<{ stop: () => void } | null>(null);

  const supported =
    typeof window !== 'undefined' &&
    Boolean(
      (window as unknown as { SpeechRecognition?: unknown; webkitSpeechRecognition?: unknown })
        .SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: unknown }).webkitSpeechRecognition,
    );

  const toggle = () => {
    if (!supported) return;
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }
    type SpeechCtor = new () => {
      lang: string;
      interimResults: boolean;
      onresult: (event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void;
      onend: () => void;
      start: () => void;
      stop: () => void;
    };
    const holder = window as unknown as {
      SpeechRecognition?: SpeechCtor;
      webkitSpeechRecognition?: SpeechCtor;
    };
    const Ctor = holder.SpeechRecognition ?? holder.webkitSpeechRecognition;
    if (!Ctor) return;
    const recognition = new Ctor();
    recognition.lang = 'zh-CN';
    recognition.interimResults = false;
    recognition.onresult = (event) => {
      const transcript = Array.from({ length: event.results.length })
        .map((_, index) => event.results[index]?.[0]?.transcript ?? '')
        .join('');
      if (transcript) onText(transcript);
    };
    recognition.onend = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  };

  return (
    <Tooltip label={supported ? '语音输入' : '当前浏览器不支持语音输入'} side="top">
      <button
        type="button"
        aria-label="语音输入"
        aria-pressed={listening}
        disabled={disabled || !supported}
        onClick={toggle}
        className={`flex h-7 w-7 items-center justify-center rounded-full transition-colors ${
          listening
            ? 'bg-danger-soft text-danger'
            : 'text-muted hover:bg-surface-hover hover:text-ink'
        } disabled:cursor-not-allowed disabled:opacity-45`}
      >
        <IconMic size={15} />
      </button>
    </Tooltip>
  );
}

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  onUploadFiles,
  uploads,
  onRemoveUpload,
  onRetryUpload,
  disabled = false,
  isStreaming,
  waitingApproval = false,
  onOpenApproval,
  outputFormat,
  onOutputFormatChange,
  textareaRef: externalTextareaRef,
  model,
  isMock,
  modelBlocked = false,
  modelHint,
  onModelChanged,
  project,
  onClearProject,
  approvalMode,
  onApprovalModeChange,
  skillsPanel,
  skillsSummary,
  docStyle,
  onDocStyleChange,
  queue = [],
  queuePaused = false,
  onEditQueued,
  onRemoveQueued,
  onPromoteQueued,
  onResumeQueue,
}: {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onUploadFiles: (files: File[]) => void;
  uploads: UploadItem[];
  onRemoveUpload: (localId: string) => void;
  /** 识别失败后的重试（图片 OCR / 录音转写）；不传就不显示重试按钮 */
  onRetryUpload?: (localId: string) => void;
  disabled?: boolean;
  isStreaming: boolean;
  /**
   * 有操作在等用户确认：输入区这时候发不出去，但得让用户知道「在等什么」，
   * 否则他只会看到框变灰、以为卡住了。点「去确认」滚到那张卡片。
   */
  waitingApproval?: boolean;
  onOpenApproval?: () => void;
  /** 产物格式：默认与首个上传素材同格式，用户可改选其他格式。 */
  outputFormat: OutputFormat;
  onOutputFormatChange: (format: OutputFormat) => void;
  textareaRef?: RefObject<HTMLTextAreaElement | null>;
  /** 当前模型名（快捷入口展示用）。 */
  model?: string | null;
  /** 是否本地 mock 模式（快捷入口徽标用）。 */
  isMock?: boolean;
  /**
   * 没有可用的模型（真实引擎下一个 Key 都没配）：拦住发送。
   * 演示模式不受影响——它本来就不花真钱，拦它只会让想试界面的人寸步难行。
   */
  modelBlocked?: boolean;
  /** 拦住时的引导文案（后端 /health 给的人话，告诉用户怎么把模型配上） */
  modelHint?: string;
  /** 切换模型后回调（外层刷新健康检查）。 */
  onModelChanged?: () => void;
  /** 本次任务关联的项目（左栏选中的文档文件夹）。 */
  project?: { id: string; name: string; fileCount?: number } | null;
  onClearProject?: () => void;
  /** 本轮审批策略：由外层持有并持久化，随任务一起发出去。 */
  approvalMode?: ApprovalMode;
  onApprovalModeChange?: (mode: ApprovalMode) => void;
  /** 技能面板：放进加号菜单的二级分组，不占工具栏位置 */
  skillsPanel?: ReactNode;
  /** 技能分组收起时的摘要（如「2/2 启用」） */
  skillsSummary?: string;
  /** 文档格式（字体/字号/字型/行距/缩进/对齐）：随本轮任务一起发给后端 */
  docStyle?: DocStyle;
  onDocStyleChange?: (next: DocStyle) => void;
  /** 排队中的任务：当前任务结束后自动按顺序执行。 */
  queue?: QueuedMessage[];
  queuePaused?: boolean;
  onEditQueued?: (id: string) => void;
  onRemoveQueued?: (id: string) => void;
  /** 优先执行某条排队任务（提到队首） */
  onPromoteQueued?: (id: string) => void;
  onResumeQueue?: () => void;
}) {
  const innerRef = useRef<HTMLTextAreaElement>(null);
  const textareaRef = externalTextareaRef ?? innerRef;
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composingRef = useRef(false);
  const [dragging, setDragging] = useState(false);
  const [hint, setHint] = useState<Hint | null>(null);

  useEffect(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, 176)}px`;
  }, [value, textareaRef]);

  useEffect(() => {
    if (!hint) return;
    const timer = window.setTimeout(() => setHint(null), 5000);
    return () => window.clearTimeout(timer);
  }, [hint]);

  const canSend = value.trim().length > 0 && !disabled && !modelBlocked;
  const readyUploads = uploads.filter(
    (upload) =>
      (upload.status === 'parsed' || upload.status === 'staged') &&
      upload.media_status !== 'processing',
  ).length;
  /** 还在识别的素材：此时发任务后端会拒（素材文字还是空的），先在界面上拦住 */
  const recognizingUploads = uploads.filter(
    (upload) => upload.status === 'parsed' && upload.media_status === 'processing',
  );

  /**
   * 发送按钮不再用 native disabled 表达「还没写内容」：
   * 实色主按钮却点不动、hover 也没反馈，观感像坏掉了。
   * 点不动时把焦点送回输入框，并明确说清楚缺什么——
   * 只丢了附件没写需求是最容易卡住的一步，得告诉用户「还差一句话」。
   */
  const submit = () => {
    if (disabled) return;
    // 门禁放在最前：模型没配好时，写了多少字都发不出去，先说清楚缺的是什么
    if (modelBlocked) {
      setHint({
        tone: 'warn',
        text: modelHint ?? '还没有可用的模型：点左侧「选择模型」挑一家，或到设置页添加 Key',
      });
      textareaRef.current?.focus();
      return;
    }
    if (!canSend) {
      setHint({
        tone: 'warn',
        text:
          readyUploads > 0
            ? `已添加 ${readyUploads} 个素材，请再写一句需求，例如「把这份材料整理成 600 字周报」`
            : '请先输入需求，再点发送',
      });
      textareaRef.current?.focus();
      return;
    }
    if (recognizingUploads.length > 0) {
      const names = recognizingUploads
        .map((upload) => upload.filename)
        .slice(0, 2)
        .join('、');
      setHint({
        tone: 'warn',
        text: `${names}${recognizingUploads.length > 2 ? ' 等' : ''} 还在识别文字，识别完就能发（不用重传）`,
      });
      textareaRef.current?.focus();
      return;
    }
    setHint(null);
    onSubmit();
  };

  /** 增强成功：原文换成增强稿，并用 info 语气说明来源（不是警告，别用黄色） */
  const handleEnhanced = (next: string, note: string) => {
    onChange(next);
    setHint({
      tone: 'info',
      text: note ? `${note}，可直接修改后发送` : '已按可执行的结构补全，可直接修改后发送',
    });
    textareaRef.current?.focus();
  };

  const handleKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) return;
    if (event.nativeEvent.isComposing || composingRef.current) return;
    event.preventDefault();
    submit();
  };

  /**
   * 收下一批拖进来的文件。
   *
   * 两个入口共用：输入框自己的 drop，和窗口兜底转过来的 drop（文件被拖到输入框
   * 以外的地方时，由 `drop-guard` 拦下导航再转进来——否则浏览器会把整个应用
   * 换成一个文件）。逻辑只写这一份，免得两条路行为不一致。
   *
   * 参数是**已经同步抓好的** capture，不是 DataTransfer：`dataTransfer` 一离开
   * drop 回调就可能被清空，抓取必须发生在回调里（见 `captureDrop`）。
   */
  const acceptDrop = useCallback(
    async (capture: DropCapture) => {
      if (disabled) return;
      const files = await expandDrop(capture);
      if (files.length === 0) {
        // 什么都不说最难受：用户以为是拖歪了，会一遍遍重试。
        // 而且这里两种失败完全不同，得分开说：
        //  - 拖的是文件但浏览器没给内容（压缩包预览、网盘占位、聊天窗口，
        //    这些拖出来的只是「壳」，没有字节）→ 直接开选择框，别让用户干瞪眼；
        //  - 拖的根本不是文件（页面上的文字/图片）→ 说清楚，别乱弹窗。
        const looksLikeFiles = capture.types.includes('Files');
        if (!looksLikeFiles) {
          setHint({
            tone: 'warn',
            text: '这一下拖的是页面上的内容，不是文件。要加素材请点「+」选文件，或从资源管理器拖进来',
          });
          return;
        }
        setHint({
          tone: 'warn',
          text: `这次拖拽没带文件内容（浏览器给了 ${capture.files.length} 个文件、${capture.itemCount} 个条目）。从压缩包预览、网盘占位或聊天窗口里拖出来的常这样——已帮你打开选择框，选同一个文件就行`,
        });
        fileInputRef.current?.click();
        return;
      }
      // 不再按后缀筛一遍：收不收由后端说了算。认不出的格式也会被收下，
      // 读不出文字时如实说明（旧版 .doc 会提示另存为 docx），而不是在这里拦掉。
      onUploadFiles(files.slice(0, MAX_DROP_FILES));
      if (files.length > MAX_DROP_FILES) {
        setHint({
          tone: 'warn',
          text: `一次最多收 ${MAX_DROP_FILES} 个文件，这次先放入前 ${MAX_DROP_FILES} 个`,
        });
      }
    },
    [disabled, onUploadFiles],
  );

  // 拖到输入框以外（左栏、对话区、右栏）也要能加：窗口兜底把 drop 转到这里来
  useEffect(() => {
    const onWindowDrop = (event: Event) => {
      const detail = (event as CustomEvent<DropFilesDetail>).detail;
      // 同步抓取：这个监听器是在 drop 回调里同步触发的
      void acceptDrop(captureDrop(detail?.dataTransfer ?? null));
    };
    window.addEventListener(DROP_FILES_EVENT, onWindowDrop);
    return () => window.removeEventListener(DROP_FILES_EVENT, onWindowDrop);
  }, [acceptDrop]);

  const handleFiles = (files: FileList | null) => {
    if (!files || files.length === 0) return;
    onUploadFiles(Array.from(files));
  };

  const onPickFile = (event: ChangeEvent<HTMLInputElement>) => {
    handleFiles(event.target.files);
    // 清空 value：选同一个文件两次也能再次触发 change
    event.target.value = '';
  };

  const openPicker = () => {
    fileInputRef.current?.click();
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    // 同步抓取：出了这个回调，dataTransfer 里的东西就不一定还在了
    void acceptDrop(captureDrop(event.dataTransfer));
  };

  return (
    <div className="mx-auto w-full max-w-[54.5rem] px-gutter pt-1 pb-[clamp(0.75rem,2.2vh,1.25rem)]">
      {/* 排队中的任务：上一个任务跑完后自动接着执行，先在这儿让用户看得见、改得动 */}
      <QueuedMessages
        items={queue}
        paused={queuePaused}
        onEdit={(id) => onEditQueued?.(id)}
        onRemove={(id) => onRemoveQueued?.(id)}
        onPromote={(id) => onPromoteQueued?.(id)}
        onResume={() => onResumeQueue?.()}
      />
      <div
        // dragenter 也要放行：某些内核（内嵌 webview、老 Chromium 分支）只认
        // dragenter 上的 preventDefault，光拦 dragover 时 drop 会照常触发，
        // 但 dataTransfer 里一个文件都没有——表现就是「拖进来了，却说没读到文件」。
        onDragEnter={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          if (!disabled) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`relative rounded-panel border bg-surface p-3 shadow-card transition-all ${
          dragging
            ? 'composer-lit border-brand border-dashed'
            : hint
              ? hint.tone === 'warn'
                ? 'composer-lit-warn border-warn-line'
                : 'composer-lit border-brand-line'
              : 'composer-glow border-line-strong'
        }`}
      >
        {dragging ? (
          // 拖进来时只说一句「松开就行」和能收哪几类：边框变虚已经在说「放下」，
          // 再弹一个大按钮反而挡住我们要放东西的地方
          <div className="pointer-events-none absolute inset-0 z-10 grid place-items-center rounded-panel bg-surface/85">
            <div className="text-center">
              <p className="text-mini font-semibold text-ink">松开即可添加</p>
              <p className="mt-0.5 text-caption text-muted">
                文档 · 图片 · 会议记录 · 录音 · 视频 · 整个文件夹
              </p>
            </div>
          </div>
        ) : null}

        {project ? (
          <div className="flex flex-wrap gap-2 px-1 pb-2">
            <div className="flex items-center gap-1.5 rounded-control border border-brand-line bg-brand-soft py-1 pr-1 pl-1.5 text-caption">
              <IconFolder size={12} className="shrink-0 text-brand" />
              <span className="shrink-0 rounded-chip bg-surface px-1 py-px text-[calc(10px*var(--font-scale))] font-semibold text-brand">
                项目
              </span>
              <span className="max-w-[13rem] truncate font-medium text-ink">{project.name}</span>
              {typeof project.fileCount === 'number' ? (
                <span className="shrink-0 text-faint">{project.fileCount} 个文档</span>
              ) : null}
              {onClearProject ? (
                <IconButton label="不带项目" className="h-5 w-5" onClick={onClearProject}>
                  <IconX size={11} />
                </IconButton>
              ) : null}
            </div>
          </div>
        ) : null}

        {uploads.length > 0 ? (
          <div className="px-1 pb-2">
            <div className="flex flex-wrap gap-2">
              {uploads.map((upload) => (
                <UploadChip
                  key={upload.local_id}
                  upload={upload}
                  onRemove={() => onRemoveUpload(upload.local_id)}
                  onRetry={onRetryUpload ? () => onRetryUpload(upload.local_id) : undefined}
                />
              ))}
            </div>
          </div>
        ) : null}

        {/* 等确认：这不是「在跑」，是「停住了等你点一下」。说清在等什么，并给一条去确认的路 */}
        {waitingApproval ? (
          <div
            role="status"
            className="mx-1 mb-2 flex items-center gap-1.5 rounded-control border border-warn-line bg-warn-soft px-2.5 py-1.5 text-caption text-warn"
          >
            <IconShield size={12} className="shrink-0" />
            <span className="min-w-0 flex-1">有一步要你确认，点了才接着做</span>
            {onOpenApproval ? (
              <button
                type="button"
                onClick={onOpenApproval}
                className="shrink-0 rounded-chip bg-surface px-1.5 py-0.5 font-medium text-warn transition-colors hover:text-ink"
              >
                去确认
              </button>
            ) : null}
          </div>
        ) : null}

        <textarea
          ref={textareaRef}
          value={value}
          rows={1}
          onChange={(event) => {
            if (hint) setHint(null);
            onChange(event.target.value);
          }}
          onKeyDown={handleKeyDown}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onCompositionEnd={() => {
            composingRef.current = false;
          }}
          disabled={disabled}
          placeholder={
            waitingApproval
              ? '先确认上一步操作，我再接着做…'
              : isStreaming
                ? '正在做，有补充就说…'
                : project
                  ? `项目「${project.name}」已就位，说说要做什么？例如：把最近修改的合同汇总成台账`
                  : uploads.length > 0
                    ? '已添加素材，说说想让我做什么？例如：按周报格式整理成 600 字'
                    : '今天帮你做些什么？例如：把这份材料整理成 600 字周报'
          }
          /*
           * 输入框「半锁」时（任务在跑 / 等审批），placeholder 其实是一条状态说明，
           * 用最淡的 faint 灰几乎看不见——按状态给品牌色 / 警示色，亮度抬一档；
           * 空闲态也从 faint 提到 muted，提示语的对比度不低于正文的辅助信息。
           */
          className={`block max-h-[11rem] min-h-[3.25rem] w-full resize-none bg-transparent px-1 pt-1 pb-2 text-regular text-ink focus:outline-none disabled:cursor-not-allowed ${
            waitingApproval
              ? 'placeholder:text-warn'
              : isStreaming
                ? 'placeholder:text-brand-strong'
                : 'placeholder:text-muted'
          }`}
          aria-label="任务输入框"
        />

        {hint ? (
          <div
            role="status"
            className={`mx-1 mb-2 flex items-start gap-1.5 rounded-control border px-2.5 py-1.5 text-caption ${
              hint.tone === 'warn'
                ? 'border-warn-line bg-warn-soft text-warn'
                : 'border-brand-line bg-brand-soft text-brand-strong'
            }`}
          >
            {hint.tone === 'warn' ? (
              <IconAlertTriangle size={12} className="mt-[1px] shrink-0" />
            ) : (
              <IconWand size={12} className="mt-[1px] shrink-0" />
            )}
            <span>{hint.text}</span>
          </div>
        ) : null}

        {/* 底部工具栏：左「+（含文件/产物格式/技能）/ 审批胶囊」，右「模型 / 语音 / 增强 / 发送」 */}
        <div className="flex flex-wrap items-center gap-1.5 px-1 pb-0.5">
          <input
            ref={fileInputRef}
            type="file"
            accept={UPLOAD_ACCEPT}
            multiple
            className="hidden"
            onChange={onPickFile}
          />

          <ComposerPlusMenu
            disabled={disabled}
            onPickFiles={openPicker}
            outputFormat={outputFormat}
            onOutputFormatChange={onOutputFormatChange}
            uploads={uploads}
            skillsPanel={skillsPanel}
            skillsSummary={skillsSummary}
            docStyle={docStyle}
            onDocStyleChange={onDocStyleChange}
          />

          {/*
           * 审批策略是安全设置，不能只藏在菜单里：紧贴加号留一个胶囊，
           * 一眼能看到「Agent 现在能自己干到什么程度」，点开也能就地改。
           * 菜单里不再重复一份——两处入口同一份状态，删掉菜单内那份反而更清楚。
           */}
          <Select
            value={approvalMode ?? 'risky'}
            options={APPROVAL_MODES.map((mode) => ({
              value: mode,
              label: APPROVAL_MODE_LABELS[mode],
              note: APPROVAL_MODE_HINTS[mode],
            }))}
            disabled={disabled}
            onChange={(next) => onApprovalModeChange?.(next as ApprovalMode)}
            ariaLabel="信任档位"
            variant="pill"
            leading={<IconShield size={11} />}
            hint="拿不准的时候拦不拦你"
          />

          <div className="ml-auto flex shrink-0 items-center gap-0.5">
            <ComposerQuickAccess
              model={model ?? null}
              isMock={Boolean(isMock)}
              blocked={Boolean(modelBlocked)}
              onModelChanged={onModelChanged}
            />
            <ComposerMic disabled={disabled} onText={(text) => onChange(`${value}${text}`)} />
            <ComposerEnhance
              text={value}
              outputFormat={outputFormat}
              disabled={disabled}
              onEnhanced={handleEnhanced}
              onNotice={setHint}
              focusInput={() => textareaRef.current?.focus()}
            />
            {/* 运行中两个动作都要在：停止当前任务，或者把这条排到下一位 */}
            {isStreaming ? (
              <Tooltip label="停止当前任务" side="top">
                <button
                  type="button"
                  aria-label="停止"
                  onClick={onStop}
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-danger-soft text-danger transition-colors hover:bg-danger-line/50"
                >
                  <IconStop size={14} />
                </button>
              </Tooltip>
            ) : null}
            <button
              type="button"
              aria-label={isStreaming ? '排队' : '发送'}
              onClick={submit}
              disabled={disabled}
              aria-disabled={!canSend}
              className={`ml-0.5 flex h-8 w-8 items-center justify-center rounded-full transition-colors duration-150 ${
                canSend
                  ? 'bg-ink text-canvas hover:bg-ink-soft active:bg-ink'
                  : 'bg-send-face text-send-ink hover:bg-send-face-hover hover:text-send-ink-hover active:bg-send-face-active'
              } disabled:cursor-not-allowed disabled:opacity-60`}
            >
              {isStreaming ? <IconClock size={15} /> : <IconArrowUp size={16} />}
            </button>
          </div>
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between gap-3 px-2 text-caption text-muted">
        {/* 这句涉及「素材会不会发出去」，必须跟着引擎状态变：
            真实模型下还写「演示环境 / 不外发」是在误导用户 */}
        <span className="flex items-center gap-2">
          <span className="hidden md:inline">
            {isStreaming ? 'Enter 排队' : 'Enter 发送'} · Shift + Enter 换行
          </span>
          <span className="hidden text-line-strong md:inline">|</span>
          <span>
            {isMock
              ? '演示环境：产物只写入本地目录，不外发'
              : '真实模型：素材会发给模型解析，产物只写入本地目录'}
          </span>
        </span>
        <span className="text-faint">Office Agent MVP</span>
      </div>
    </div>
  );
}
