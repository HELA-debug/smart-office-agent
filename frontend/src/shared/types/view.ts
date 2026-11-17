/**
 * 跨 feature 共享的视图模型（纯数据，不含行为）。
 *
 * 这些类型描述"后端事件/接口数据如何在前端呈现"，
 * 供 features/runs、features/artifacts、features/audit 的展示组件与
 * features/workbench 的状态机共用，避免组件反向依赖某个 feature 的内部状态。
 */
import type {
  ApprovalDecision,
  ApprovalPreview,
  ApprovalRecord,
  ArtifactType,
  PlanTodo,
  RiskLevel,
  RunStatus,
  SubagentInfo,
  ToolErrorInfo,
} from './events';
import type { AuditOut } from '../api/types';

/* ------------------------------------------------------------------ */
/* 运行过程（计划 / 工具 / 子智能体 / 审批）                            */
/* ------------------------------------------------------------------ */

export interface PlanSnapshot {
  run_id: string;
  todos: PlanTodo[];
  updated_at: string;
}

export interface ToolCallItem {
  id: string;
  run_id: string;
  tool: string;
  ok: boolean;
  /** 有意跳过（门控没放行 / 等不到审批）：不是故障，别按失败渲染。 */
  skipped?: boolean;
  risk: RiskLevel;
  summary: string;
  duration_ms: number;
  input?: Record<string, unknown> | null;
  output?: Record<string, unknown> | null;
  artifact_id?: string | null;
  error?: ToolErrorInfo;
  subagent?: SubagentInfo | null;
  created_at: string;
}

export interface SubagentItem {
  id: string;
  name: string;
  role?: string;
  status: 'running' | 'done' | 'failed';
  summary?: string;
  tools: string[];
  updated_at: string;
}

export interface ApprovalItem {
  approval_id: string;
  run_id: string;
  tool: string;
  risk: RiskLevel;
  message: string;
  preview: ApprovalPreview;
  created_at: string;
  decision: ApprovalDecision | null;
  submitting: boolean;
  error: string | null;
  decided_at?: string;
}

/* ------------------------------------------------------------------ */
/* 产物与审计                                                          */
/* ------------------------------------------------------------------ */

export interface ArtifactItem {
  artifact_id: string;
  type: ArtifactType | string;
  filename: string;
  size: number;
  download_url: string;
  preview_url: string;
  run_id?: string;
  created_at: string;
  /** 产出这一份产物的那次运行花了多少（运行结束时才知道，历史产物可能为空） */
  tokens?: number;
  cost_cny?: number;
  /** 由哪些素材生成：同一天出多份摘要时，靠它说明「这一份是哪一份」 */
  sources?: string[];
  meta_status: 'idle' | 'loading' | 'ready' | 'error';
  meta_error: string | null;
  meta?: {
    sha256?: string;
    created_at?: string;
  } | null;
}

export interface AuditViewState {
  open: boolean;
  status: 'idle' | 'loading' | 'ready' | 'error';
  data: AuditOut | null;
  error: string | null;
}

/* ------------------------------------------------------------------ */
/* 用量摘要                                                            */
/* ------------------------------------------------------------------ */

export interface UsageSummary {
  run_id: string;
  status: RunStatus;
  tokens: number;
  cost_cny: number;
  elapsed_ms: number;
  artifact_ids: string[];
  approvals: ApprovalRecord[];
  degraded: boolean;
}
