import { UPLOAD_FORMATS } from '../../../shared/config/output-formats';
import { IconPaperclip, IconWand } from '../../../shared/ui/Icons';

export function EmptyState({
  onUploadRequest,
  mock,
}: {
  onUploadRequest: () => void;
  /** 当前跑的是不是演示引擎：这句话涉及「素材会不会发出去」，不能写死 */
  mock: boolean;
}) {
  // my-auto：空间富余时垂直居中，空间不足时自动退化为顶部对齐（不会被裁掉上半截）
  return (
    <div className="empty-hero my-auto flex flex-col items-center px-4">
      <div className="empty-hero__head flex flex-col items-center">
        <div className="empty-hero__icon flex items-center justify-center rounded-2xl bg-gradient-to-br from-[#3b82f6] to-[#1d4ed8] text-white shadow-card">
          <IconWand size={22} />
        </div>
        <h1 className="empty-hero__title text-pretty text-display font-semibold tracking-tight text-ink">
          把一份材料，变成可交付的文档
        </h1>
      </div>
      <p className="empty-hero__lead max-w-[27.5rem] text-center text-mini text-muted">
        上传素材，说一句想要什么。Agent 会先给出计划，逐步执行工具调用，并在高风险动作前请你确认。
      </p>

      <div className="empty-hero__block w-full max-w-[28.75rem]">
        <button
          type="button"
          onClick={onUploadRequest}
          className="group flex w-full flex-col items-start gap-1 rounded-card border border-line bg-surface px-3.5 py-3 text-left shadow-card transition-all duration-150 hover:border-brand-border hover:bg-brand-soft/70 hover:shadow-pop active:bg-brand-soft"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-control bg-surface-sunken text-muted transition-colors group-hover:bg-brand-solid group-hover:text-white">
            <IconPaperclip size={15} />
          </span>
          <span className="mt-1 text-mini font-semibold text-ink transition-colors group-hover:text-brand-strong">
            上传素材
          </span>
          <span className="text-caption text-faint transition-colors group-hover:text-ink-soft">
            <span className="text-ink-soft">
              图片 · 会议记录 · 会议录音 · 会议视频（会先识别成文字）
            </span>
            <br />
            {UPLOAD_FORMATS.join(' / ')}
          </span>
        </button>
      </div>

      {/* items-start + 圆点自带留白：窄屏这句会折成两行，居中排会把圆点挤到中间那一行，
          看着像个列表符号 */}
      <div className="empty-hero__foot flex items-start gap-1.5 text-caption text-faint">
        <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-faint" />
        {mock
          ? '演示模式（不联网）：产物只保存在本机目录，不会外发'
          : '真实模型：素材会发送给模型解析，产物只写进本机目录'}
      </div>
    </div>
  );
}
