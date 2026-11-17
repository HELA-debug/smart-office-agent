/**
 * 后端 DTO → 视图模型 的纯映射。
 *
 * 从 useWorkbench.ts 拆出（P2-14）：这些函数不读 React 状态、不产生副作用，
 * 单独放一处便于直接单测，也让控制器只保留流程编排。
 */
import { artifactsApi } from '../../artifacts';
import type { ApprovalItem, ArtifactItem, ChatMessage, UploadItem } from './workbench';
import type { ApprovalOut, ArtifactOut, ThreadDetailEnvelope } from '../../../shared/api/types';
import type { ApprovalPreview, RunErrorInfo, RunMode } from '../../../shared/types/events';

/** 会话标题摘要：取任务首行前 20 字，超出省略。 */
export function summarizeTitle(message: string): string {
  const firstLine = message.trim().split('\n')[0] ?? '';
  return firstLine.length > 20 ? `${firstLine.slice(0, 20)}…` : firstLine;
}

export function normalizeRunMode(value: string | null | undefined): RunMode | null {
  return value === 'mock' || value === 'real' ? value : null;
}

export function toHistoryMessages(detail: ThreadDetailEnvelope): ChatMessage[] {
  const messages = Array.isArray(detail.messages) ? detail.messages : [];
  return messages
    .filter(
      (message) =>
        (message.role as string) !== 'run_summary' && typeof message.content === 'string',
    )
    .map((message, index) => ({
      id: message.message_id ?? `hist_${index}`,
      role:
        message.role === 'user'
          ? ('user' as const)
          : message.role === 'assistant'
            ? ('assistant' as const)
            : ('system' as const),
      content: message.content,
      streaming: false,
      created_at: message.created_at ?? new Date().toISOString(),
    }));
}

/**
 * 会话详情里的产物/素材 → 右栏数据。
 *
 * `threadUploads` 是**会话自带**的素材，只给右栏用：它不是「待发的附件」，
 * 不能被塞回输入框（否则跑完一轮、刷新或切回会话时，素材 chip 又挂在输入框里，
 * 看着像还没发出去）。
 */
export function toThreadAssets(detail: ThreadDetailEnvelope): {
  artifacts: ArtifactItem[];
  threadUploads: UploadItem[];
} {
  const now = new Date().toISOString();
  const artifacts: ArtifactItem[] = [];
  const uploads: UploadItem[] = (detail.uploads ?? []).map((raw) => ({
    local_id: raw.artifact_id,
    filename: raw.filename ?? '素材',
    size: raw.size ?? 0,
    // 注意别把「识别中」画成失败：图片 OCR、录音转写要几分钟，
    // 这三种状态在卡片上是三件事（转圈 / 字数 / 重试），不能都算 error
    status: raw.media?.status === 'failed' ? 'error' : 'parsed',
    chars: raw.chars ?? undefined,
    file_id: raw.file_id ?? raw.artifact_id,
    ext: raw.ext || undefined,
    media_kind: raw.media?.kind,
    media_status: raw.media?.status,
    media_error: raw.media?.error,
    media_meta: raw.media?.meta as Record<string, unknown> | undefined,
    note: raw.note ?? null,
    error: raw.media?.status === 'failed' ? (raw.media.error ?? '识别失败') : null,
  }));

  for (const raw of (detail.artifacts ?? []) as ArtifactOut[]) {
    if (!raw?.artifact_id) continue;
    const type = String(raw.type ?? 'file');
    if (type === 'upload') {
      // 老快照（detail.uploads 还没上线时）靠产物列表兜底，别让素材凭空消失
      if (uploads.length === 0) {
        const extra = raw.extra ?? {};
        uploads.push({
          local_id: raw.artifact_id,
          filename: raw.filename ?? '素材',
          size: raw.size ?? 0,
          status: 'parsed',
          chars: typeof extra.chars === 'number' ? extra.chars : undefined,
          file_id: raw.artifact_id,
          ext: typeof extra.ext === 'string' ? extra.ext : undefined,
          error: null,
        });
      }
      continue;
    }
    artifacts.push({
      artifact_id: raw.artifact_id,
      type,
      filename: raw.filename ?? '产物',
      size: raw.size ?? 0,
      download_url: raw.download_url ?? artifactsApi.artifactDownloadUrl(raw.artifact_id),
      preview_url: raw.preview_url ?? artifactsApi.artifactPreviewUrl(raw.artifact_id),
      run_id: raw.run_id ?? undefined,
      created_at: raw.created_at ?? now,
      meta_status: 'idle',
      meta_error: null,
      meta: raw.sha256 ? { sha256: raw.sha256, created_at: raw.created_at } : null,
      // 快照里带着生成时的素材来源，历史产物也能说明「这一份是哪一份」
      sources: Array.isArray(raw.sources)
        ? raw.sources.map((name) => String(name)).filter(Boolean)
        : [],
    });
  }

  return { artifacts, threadUploads: uploads };
}

/** 审计接口里的审批记录 → 右栏历史审批。 */
export function toApprovalItems(approvals: ApprovalOut[]): ApprovalItem[] {
  const now = new Date().toISOString();
  return approvals
    .filter((raw) => raw.decision === 'approved' || raw.decision === 'rejected')
    .map((raw) => ({
      approval_id: raw.approval_id,
      run_id: raw.run_id ?? '',
      tool: raw.tool,
      risk:
        raw.tool === 'doc.generate_report' ||
        raw.tool === 'file.delete' ||
        raw.tool === 'code.run_python'
          ? ('high' as const)
          : ('medium' as const),
      message: '历史审批记录',
      preview: (raw.payload ?? {}) as ApprovalPreview,
      created_at: raw.created_at ?? now,
      decision: raw.decision === 'approved' ? ('approved' as const) : ('rejected' as const),
      submitting: false,
      error: null,
      decided_at: raw.decided_at ?? undefined,
    }));
}

export function failureToError(failure: {
  code: string;
  message: string;
  retryable: boolean;
}): RunErrorInfo {
  return { code: failure.code, message: failure.message, retryable: failure.retryable };
}
