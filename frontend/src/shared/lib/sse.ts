/**
 * SSE 客户端（docs/events.md 第 1 节）。
 *
 * 为什么不用 EventSource：发起运行需要 POST + JSON body，EventSource 只支持 GET。
 * 这里用 fetch + ReadableStream + TextDecoder，按 `id/event/data` 帧解析，
 * 支持 AbortController 停止、未知事件忽略、终态事件关流、网络异常上报；
 * 断线后可通过 `resumeRunEvents`（带 Last-Event-ID）续传运行事件。
 */
import { API_V1_BASE } from '../config/runtime';
import { isTerminalEventName } from '../types/events';
import type { RunMode } from '../types/events';

export interface SseFrame {
  id: string | null;
  event: string;
  data: string;
}

export interface StreamFailure {
  code: string;
  message: string;
  retryable: boolean;
  traceId: string | null;
  status?: number;
}

export interface RunStreamInput {
  threadId: string;
  message: string;
  mode?: RunMode;
  /** 产物格式（docx/pdf/xlsx/md/txt）；缺省由后端按素材推导。 */
  outputFormat?: string;
  /** 当前项目：后端会把项目里的文档作为本轮素材一起交给 Agent。 */
  projectId?: string;
  /** 只带项目里的这些文件（相对路径）；不传则按最近修改取若干文档。 */
  projectFiles?: string[];
  /** 本轮审批策略：always_ask / risky / all_allow；缺省由后端按设置决定。 */
  approvalMode?: string;
  /**
   * 「文档格式」面板里点过的那几项（font / size / bold / line / indent_chars / align …）。
   * 只传用户真正选过的键；空对象等于全交给后端按文档类型判断。
   */
  docStyle?: Record<string, unknown>;
  signal?: AbortSignal;
}

export interface ResumeRunInput {
  runId: string;
  /** 最后收到的事件 id（SSE id 字段），作为 Last-Event-ID 续传。 */
  lastEventId: string | null;
  signal?: AbortSignal;
}

export interface RunStreamHandlers {
  /** 每收到一个合法帧回调（未知事件也会送达，由上层忽略）。 */
  onFrame: (frame: SseFrame) => void;
  /** 响应头到达、开始读流。 */
  onOpen?: () => void;
  /** 任何失败（HTTP 非 2xx / 网络错误 / 响应体不可读）。 */
  onFailure?: (failure: StreamFailure) => void;
  /** 流结束（终态事件后主动关流也会触发）。 */
  onClose?: () => void;
  /** 用户主动停止（AbortController）。 */
  onAbort?: () => void;
}

interface ParsedErrorBody {
  code: string;
  message: string;
  traceId: string | null;
}

function parseErrorBody(text: string, status: number): ParsedErrorBody {
  const fallback: ParsedErrorBody = {
    code: `HTTP_${status}`,
    message: `请求失败（HTTP ${status}）`,
    traceId: null,
  };
  if (!text) return fallback;
  try {
    const body = JSON.parse(text) as {
      trace_id?: string;
      error?: { code?: string; message?: string };
      detail?: unknown;
    };
    return {
      code: body.error?.code ?? fallback.code,
      message: body.error?.message ?? describeDetail(body.detail) ?? fallback.message,
      traceId: body.trace_id ?? null,
    };
  } catch {
    return fallback;
  }
}

function describeDetail(detail: unknown): string | null {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length > 0) return '请求参数有误';
  return null;
}

/** 从缓冲区里切出一个完整帧；没有完整帧返回 null。 */
function takeFrame(buffer: string): { raw: string; rest: string } | null {
  const lf = buffer.indexOf('\n\n');
  const crlf = buffer.indexOf('\r\n\r\n');
  if (lf < 0 && crlf < 0) return null;
  if (lf >= 0 && (crlf < 0 || lf < crlf)) {
    return { raw: buffer.slice(0, lf), rest: buffer.slice(lf + 2) };
  }
  return { raw: buffer.slice(0, crlf), rest: buffer.slice(crlf + 4) };
}

/** 解析单个帧（空行已由调用方切掉）。无法解析返回 null。 */
export function parseSseFrame(raw: string): SseFrame | null {
  const lines = raw.split(/\r?\n/);
  const dataLines: string[] = [];
  let event = 'message';
  let id: string | null = null;

  for (const line of lines) {
    if (!line || line.startsWith(':')) continue; // 注释/心跳
    const colon = line.indexOf(':');
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);

    switch (field) {
      case 'id':
        id = value;
        break;
      case 'event':
        if (value) event = value;
        break;
      case 'data':
        dataLines.push(value);
        break;
      default:
        // retry / 未知字段：忽略（契约只要求 id/event/data）
        break;
    }
  }

  if (dataLines.length === 0) return null;
  return { id, event, data: dataLines.join('\n') };
}

/**
 * 读取一个 SSE 响应直到流结束。
 * 终态事件（run.completed / run.failed）后主动 cancel，避免连接悬空。
 */
async function pumpStream(response: Response, handlers: RunStreamHandlers): Promise<void> {
  if (!response.body) {
    handlers.onFailure?.({
      code: 'STREAM_UNAVAILABLE',
      message: '当前浏览器不支持流式响应',
      retryable: false,
      traceId: null,
    });
    return;
  }

  handlers.onOpen?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let terminal = false;

  while (!terminal) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let frame = takeFrame(buffer);
    while (frame) {
      buffer = frame.rest;
      const parsed = parseSseFrame(frame.raw);
      if (parsed) {
        handlers.onFrame(parsed);
        if (isTerminalEventName(parsed.event)) {
          terminal = true;
          break;
        }
      }
      frame = takeFrame(buffer);
    }
  }

  await reader.cancel().catch(() => undefined);
  handlers.onClose?.();
}

/** 建立 fetch 连接并把非 2xx / JSON 错误统一转成 StreamFailure。 */
async function openStream(
  url: string,
  init: RequestInit,
  handlers: RunStreamHandlers,
): Promise<Response | null> {
  const response = await fetch(url, { ...init, cache: 'no-store' });

  if (!response.ok) {
    const text = await response.text().catch(() => '');
    const parsed = parseErrorBody(text, response.status);
    handlers.onFailure?.({
      code: parsed.code,
      message: parsed.message,
      retryable: response.status >= 500 || response.status === 429,
      traceId: parsed.traceId,
      status: response.status,
    });
    return null;
  }

  const contentType = response.headers.get('content-type') ?? '';
  if (contentType.includes('application/json')) {
    const text = await response.text().catch(() => '');
    const parsed = parseErrorBody(text, response.status);
    handlers.onFailure?.({
      code: parsed.code,
      message: parsed.message,
      retryable: true,
      traceId: parsed.traceId,
      status: response.status,
    });
    return null;
  }

  return response;
}

function networkFailure(error: unknown): StreamFailure {
  const message =
    error instanceof TypeError
      ? '无法连接后端（/api 代理未通或服务未启动）'
      : error instanceof Error
        ? error.message
        : '流式连接异常';
  return { code: 'NETWORK_ERROR', message, retryable: true, traceId: null };
}

function isAbort(error: unknown, signal?: AbortSignal): boolean {
  return Boolean(signal?.aborted) || (error instanceof DOMException && error.name === 'AbortError');
}

/**
 * 发起运行并读取 SSE 流。
 * 正常结束（终态事件或服务端关流）后 resolve；失败通过 onFailure 上报后 resolve。
 */
export async function streamRun(input: RunStreamInput, handlers: RunStreamHandlers): Promise<void> {
  const controller = new AbortController();
  let abortedByCaller = false;

  const onCallerAbort = () => {
    abortedByCaller = true;
    controller.abort();
  };
  if (input.signal) {
    if (input.signal.aborted) {
      handlers.onAbort?.();
      return;
    }
    input.signal.addEventListener('abort', onCallerAbort, { once: true });
  }

  try {
    const response = await openStream(
      `${API_V1_BASE}/threads/${encodeURIComponent(input.threadId)}/runs/stream`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'text/event-stream',
        },
        body: JSON.stringify({
          message: input.message,
          ...(input.mode ? { mode: input.mode } : {}),
          ...(input.outputFormat ? { output_format: input.outputFormat } : {}),
          ...(input.docStyle && Object.keys(input.docStyle).length > 0
            ? { doc_style: input.docStyle }
            : {}),
          ...(input.projectId ? { project_id: input.projectId } : {}),
          ...(input.approvalMode ? { approval_mode: input.approvalMode } : {}),
          ...(input.projectFiles && input.projectFiles.length > 0
            ? { project_files: input.projectFiles }
            : {}),
        }),
        signal: controller.signal,
      },
      handlers,
    );
    if (!response) return;
    await pumpStream(response, handlers);
  } catch (error) {
    if (abortedByCaller || isAbort(error, input.signal)) {
      handlers.onAbort?.();
      return;
    }
    handlers.onFailure?.(networkFailure(error));
  } finally {
    input.signal?.removeEventListener('abort', onCallerAbort);
  }
}

/**
 * 断线续传：GET /api/v1/runs/{run_id}/events/stream，带 Last-Event-ID。
 * 后端未实现该端点时返回 404 → onFailure（上层据此降级为轮询或报错）。
 */
export async function resumeRunEvents(
  input: ResumeRunInput,
  handlers: RunStreamHandlers,
): Promise<void> {
  try {
    const headers: Record<string, string> = { Accept: 'text/event-stream' };
    if (input.lastEventId) headers['Last-Event-ID'] = input.lastEventId;

    const response = await openStream(
      `${API_V1_BASE}/runs/${encodeURIComponent(input.runId)}/events/stream`,
      { method: 'GET', headers, signal: input.signal },
      handlers,
    );
    if (!response) return;
    await pumpStream(response, handlers);
  } catch (error) {
    if (isAbort(error, input.signal)) {
      handlers.onAbort?.();
      return;
    }
    handlers.onFailure?.(networkFailure(error));
  }
}
