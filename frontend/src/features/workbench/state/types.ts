/**
 * 工作台状态机（计划书 6.3 / api.md 第 4 节）。
 *
 * 状态：idle → streaming → waiting_approval → done / error
 * 规则：只有 reducer 能改状态；组件只读 state，不自行猜测运行进度。
 * 事件驱动的迁移：
 *   run.started        → streaming
 *   approval.required  → waiting_approval
 *   run.completed      → done
 *   run.failed         → error
 *   审批 POST 成功      → streaming（connection 始终保持打开）
 */
import type { AuditOut } from '../../../shared/api/types';
import type { ThreadSummary, ThreadFile, UploadResponse } from '../../../shared/types/api';
import type {
  ApprovalDecision,
  ParsedRunEvent,
  RunErrorInfo,
  RunMode,
  ThinkingKind,
} from '../../../shared/types/events';
import type {
  ApprovalItem,
  ArtifactItem,
  AuditViewState,
  PlanSnapshot,
  SubagentItem,
  ToolCallItem,
  UsageSummary,
} from '../../../shared/types/view';

// 视图模型定义在 shared/types/view（跨 feature 共用）；这里再导出，
// 供 workbench 内部组件继续从 state 模块引入。
export type {
  ApprovalItem,
  ArtifactItem,
  PlanSnapshot,
  SubagentItem,
  ToolCallItem,
  UsageSummary,
} from '../../../shared/types/view';

/* ------------------------------------------------------------------ */
/* 状态类型                                                            */
/* ------------------------------------------------------------------ */

export type WorkbenchStatus = 'idle' | 'streaming' | 'waiting_approval' | 'done' | 'error';

export type ConnectionState = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  streaming: boolean;
  created_at: string;
}

/**
 * 决策行（v1.5，沿用 thinking.* 事件）。
 *
 * 语义已经不是「每轮开工先想一遍」，而是「需要判断的时候说一句」：
 * 挑了哪个方向 / 停下来问你 / 某一步没成。所以界面上它是一行字，不是一块面板。
 */
export interface ThinkingItem {
  id: string;
  content: string;
  streaming: boolean;
  /** 完成后折叠，用户可手动展开（老的长思考才有这块） */
  collapsed: boolean;
  /** 这句话属于哪种场合；老事件没有这个字段 */
  kind?: ThinkingKind;
  /** 思考耗时（毫秒） */
  elapsed_ms?: number;
  created_at: string;
}

/**
 * 中间旁白（v1.3 message.* 的 channel=process）。
 *
 * 跟消息的区别只在展示位置：不进对话气泡、不带头像，而是收进「执行过程」。
 * 一次运行常有「先读素材 → 看结构 → 换模板 → 出稿」几段旁白，全按气泡渲染时
 * 每条都带一遍「Office Agent + 时间」，一屏全是抬头，正文反而没了。
 */
export interface NoteItem {
  id: string;
  content: string;
  streaming: boolean;
  created_at: string;
}

export type TimelineItem =
  | { kind: 'message'; id: string; message: ChatMessage }
  | { kind: 'note'; id: string; note: NoteItem }
  | { kind: 'thinking'; id: string; thinking: ThinkingItem }
  | { kind: 'plan'; id: string; plan: PlanSnapshot }
  | { kind: 'tool'; id: string; tool: ToolCallItem }
  | { kind: 'subagent'; id: string; subagent: SubagentItem };

export interface UploadItem {
  local_id: string;
  filename: string;
  size: number;
  /**
   * staged = 还没开会话，文件只留在本地队列里等任务提交（避免「选文件就凭空多一个会话」）。
   * 提交任务时才会真正上传。
   */
  status: 'staged' | 'uploading' | 'parsed' | 'error';
  /** 0-100 上传进度（XHR progress）。 */
  progress?: number;
  chars?: number;
  /** 解析预览（前 200 字，来自 preview 端点）。 */
  preview?: string | null;
  file_id?: string;
  artifact_id?: string;
  ext?: string;
  error: string | null;
  /**
   * 文件收下了、但里面的文字读不出来（旧版 .doc、压缩包、二进制）。
   * 和 error 分开：这不是失败——文件确实在素材里，只是模型读不到内容。
   */
  note?: string | null;
  /** 媒体类别（图片 / 会议记录 / 会议录音 / 会议视频）；文档为空 */
  media_kind?: 'image' | 'transcript' | 'audio' | 'video' | string;
  /** 识别状态：processing 识别中 / ready 可用 / failed 失败（reducer 与轮询都会写） */
  media_status?: 'processing' | 'ready' | 'failed' | string;
  media_error?: string;
  /** 识别结果的元信息：转写时长、句数、模型名 */
  media_meta?: Record<string, unknown>;
  /** staged 状态下暂存的原始文件；上传成功后即释放。 */
  file?: File;
}

/**
 * 排队中的任务。
 *
 * 上一轮还在跑时按下发送：不丢掉这条消息，而是连同样式化参数一起排进队列，
 * 等当前任务结束自动接着执行（对齐聊天工具的「预处理」体验）。
 */
export interface QueuedMessage {
  id: string;
  /** 入队时所在的会话：切走再回来仍能发回原会话，不会被别的会话顺手带走 */
  threadId: string;
  text: string;
  output_format?: string;
  /** 这条消息跟着走的文档格式设置（入队时一起拍下来，别让它串到下一条） */
  doc_style?: Record<string, unknown>;
  project?: { id: string; name?: string; files?: string[] } | null;
  approval_mode?: string;
  /** 跟着这条消息走的素材（入队时从输入区搬过来，下一条不会再带上） */
  uploads: UploadItem[];
  created_at: string;
}

export interface HealthState {
  status: 'unknown' | 'ok' | 'unreachable';
  mode: RunMode | null;
  version?: string;
  checked_at: string | null;
  /** 配置的引擎（设置页下拉里的值） */
  engine?: string;
  /** 实际生效的引擎：没 Key / 探测失败时会和 engine 不同 */
  engineEffective?: string;
  /** 两者不同时，后端给的人话原因（谁挡住的：开关、缺 Key、还是探测失败） */
  engineReason?: string;
  /** 发送门禁：false = 一个能用的模型都没有（演示模式恒为 true） */
  modelReady?: boolean;
  /** modelReady=false 时的引导文案（怎么把模型配上） */
  modelHint?: string;
}

export interface Notice {
  kind: 'info' | 'error';
  text: string;
  traceId?: string | null;
}

export interface WorkbenchState {
  status: WorkbenchStatus;
  threadId: string | null;
  threadTitle: string;
  sessions: ThreadSummary[];
  sessionsMeta: { page: number; pageSize: number; total: number };
  sessionsStatus: 'idle' | 'loading' | 'ready' | 'error';
  sessionsError: string | null;
  timeline: TimelineItem[];
  plan: PlanSnapshot | null;
  approvals: ApprovalItem[];
  artifacts: ArtifactItem[];
  /** 输入框里待发的附件：只放用户刚挑、还没发出去的文件。
   *  跑完一轮就清空——素材已经进了会话，再挂在输入框里像「还没发」。 */
  uploads: UploadItem[];
  /** 会话里已有的素材（服务端 uploads）：右栏「本次素材」用，永远不进输入框 */
  threadUploads: UploadItem[];
  subagents: SubagentItem[];
  runId: string | null;
  mode: RunMode | null;
  model: string | null;
  degraded: boolean;
  /** 降级原因（来自 /health）；有值说明真实模型没打通 */
  degradedReason: string;
  usage: UsageSummary | null;
  /** 历史会话最近一次运行的用量（来自审计），只在没有实时 usage 时兜底右栏 */
  runError: RunErrorInfo | null;
  connection: ConnectionState;
  health: HealthState;
  notice: Notice | null;
  audit: AuditViewState;
  lastUserMessage: string | null;
  /** 排队中的任务：当前任务结束后按顺序自动执行 */
  queue: QueuedMessage[];
  /** 用户主动「停止」后队列暂停，避免刚点停止它又自己跑起来 */
  queuePaused: boolean;
}

export function createInitialState(): WorkbenchState {
  return {
    status: 'idle',
    threadId: null,
    threadTitle: '新的会话',
    sessions: [],
    sessionsMeta: { page: 1, pageSize: 8, total: 0 },
    sessionsStatus: 'loading',
    sessionsError: null,
    timeline: [],
    plan: null,
    approvals: [],
    artifacts: [],
    uploads: [],
    threadUploads: [],
    subagents: [],
    runId: null,
    mode: null,
    model: null,
    degraded: false,
    degradedReason: '',
    usage: null,
    runError: null,
    connection: 'idle',
    health: { status: 'unknown', mode: null, checked_at: null },
    notice: null,
    audit: { open: false, status: 'idle', data: null, error: null },
    lastUserMessage: null,
    queue: [],
    queuePaused: false,
  };
}

/* ------------------------------------------------------------------ */
/* Actions                                                             */
/* ------------------------------------------------------------------ */

export type WorkbenchAction =
  | {
      type: 'health/checked';
      status: HealthState['status'];
      mode: RunMode | null;
      /** 后端此刻真正在用的模型名；没有就传 null（界面显示「选择模型」） */
      model?: string | null;
      /** /health 的 degraded / degraded_reason：区分「真在调模型」和「已降级到本地模拟」 */
      degraded?: boolean;
      degradedReason?: string;
      version?: string;
      /** 引擎三件套：配置值 / 实际生效值 / 原因，用于「两处不一致」时解释 */
      engine?: string;
      engineEffective?: string;
      engineReason?: string;
      /** 发送门禁：false = 一个能用的模型都没有（演示模式恒 true），界面应拦住发送 */
      modelReady?: boolean;
      modelHint?: string;
      at: string;
    }
  | { type: 'sessions/loading' }
  | {
      type: 'sessions/loaded';
      sessions: ThreadSummary[];
      meta?: { page: number; pageSize: number; total: number };
    }
  | { type: 'sessions/upsert'; thread: ThreadSummary }
  | { type: 'sessions/removed'; threadId: string }
  | { type: 'sessions/removedMany'; threadIds: string[] }
  | { type: 'sessions/reordered'; threadIds: string[] }
  | { type: 'sessions/error'; message: string }
  | { type: 'thread/new' }
  | { type: 'thread/created'; thread: ThreadSummary }
  | {
      type: 'thread/selected';
      threadId: string;
      title: string;
      history: ChatMessage[];
      artifacts?: ArtifactItem[];
      approvals?: ApprovalItem[];
      /** 历史会话自带的素材：进 threadUploads（右栏用），不进输入框 */
      threadUploads?: UploadItem[];
      /** 历史会话最近一次运行（审计里带回来），没有就不传 */
    }
  | { type: 'thread/title'; title: string }
  /** 只换产物与素材，不动对话与状态：跑完一轮后补拉用，避免整条时间线被重置 */
  | {
      type: 'thread/assets';
      artifacts: ArtifactItem[];
      threadUploads?: UploadItem[];
    }
  | { type: 'notice'; notice: Notice | null }
  | { type: 'run/begin'; threadId: string; message: string; at: string }
  | { type: 'run/connection'; connection: ConnectionState }
  | { type: 'run/event'; parsed: ParsedRunEvent; frameId: string | null; at: string }
  | { type: 'run/stopped'; at: string }
  | { type: 'run/failed'; error: RunErrorInfo; at: string }
  | { type: 'run/streamClosed'; at: string }
  | { type: 'approval/submitting'; approvalId: string }
  | { type: 'approval/decided'; approvalId: string; decision: ApprovalDecision; at: string }
  | { type: 'approval/error'; approvalId: string; message: string }
  | { type: 'upload/start'; item: UploadItem }
  | { type: 'upload/begin'; localId: string }
  | { type: 'upload/progress'; localId: string; progress: number }
  | { type: 'upload/preview'; localId: string; preview: string }
  | { type: 'upload/success'; localId: string; response: UploadResponse }
  /** 识别状态回写：轮询 /threads/{id}/files 拿到最新结果后同步到卡片上 */
  | { type: 'upload/sync'; files: ThreadFile[] }
  /** 点了「重试」：卡片先回到识别中，结果仍由轮询带回来 */
  | { type: 'upload/retry'; localId: string }
  | { type: 'upload/error'; localId: string; message: string }
  | { type: 'upload/remove'; localId: string }
  | { type: 'queue/add'; item: QueuedMessage }
  | { type: 'queue/remove'; id: string }
  /** 优先执行：把这条挪到队首（同时解除暂停），下一条就先跑它 */
  | { type: 'queue/promote'; id: string }
  /** 编辑排队任务：把它的素材还给输入区，用户改完再发 */
  | { type: 'queue/returnUploads'; uploads: UploadItem[] }
  | { type: 'queue/pause' }
  | { type: 'queue/resume' }
  | { type: 'artifact/metaLoading'; artifactId: string }
  | { type: 'artifact/meta'; artifactId: string; sha256?: string; createdAt?: string }
  | { type: 'artifact/metaError'; artifactId: string; message: string }
  | { type: 'audit/open' }
  | { type: 'audit/loading' }
  | { type: 'audit/loaded'; data: AuditOut }
  | { type: 'audit/error'; message: string }
  | { type: 'audit/close' };
