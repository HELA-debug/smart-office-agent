/**
 * SSE 事件契约 v1 —— 与 docs/events.md 一一对应。
 *
 * 规则（与后端约定一致）：
 * - 所有 data 都带 `version: 1` 和 `run_id`；
 * - 只允许追加事件/字段；未知事件必须忽略；
 * - 本文件是前端唯一的事件类型来源，新增事件先在这里加类型。
 */

export const EVENT_VERSION = 1 as const;
export type EventVersion = typeof EVENT_VERSION;

/* ------------------------------------------------------------------ */
/* 1. run.started                                                      */
/* ------------------------------------------------------------------ */

export type RunMode = 'mock' | 'real';

export interface RunStartedEvent {
  version: EventVersion;
  run_id: string;
  thread_id: string;
  mode: RunMode;
  model?: string;
  started_at?: string;
  /** 可选追加字段：模型不可用时后端会提前标注降级。 */
  degraded?: boolean;
}

/* ------------------------------------------------------------------ */
/* 2/3. message.delta / message.completed                              */
/* ------------------------------------------------------------------ */

/**
 * v1.3：`channel` 区分「对话里的正式回复」和「中间旁白」。
 * process 的旁白不进气泡，收进「执行过程」折叠条（一次运行会蹦出好几段，
 * 每段都起一个带头像的气泡，一屏就全是「Office Agent」了）。
 */
export type MessageChannel = 'reply' | 'process';

export interface MessageDeltaEvent {
  version: EventVersion;
  run_id: string;
  message_id: string;
  delta: string;
  index: number;
  channel?: MessageChannel;
}

export interface MessageCompletedEvent {
  version: EventVersion;
  run_id: string;
  message_id: string;
  content: string;
  channel?: MessageChannel;
}

/* ------------------------------------------------------------------ */
/* 2.5. thinking.delta / thinking.completed（v1.2 思考过程）              */
/* ------------------------------------------------------------------ */

/**
 * v1.5：思考的「场合」。语义已经从「每轮开工的推演」收成「决策那一刻的一句话」，
 * 只有三种时候才会有：
 * - decision：它在两个方向之间做了选择；
 * - ask：它停下来等你回话；
 * - error：某一步没成，得换个法子。
 * 老事件没有这个字段，按 decision 处理。
 */
export type ThinkingKind = 'decision' | 'ask' | 'error';

export interface ThinkingDeltaEvent {
  version: EventVersion;
  run_id: string;
  message_id: string;
  delta: string;
  index: number;
  kind?: ThinkingKind;
}

export interface ThinkingCompletedEvent {
  version: EventVersion;
  run_id: string;
  message_id: string;
  content: string;
  /** 这次思考实际花的时间（毫秒）。一行字很快，不再往界面上写秒数 */
  elapsed_ms?: number;
  kind?: ThinkingKind;
}

/* ------------------------------------------------------------------ */
/* 4. plan.updated                                                     */
/* ------------------------------------------------------------------ */

export type TodoStatus = 'pending' | 'in_progress' | 'completed' | 'cancelled';

export interface PlanTodo {
  id: string;
  content: string;
  status: TodoStatus;
}

export interface PlanUpdatedEvent {
  version: EventVersion;
  run_id: string;
  todos: PlanTodo[];
}

/* ------------------------------------------------------------------ */
/* 5. tool.finished                                                    */
/* ------------------------------------------------------------------ */

export type RiskLevel = 'low' | 'medium' | 'high';

export interface ToolErrorInfo {
  code: string;
  message: string;
}

export interface ToolFinishedEvent {
  version: EventVersion;
  run_id: string;
  tool: string;
  ok: boolean;
  risk: RiskLevel;
  summary: string;
  duration_ms: number;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  artifact_id?: string | null;
  error?: ToolErrorInfo;
  /**
   * 可选的追加字段（契约允许追加、老前端忽略）：
   * 后端如果告知该工具由某个子智能体执行，前端渲染 SubagentCard。
   */
  subagent?: SubagentInfo | null;
}

/** 子智能体信息（tool.finished.subagent 的可选追加结构）。 */
export interface SubagentInfo {
  id: string;
  name: string;
  role?: string;
  status?: 'running' | 'done' | 'failed';
}

/* ------------------------------------------------------------------ */
/* 6. approval.required                                                */
/* ------------------------------------------------------------------ */

export interface ApprovalPreview {
  /** 目标（如收件人） */
  to?: string;
  subject?: string;
  body_preview?: string;
  /** 影响范围说明 */
  impact?: string;
  [key: string]: unknown;
}

export interface ApprovalRequiredEvent {
  version: EventVersion;
  run_id: string;
  approval_id: string;
  tool: string;
  risk: RiskLevel;
  message: string;
  preview: ApprovalPreview;
}

/* ------------------------------------------------------------------ */
/* 7. artifact.ready                                                   */
/* ------------------------------------------------------------------ */

export type ArtifactType = 'docx' | 'pdf' | 'txt' | 'upload';

export interface ArtifactReadyEvent {
  version: EventVersion;
  run_id: string;
  artifact_id: string;
  type: ArtifactType;
  filename: string;
  size: number;
  download_url: string;
  preview_url: string;
  /** 这份产物由哪些素材生成（来自 doc.generate_report 的 extra.sources），用于区分同名产物 */
  sources?: string[];
}

/* ------------------------------------------------------------------ */
/* 8/9. run.completed / run.failed                                     */
/* ------------------------------------------------------------------ */

export type RunStatus = 'completed' | 'rejected';

export type ApprovalDecision = 'approved' | 'rejected';

export interface ApprovalRecord {
  approval_id: string;
  tool: string;
  decision: ApprovalDecision | string;
}

export interface RunCompletedEvent {
  version: EventVersion;
  run_id: string;
  status: RunStatus;
  tokens: number;
  cost_cny: number;
  elapsed_ms: number;
  artifact_ids: string[];
  approvals: ApprovalRecord[];
  degraded: boolean;
}

export type RunErrorCode =
  | 'MODEL_TIMEOUT'
  | 'MODEL_RATE_LIMIT'
  | 'TOOL_ERROR'
  | 'FILE_PARSE_ERROR'
  | 'APPROVAL_TIMEOUT'
  | 'INTERNAL';

export interface RunErrorInfo {
  code: RunErrorCode | string;
  message: string;
  retryable?: boolean;
}

export interface RunFailedEvent {
  version: EventVersion;
  run_id: string;
  error: RunErrorInfo;
  degraded?: boolean;
}

/* ------------------------------------------------------------------ */
/* 联合类型 + 事件名表                                                 */
/* ------------------------------------------------------------------ */

export const RUN_EVENT_NAMES = [
  'run.started',
  'message.delta',
  'message.completed',
  'thinking.delta',
  'thinking.completed',
  'plan.updated',
  'tool.finished',
  'approval.required',
  'artifact.ready',
  'run.completed',
  'run.failed',
] as const;

export type RunEventName = (typeof RUN_EVENT_NAMES)[number];

/** 事件名 → data 类型的映射（一一对应 docs/events.md 第 3 节）。 */
export type RunEventMap = {
  'run.started': RunStartedEvent;
  'message.delta': MessageDeltaEvent;
  'message.completed': MessageCompletedEvent;
  'thinking.delta': ThinkingDeltaEvent;
  'thinking.completed': ThinkingCompletedEvent;
  'plan.updated': PlanUpdatedEvent;
  'tool.finished': ToolFinishedEvent;
  'approval.required': ApprovalRequiredEvent;
  'artifact.ready': ArtifactReadyEvent;
  'run.completed': RunCompletedEvent;
  'run.failed': RunFailedEvent;
};

export type RunEvent = RunEventMap[RunEventName];

/** 带事件名的解析结果（reducer 用 name 做可辨识联合）。 */
export type ParsedRunEvent = {
  [K in RunEventName]: { name: K; event: RunEventMap[K] };
}[RunEventName];

export const TERMINAL_EVENTS: readonly RunEventName[] = ['run.completed', 'run.failed'];

export const APPROVAL_TIMEOUT_MS = 180_000;

export function isKnownEventName(name: string): name is RunEventName {
  return (RUN_EVENT_NAMES as readonly string[]).includes(name);
}

export function isTerminalEventName(name: string): boolean {
  return (TERMINAL_EVENTS as readonly string[]).includes(name);
}

/**
 * 把 (event 名, 解析后的 data) 收窄成带名字的事件。
 * 版本不符 / 结构不符 / 未知事件 → null，由调用方忽略。
 */
export function parseRunEvent(name: string, data: unknown): ParsedRunEvent | null {
  if (!isKnownEventName(name)) return null;
  if (typeof data !== 'object' || data === null) return null;

  const record = data as Record<string, unknown>;
  if (record.version !== EVENT_VERSION) return null;
  if (typeof record.run_id !== 'string' || record.run_id.length === 0) return null;

  switch (name) {
    case 'run.started':
      return { name, event: data as RunStartedEvent };
    case 'message.delta':
      return { name, event: data as MessageDeltaEvent };
    case 'message.completed':
      return { name, event: data as MessageCompletedEvent };
    case 'thinking.delta':
      return { name, event: data as ThinkingDeltaEvent };
    case 'thinking.completed':
      return { name, event: data as ThinkingCompletedEvent };
    case 'plan.updated':
      return { name, event: data as PlanUpdatedEvent };
    case 'tool.finished':
      return { name, event: data as ToolFinishedEvent };
    case 'approval.required':
      return { name, event: data as ApprovalRequiredEvent };
    case 'artifact.ready':
      return { name, event: data as ArtifactReadyEvent };
    case 'run.completed':
      return { name, event: data as RunCompletedEvent };
    case 'run.failed':
      return { name, event: data as RunFailedEvent };
    default:
      return null;
  }
}
