/**
 * 本地 mock 事件流（仅 `?mock=1` / `VITE_MOCK=1` 时启用）。
 *
 * 目的有两个：
 * 1. 后端尚未就绪时也能验证 UI（审批卡、产物卡、用量摘要）；
 * 2. 演示兜底：事件序列与 docs/events.md 完全一致，走同一套 reducer。
 *
 * 注意：这是 fixture，不是"假后端"——非流式接口（建会话/上传/审批/审计）
 * 在这里也有一份内存实现，保证主链路能点通。
 */
import { OUTPUT_FORMAT_LABELS, isOutputFormat } from '../config/output-formats';
import { EVENT_VERSION } from '../types/events';
import type { RunStreamHandlers, RunStreamInput } from './sse';
import type { OutputFormat } from '../config/output-formats';
import type {
  ApiResponse,
  ArtifactMeta,
  AuditResponse,
  AuditRun,
  HealthResponse,
  ThreadDetail,
  ThreadFile,
  ThreadSummary,
  UploadResponse,
} from '../types/api';
import type { ApprovalDecision, ThinkingKind } from '../types/events';
import type { ToolFinishedEvent, TodoStatus } from '../types/events';

/* ------------------------------------------------------------------ */
/* 内存态                                                              */
/* ------------------------------------------------------------------ */

const mockThreads: ThreadSummary[] = [];
const mockArtifacts = new Map<string, ArtifactMeta>();
let threadSeq = 0;
let lastAuditRun: AuditRun | null = null;
let lastAuditThreadId: string | null = null;

const pendingApprovals = new Map<string, (decision: ApprovalDecision) => void>();

const nowIso = () => new Date().toISOString();
const traceId = () => `mock-trace-${Date.now().toString(36)}`;

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/* ------------------------------------------------------------------ */
/* 预览 HTML（DOCX 预览的 fixture）                                    */
/* ------------------------------------------------------------------ */

const MOCK_REPORT_HTML = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<style>
  /* 版式对齐真实产物：黑色居中大标题、灰色副标题、浅灰表头、正文首行缩进两格。
     演示里长什么样，用户就以为交付件长什么样——所以这里不能比真文档好看，
     也不能比它花哨（蓝线、彩色标题那种「PPT 味」不是我们要交的东西）。 */
  body{margin:0;padding:30px 34px;font-family:"Microsoft YaHei","PingFang SC",system-ui,sans-serif;color:#33383f;font-size:13.5px;line-height:1.75;background:#fff}
  h1{font-size:23px;margin:0 0 6px;font-weight:600;color:#1f2328;letter-spacing:.2px;text-align:center}
  .lead{color:#6b7280;font-size:13px;margin:0 0 24px;text-align:center}
  h2{font-size:16px;margin:26px 0 8px;color:#1f2328;font-weight:600}
  p{margin:0 0 10px;text-indent:2em}
  ul,ol{margin:0 0 10px;padding-left:20px}
  li{margin:0 0 5px}
  table{border-collapse:collapse;width:100%;margin:6px 0 16px;font-size:12.5px}
  th,td{border:1px solid #d0d5dd;padding:7px 10px;text-align:left;vertical-align:top}
  th{background:#f2f4f7;color:#1f2328;font-weight:600}
  .sign{margin-top:26px;color:#6b7280;font-size:12px;text-indent:0}
</style></head>
<body>
  <h1>本周工作周报（2026-W43）</h1>
  <div class="lead">Office Agent 主链路 · 结论先行</div>
  <h2>一、一句话结论</h2>
  <p>毛胚前后端主链路已按事件契约跑通，本周完成 3 项交付、2 项风险仍在；下周若不补齐 DOCX 模板变量，下载审计这条链路无法验收。</p>
  <h2>二、进度：做了什么、走到哪一步</h2>
  <table>
    <tr><th>事项</th><th>本周结果</th><th>口径与待补</th></tr>
    <tr><td>前后端主链路联调</td><td>完成</td><td>SSE 事件流按 v1.1 契约跑通，覆盖 9 类事件</td></tr>
    <tr><td>会议记录整理</td><td>完成</td><td>2 份素材提炼 6 条待办，4 条已闭环</td></tr>
    <tr><td>周报模板 v1</td><td>完成</td><td>覆盖进展、风险、下周计划三段式结构</td></tr>
  </table>
  <h2>三、风险与问题</h2>
  <ol>
    <li>真实模型额度有限——演示阶段统一走 mock 引擎，真实链路未按周验证。</li>
    <li>产物只写入本地产物目录、不外发，收件人需要另行转交。</li>
  </ol>
  <h2>四、下周计划</h2>
  <ul>
    <li>补齐 DOCX 模板变量与下载审计：交付物为可复跑的验收用例。</li>
    <li>把子智能体占位替换为真实检索实现：验收口径待评估后补。</li>
  </ul>
  <p class="sign">本文件由 Office Agent 生成，请审核后使用。</p>
</body></html>`;

function mockPreviewUrl(): string {
  return `data:text/html;charset=utf-8,${encodeURIComponent(MOCK_REPORT_HTML)}`;
}

/* ------------------------------------------------------------------ */
/* 非流式接口的 mock 实现                                              */
/* ------------------------------------------------------------------ */

export function mockHealth(): ApiResponse<HealthResponse> {
  return {
    data: { status: 'ok', mode: 'mock', version: 'mock-0.1.0', model: 'mock-scripted' },
    traceId: traceId(),
  };
}

export function mockListThreads(): ApiResponse<ThreadSummary[]> {
  return {
    data: [...mockThreads].sort((a, b) => b.updated_at.localeCompare(a.updated_at)),
    traceId: traceId(),
  };
}

export function mockCreateThread(title?: string): ApiResponse<ThreadSummary> {
  threadSeq += 1;
  const thread: ThreadSummary = {
    thread_id: `th_mock_${String(threadSeq).padStart(3, '0')}`,
    title: title?.trim() || '新的会话',
    created_at: nowIso(),
    updated_at: nowIso(),
    message_count: 0,
    artifact_count: 0,
  };
  mockThreads.unshift(thread);
  return { data: thread, traceId: traceId() };
}

export function mockGetThread(threadId: string): ApiResponse<ThreadDetail> {
  const thread = mockThreads.find((item) => item.thread_id === threadId);
  if (!thread) {
    return {
      data: { ...mockCreateThread('演示会话').data, messages: [] },
      traceId: traceId(),
    };
  }
  return { data: { ...thread, messages: [] }, traceId: traceId() };
}

function touchMockThread(threadId: string, messageCount: number, artifactCount: number): void {
  const thread = mockThreads.find((item) => item.thread_id === threadId);
  if (!thread) return;
  thread.updated_at = nowIso();
  thread.message_count = messageCount;
  thread.artifact_count = artifactCount;
}

export function mockListFiles(): ApiResponse<ThreadFile[]> {
  return { data: [], traceId: traceId() };
}

export async function mockUploadFile(
  _threadId: string,
  file: File,
): Promise<ApiResponse<UploadResponse>> {
  await delay(260);
  const ext = `.${(file.name.split('.').pop() ?? '').toLowerCase()}`;
  const textual = ['.txt', '.md', '.csv'].includes(ext);
  let chars: number | undefined;
  if (textual) {
    const text = await file.text().catch(() => '');
    chars = text.length;
  }
  const data: UploadResponse = {
    file_id: `art_upload_mock_${Date.now().toString(36)}`,
    filename: file.name,
    size: file.size,
    type: ext.replace('.', ''),
    chars,
    parsed: true,
    ext: ext.replace('.', ''),
    trace_id: traceId(),
  };
  return { data, traceId: data.trace_id ?? null };
}

export function mockSubmitApproval(
  _threadId: string,
  approvalId: string,
  decision: ApprovalDecision,
  _comment?: string,
): ApiResponse<{
  approval_id: string;
  decision: ApprovalDecision;
  decided_at: string;
  resumed: boolean;
}> {
  const resolve = pendingApprovals.get(approvalId);
  if (!resolve) {
    throw new Error('APPROVAL_ALREADY_DECIDED');
  }
  pendingApprovals.delete(approvalId);
  resolve(decision);
  return {
    data: {
      approval_id: approvalId,
      decision,
      decided_at: nowIso(),
      resumed: true,
    },
    traceId: traceId(),
  };
}

export function mockGetAudit(threadId: string): ApiResponse<AuditResponse> {
  const runs: AuditRun[] = [];
  if (lastAuditRun && (lastAuditThreadId === threadId || !lastAuditThreadId)) {
    runs.push(lastAuditRun);
  }
  return {
    data: { thread_id: threadId, runs, trace_id: traceId() },
    traceId: traceId(),
  };
}

export function mockGetArtifact(artifactId: string): ApiResponse<ArtifactMeta> {
  const artifact = mockArtifacts.get(artifactId);
  if (artifact) return { data: artifact, traceId: traceId() };
  const fallback: ArtifactMeta = {
    artifact_id: artifactId,
    type: 'docx',
    filename: '周报_2026-W43.docx',
    size: 18234,
    sha256: 'mock-sha256',
    created_at: nowIso(),
    download_url: mockPreviewUrl(),
    preview_url: mockPreviewUrl(),
    trace_id: traceId(),
  };
  return { data: fallback, traceId: traceId() };
}

/* ------------------------------------------------------------------ */
/* 流式事件脚本                                                        */
/* ------------------------------------------------------------------ */

function todo(content: string, status: TodoStatus, id: string) {
  return { id, content, status };
}

export async function runMockStream(
  input: RunStreamInput,
  handlers: RunStreamHandlers,
): Promise<void> {
  const runId = `r_mock_${Date.now().toString(36)}`;
  const threadId = input.threadId;
  const startedAt = nowIso();
  const signal = input.signal;

  // 产物格式：与输入区选择保持一致（默认 docx）
  const mockFormat: OutputFormat = isOutputFormat(input.outputFormat ?? '')
    ? (input.outputFormat as OutputFormat)
    : 'docx';
  const mockFormatLabel = OUTPUT_FORMAT_LABELS[mockFormat];
  const mockArtifactType =
    mockFormat === 'docx' || mockFormat === 'pdf' || mockFormat === 'xlsx' ? mockFormat : 'txt';
  const mockFilename = `周报_2026-W43.${mockFormat}`;

  let frameSeq = 0;

  const emit = (event: string, data: Record<string, unknown>) => {
    frameSeq += 1;
    handlers.onFrame({
      id: String(frameSeq),
      event,
      data: JSON.stringify({ version: EVENT_VERSION, run_id: runId, ...data }),
    });
  };

  const sleep = (ms: number): Promise<boolean> =>
    new Promise((resolve) => {
      if (signal?.aborted) {
        resolve(false);
        return;
      }
      const timer = setTimeout(() => {
        signal?.removeEventListener('abort', onAbort);
        resolve(true);
      }, ms);
      const onAbort = () => {
        clearTimeout(timer);
        resolve(false);
      };
      signal?.addEventListener('abort', onAbort, { once: true });
    });

  const stopIfAborted = () => signal?.aborted === true;

  const streamText = async (messageId: string, text: string, chunkSize = 7, gapMs = 38) => {
    let count = 0;
    for (let index = 0; index < text.length; index += chunkSize) {
      if (stopIfAborted() || !(await sleep(gapMs))) return false;
      emit('message.delta', {
        message_id: messageId,
        delta: text.slice(index, index + chunkSize),
        index: count,
      });
      count += 1;
    }
    emit('message.completed', { message_id: messageId, content: text });
    return true;
  };

  // v1.2：思考过程流（先于正文，与大模型「先想后答」一致）
  // 节奏刻意放慢到 ~1.4s：太快会让用户看不到思考过程，失去「先想后答」的观感。
  // 决策行只在需要判断时出现：v1.5 起 thinking.* 的语义变了，带 kind 让前端
  // 决定用哪种色调、要不要当「我在做事」之外的东西显示。
  const streamThinking = async (
    messageId: string,
    text: string,
    kind: ThinkingKind = 'decision',
    chunkSize = 4,
    gapMs = 62,
  ) => {
    let count = 0;
    for (let index = 0; index < text.length; index += chunkSize) {
      if (stopIfAborted() || !(await sleep(gapMs))) return false;
      emit('thinking.delta', {
        message_id: messageId,
        delta: text.slice(index, index + chunkSize),
        index: count,
        kind,
      });
      count += 1;
    }
    emit('thinking.completed', { message_id: messageId, content: text, kind });
    return true;
  };

  handlers.onOpen?.();

  // 演示也照真实路径走：不再有「写入前请你确认」这一步。审批卡已经拿掉了，
  // 门控判过就做、判不过就说明——本地 mock 留在旧流程里，会卡在一个
  // 没人能给出的决议上。
  const message1 = '我先读取你上传的材料，然后按周报模板生成文档。';
  const message2 = '已读取 2 份素材（会议记录.docx、素材.txt），共 1,240 字。正在提炼周报要点。';
  const message3 = `要点已提炼完成，正在按周报模板生成 ${mockFormatLabel}。`;
  const message4 = `周报已生成：${mockFilename}，可直接下载。`;
  // 决策行：只在要定方向时说一句。演示模式也照这个来——
  // 以前这里先念一遍「理解目标→读素材→按结构组织→生成文件」的方法论，
  // 每次开局都一样，像模板在演，而不是有人在想。
  const decision1 = '先按周报骨架走；材料里要是没有进展和计划，就改给摘要，不硬凑';

  emit('run.started', {
    thread_id: threadId,
    mode: 'mock',
    model: 'mock-scripted',
    started_at: startedAt,
  });
  if (!(await sleep(260)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  if (!(await streamThinking(`m_${runId}_think`, decision1))) {
    handlers.onAbort?.();
    return;
  }

  if (!(await streamText(`m_${runId}_01`, message1))) {
    handlers.onAbort?.();
    return;
  }
  if (!(await sleep(140)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  const todos = (s1: TodoStatus, s2: TodoStatus, s3: TodoStatus) => [
    todo('读取上传材料', s1, 't1'),
    todo('提炼周报要点', s2, 't2'),
    todo(`生成 ${mockFormatLabel} 周报`, s3, 't3'),
  ];
  emit('plan.updated', { todos: todos('in_progress', 'pending', 'pending') });

  if (!(await sleep(420)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  emit('tool.finished', {
    tool: 'file.list',
    ok: true,
    risk: 'low',
    summary: '发现 2 个素材文件',
    duration_ms: 64,
    input: { thread_id: threadId },
    output: {
      files: [
        { filename: '会议记录.docx', size: 18234, type: 'docx' },
        { filename: '素材.txt', size: 2140, type: 'txt' },
      ],
    },
    artifact_id: null,
  });

  if (!(await sleep(260)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  emit('plan.updated', { todos: todos('completed', 'in_progress', 'pending') });

  if (!(await sleep(240)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  if (!(await streamText(`m_${runId}_02`, message2))) {
    handlers.onAbort?.();
    return;
  }
  if (!(await sleep(220)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  const fileReadOutput = {
    files: [
      { filename: '会议记录.docx', chars: 860 },
      { filename: '素材.txt', chars: 380 },
    ],
    chars: 1240,
  };
  emit('tool.finished', {
    tool: 'file.read',
    ok: true,
    risk: 'low',
    summary: '已读取 2 个文件，共 1,240 字',
    duration_ms: 184,
    input: { files: ['会议记录.docx', '素材.txt'] },
    output: fileReadOutput,
    artifact_id: null,
    // 可选追加字段：告知前端该工具由哪个子智能体执行（契约允许追加，旧前端忽略）
    subagent: {
      id: 'sa_file',
      name: '文件检索子智能体',
      role: '检索并解析上传素材',
      status: 'done',
    },
  } satisfies Partial<ToolFinishedEvent>);

  if (!(await sleep(240)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  emit('plan.updated', { todos: todos('completed', 'completed', 'in_progress') });

  if (!(await sleep(220)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  if (!(await streamText(`m_${runId}_03`, message3))) {
    handlers.onAbort?.();
    return;
  }
  if (!(await sleep(320)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  const previewUrl = mockPreviewUrl();

  if (!(await sleep(360)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  emit('tool.finished', {
    tool: 'doc.generate_report',
    ok: true,
    risk: 'high',
    summary: `按周报模板生成 ${mockFormatLabel}（18.2 KB）`,
    duration_ms: 1240,
    input: {
      template: 'weekly_report_v1',
      title: '本周工作周报（2026-W43）',
      format: mockFormat,
      sections: ['本周完成', '关键进展', '风险与求助', '下周计划'],
    },
    output: { filename: mockFilename, size: 18234, artifact_id: 'art_01' },
    artifact_id: 'art_01',
    subagent: {
      id: 'sa_doc',
      name: '文档撰写子智能体',
      role: '按模板成文并排版',
      status: 'done',
    },
  } satisfies Partial<ToolFinishedEvent>);

  if (!(await sleep(220)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }

  const artifact: ArtifactMeta = {
    artifact_id: 'art_01',
    type: mockArtifactType,
    filename: mockFilename,
    size: 18234,
    sha256: 'mock-9f2c4a6b8d0e1f3a5c7e9b2d4f6a8c0e',
    created_at: nowIso(),
    download_url: previewUrl,
    preview_url: previewUrl,
    thread_id: threadId,
    run_id: runId,
    trace_id: traceId(),
  };
  mockArtifacts.set(artifact.artifact_id, artifact);

  emit('artifact.ready', {
    artifact_id: artifact.artifact_id,
    type: mockArtifactType,
    filename: artifact.filename,
    size: artifact.size,
    download_url: artifact.download_url,
    preview_url: artifact.preview_url,
  });

  if (!(await sleep(280)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  emit('plan.updated', { todos: todos('completed', 'completed', 'completed') });

  if (!(await sleep(260)) || stopIfAborted()) {
    handlers.onAbort?.();
    return;
  }
  // 生成后那段「二次思考」删掉了：那只是把「核对结果、整理结论」念一遍，
  // 用户要看的是文件到底成没成。
  if (!(await streamText(`m_${runId}_04`, message4))) {
    handlers.onAbort?.();
    return;
  }

  const finishedAt = nowIso();
  const status = 'completed';
  const runSummary: AuditRun = {
    run_id: runId,
    started_at: startedAt,
    finished_at: finishedAt,
    status,
    tokens: 8123,
    cost_cny: 0.06,
    elapsed_ms: 41_700,
    approvals: [],
    artifacts: [{ artifact_id: 'art_01', type: 'docx', filename: mockFilename }],
  };
  lastAuditRun = runSummary;
  lastAuditThreadId = threadId;

  emit('run.completed', {
    status,
    tokens: runSummary.tokens,
    cost_cny: runSummary.cost_cny,
    elapsed_ms: runSummary.elapsed_ms,
    artifact_ids: ['art_01'],
    // 契约字段照发，永远是空数组：审批层已经拿掉，没人再产生决议。
    approvals: [],
    degraded: false,
  });

  touchMockThread(threadId, 6, 1);
  handlers.onClose?.();
}
