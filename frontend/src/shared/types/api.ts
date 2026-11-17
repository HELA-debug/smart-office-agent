/**
 * HTTP 接口的数据结构 —— 与 docs/api.md 对应。
 * 后端可能追加字段，前端只读取这里声明过的字段。
 */
import type { ApprovalDecision, ArtifactType } from './events';

/** 所有 JSON 响应顶层的 trace_id。 */
export interface Traced {
  trace_id?: string;
}

/** 统一返回值：数据 + trace_id（错误时 trace 挂在 ApiError 上）。 */
export interface ApiResponse<T> {
  data: T;
  traceId: string | null;
}

/* ------------------------------------------------------------------ */
/* 健康检查                                                            */
/* ------------------------------------------------------------------ */

export interface HealthResponse extends Traced {
  status?: string;
  mode?: 'mock' | 'real';
  version?: string;
  model?: string;
  /** 后端进程启动时载入的提交。 */
  git_sha?: string;
  /** 仓库当前 HEAD；比 git_sha 新说明后端进程该重启了。 */
  git_sha_live?: string;
}

/* ------------------------------------------------------------------ */
/* 会话                                                                */
/* ------------------------------------------------------------------ */

export interface ThreadSummary extends Traced {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  /** v1 新增：置顶标记。 */
  pinned?: boolean;
  message_count: number;
  artifact_count: number;
}

export interface ThreadHistoryMessage {
  message_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string;
}

export interface ThreadArtifact {
  artifact_id: string;
  /** 后端 `Artifact.to_dict()` 用 artifact_type，事件里用 type，两者都兼容。 */
  artifact_type?: string;
  type?: string;
  filename: string;
  size: number;
  sha256?: string;
  created_at?: string;
  download_url?: string;
  preview_url?: string;
  run_id?: string | null;
  extra?: Record<string, unknown> | null;
}

export interface ThreadApproval {
  approval_id: string;
  run_id?: string | null;
  tool: string;
  /** 后端存的是 payload；事件里叫 preview。 */
  payload?: Record<string, unknown> | null;
  preview?: Record<string, unknown> | null;
  decision?: 'approved' | 'rejected' | null;
  comment?: string | null;
  created_at?: string;
  decided_at?: string | null;
}

export interface ThreadDetail extends ThreadSummary {
  /** 历史消息为可选字段（后端如未实现则前端只显示空提示）。 */
  messages?: ThreadHistoryMessage[];
  artifacts?: ThreadArtifact[];
  approvals?: ThreadApproval[];
}

export interface CreateThreadRequest {
  title?: string;
}

/* ------------------------------------------------------------------ */
/* 上传                                                                */
/* ------------------------------------------------------------------ */

/** 媒体素材的识别状态（与后端 MediaStatusOut 一致）。 */
export interface MediaStatus {
  kind: 'image' | 'transcript' | 'audio' | 'video' | string;
  label?: string;
  status: 'processing' | 'ready' | 'failed' | string;
  error?: string;
  retryable?: boolean;
  meta?: {
    duration?: number;
    segments?: number;
    model?: string;
    language?: string;
    lines?: number;
    [key: string]: unknown;
  };
}

export interface UploadResponse extends Traced {
  file_id: string;
  artifact_id?: string;
  filename: string;
  size: number;
  type?: string;
  chars?: number;
  parsed?: boolean;
  /** processing = 识别中（图片 OCR / 录音转写），ready = 可用，failed = 识别失败 */
  status?: 'processing' | 'ready' | 'failed' | string;
  /** 收下了但读不出文字时的说明（旧版 .doc、压缩包…），此时 parsed 为 false */
  note?: string | null;
  media?: MediaStatus | null;
  ext?: string;
  /** 解析文本的前 200 字预览（素材卡片在会话恢复后靠它显示正文开头） */
  text_preview?: string;
}

export interface ThreadFile extends UploadResponse {
  created_at?: string;
}

/* ------------------------------------------------------------------ */
/* 审批                                                                */
/* ------------------------------------------------------------------ */

export interface SubmitApprovalRequest {
  decision: ApprovalDecision;
  comment?: string;
}

export interface SubmitApprovalResponse extends Traced {
  approval_id: string;
  decision: ApprovalDecision;
  decided_at: string;
  resumed: boolean;
}

/* ------------------------------------------------------------------ */
/* 审计                                                                */
/* ------------------------------------------------------------------ */

export interface AuditRun extends Traced {
  run_id: string;
  started_at?: string;
  finished_at?: string;
  status?: string;
  tokens?: number;
  cost_cny?: number;
  elapsed_ms?: number;
  approvals?: Array<{
    approval_id: string;
    tool: string;
    decision: string;
    decided_at?: string;
  }>;
  artifacts?: Array<{
    artifact_id: string;
    type?: ArtifactType | string;
    filename?: string;
  }>;
}

export interface AuditResponse extends Traced {
  thread_id: string;
  runs: AuditRun[];
}

/* ------------------------------------------------------------------ */
/* 产物                                                                */
/* ------------------------------------------------------------------ */

export interface ArtifactMeta extends Traced {
  artifact_id: string;
  type: ArtifactType | string;
  filename: string;
  size: number;
  sha256?: string;
  created_at?: string;
  download_url: string;
  preview_url: string;
  thread_id?: string;
  run_id?: string;
}

/* ------------------------------------------------------------------ */
/* 错误                                                                */
/* ------------------------------------------------------------------ */

export interface ApiErrorEnvelope extends Traced {
  error: {
    code: string;
    message: string;
  };
}

/** 上传支持的扩展名（与 api.md 2.2 对齐，pdf 为可选依赖）。 */
export const SUPPORTED_UPLOAD_EXTENSIONS = ['.docx', '.txt', '.md', '.csv', '.pdf'] as const;
