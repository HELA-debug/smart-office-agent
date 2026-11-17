/**
 * 工作台控制器：把组件事件翻译成 API 调用 + reducer action。
 * 组件本身不 fetch，只通过这里暴露的方法驱动。
 */
import { useCallback, useEffect, useReducer, useRef } from 'react';
import {
  isMockMode,
  RUN_MODE_OVERRIDE,
  SSE_MAX_RECONNECTS,
  SSE_RECONNECT_BASE_DELAY_MS,
} from '../../../shared/config/runtime';
import { ApiError, endpointUnavailableMessage, errorMessage } from '../../../shared/lib/api';
import { onArtifactsChanged } from '../../../shared/lib/artifacts-signal';
import { mockCreateThread, mockListThreads, runMockStream } from '../../../shared/lib/mock-run';
import { parseRunEvent } from '../../../shared/types/events';
import { artifactsApi, maxUploadBytesForFile } from '../../artifacts';
import { auditApi } from '../../audit';
import { resumeRunEvents, runsApi, streamRun } from '../../runs';
import { sessionsApi } from '../../sessions';
import { settingsApi } from '../../settings';
import {
  getBackgroundTask,
  patchBackgroundTask,
  removeBackgroundTask,
  upsertBackgroundTask,
} from './background-tasks';
import { clearLastThreadId, readLastThreadId, writeLastThreadId } from './last-thread';
import {
  failureToError,
  normalizeRunMode,
  summarizeTitle,
  toApprovalItems,
  toHistoryMessages,
  toThreadAssets,
} from './mappers';
import {
  createInitialState,
  selectBlockingApproval,
  selectIsStreaming,
  selectRunBusy,
  workbenchReducer,
} from './workbench';
import type { QueuedMessage, UploadItem, WorkbenchAction } from './types';
import type { ApprovalDecision } from '../../../shared/types/events';
import type { SseFrame } from '../../runs';

const NOTICE_TTL_MS = 5000;
/** 批量删除单次请求上限（后端 `thread_ids` 的 max_length=200）。 */
const BULK_DELETE_CHUNK = 200;
/** 「全选全部」最多翻多少页（100/页 → 2000 个会话），防止后端分页异常时死循环。 */
const MAX_SESSION_PAGES = 20;

export function useWorkbench() {
  const [state, dispatch] = useReducer(workbenchReducer, undefined, createInitialState);
  const abortRef = useRef<AbortController | null>(null);
  const threadIdRef = useRef<string | null>(null);
  const threadPromiseRef = useRef<Promise<string> | null>(null);
  const noticeTimerRef = useRef<number | null>(null);
  const sessionsQueryRef = useRef({ page: 1, pageSize: 8 });
  /**
   * 当前「前台」那条事件流：切会话时会被摘成后台任务。
   * 一个 key 对应一条 SSE；不在前台的流一律不再 dispatch，避免污染新会话的消息列表。
   */
  const activeKeyRef = useRef<string | null>(null);
  const streamCtrlsRef = useRef<Map<string, AbortController>>(new Map());
  const detachedRef = useRef<Set<string>>(new Set());
  /** 用户已经主动选过会话/开过新会话：此时「恢复上次会话」不能再抢回来 */
  const restoreCancelledRef = useRef(false);
  /** 媒体识别轮询的定时器；同一时刻只跑一条（换会话时重开） */
  const mediaPollRef = useRef<number | null>(null);
  /** 已经提示过「识别完成/失败」的素材，避免每轮轮询都再弹一次 */
  const mediaNotifiedRef = useRef<Set<string>>(new Set());
  // 回调里要读最新状态，但不想把每个回调都绑上 state 依赖
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  });

  useEffect(() => {
    threadIdRef.current = state.threadId;
    // 记住当前会话：路由切走再回来时据此恢复，避免每次回首页都变成新会话
    if (state.threadId) writeLastThreadId(state.threadId);
  }, [state.threadId]);

  // 换会话 / 卸载时停掉识别轮询：旧会话的识别结果已经和新界面对不上了，
  // 继续拉只会白耗请求，还可能把「识别完成」的提示弹在别的会话里
  useEffect(
    () => () => {
      if (mediaPollRef.current) {
        window.clearTimeout(mediaPollRef.current);
        mediaPollRef.current = null;
      }
    },
    [state.threadId],
  );

  /**
   * 进会话时把「早就有结果的素材」先标成已提示过。
   *
   * 轮询是「这一轮识别完了就报一声」，但第一次拉取会把会话里**所有**素材带回来：
   * 上午传的录音、昨天传的截图都会跟着报一遍「识别完成」。那不是新闻，是噪音。
   */
  const seedNotifiedMedia = useCallback((uploads: UploadItem[]) => {
    for (const upload of uploads) {
      if (!upload.media_status || upload.media_status === 'processing') continue;
      const id = upload.file_id ?? upload.artifact_id ?? upload.local_id;
      if (id) mediaNotifiedRef.current.add(id);
    }
  }, []);

  const notify = useCallback((kind: 'info' | 'error', text: string, traceId?: string | null) => {
    dispatch({ type: 'notice', notice: { kind, text, traceId } });
  }, []);

  /* ---------------------------------------------------------------- */
  /* 健康检查 + 会话列表                                               */
  /* ---------------------------------------------------------------- */

  const checkHealth = useCallback(async () => {
    const at = new Date().toISOString();
    try {
      const response = await settingsApi.health();
      dispatch({
        type: 'health/checked',
        status: 'ok',
        mode: normalizeRunMode(response.data.mode) ?? (isMockMode() ? 'mock' : null),
        model: response.data.model ?? null,
        degraded: response.data.degraded,
        degradedReason: response.data.degraded_reason ?? '',
        engine: response.data.engine,
        engineEffective: response.data.engine_effective,
        engineReason: response.data.engine_reason ?? '',
        modelReady: response.data.model_ready,
        modelHint: response.data.model_hint ?? '',
        version: response.data.version,
        at,
      });
    } catch {
      dispatch({ type: 'health/checked', status: 'unreachable', mode: null, model: null, at });
    }
  }, []);

  /**
   * 拉会话列表。
   * `silent` 用于「别处删了产物，顺手把 N 产物对一下账」这类后台刷新：
   * 不需要再闪一次骨架屏，失败了也不用弹错——下一次操作自然会重试。
   */
  const loadSessions = useCallback(async (options: { silent?: boolean } = {}) => {
    if (!options.silent) dispatch({ type: 'sessions/loading' });
    const { page, pageSize } = sessionsQueryRef.current;
    try {
      const response = await sessionsApi.listThreads({ page, pageSize });
      dispatch({
        type: 'sessions/loaded',
        sessions: response.data.threads,
        meta: {
          page: response.data.page,
          pageSize: response.data.page_size,
          total: response.data.total,
        },
      });
    } catch (error) {
      if (options.silent) return;
      dispatch({ type: 'sessions/error', message: errorMessage(error) });
    }
  }, []);

  /** 服务端分页。 */
  const goToSessionsPage = useCallback(
    (page: number) => {
      sessionsQueryRef.current = { ...sessionsQueryRef.current, page };
      void loadSessions();
    },
    [loadSessions],
  );

  useEffect(() => {
    void checkHealth();
    void loadSessions();
  }, [checkHealth, loadSessions]);

  /**
   * 产物被删/恢复后，会话行上的「N 产物」要立刻跟上。
   * 这个数字是会话接口算的，跟产物中心不是同一份数据，只能重新拉一次列表；
   * 用静默刷新，避免用户正看着列表时骨架屏又闪一下。
   */
  useEffect(() => {
    return onArtifactsChanged(() => {
      void loadSessions({ silent: true });
    });
  }, [loadSessions]);

  /**
   * 回到工作台时恢复上次打开的会话（只跑一次）。
   * 没有记录 / 记录已失效就保持空状态 —— 是否新建会话完全由用户点「新建会话」决定，
   * 任何情况下都不在挂载时自动建线程。
   */
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const saved = readLastThreadId();
    if (!saved) return;

    void (async () => {
      try {
        const [detailResult, auditResult] = await Promise.allSettled([
          sessionsApi.getThread(saved),
          auditApi.getAudit(saved),
        ]);
        if (detailResult.status === 'rejected') {
          clearLastThreadId(); // 会话已删 / 后端重置：丢掉记录，停在空状态
          return;
        }
        // 请求期间用户已经选了别的会话或新建了会话：以用户操作为准，不覆盖
        if (threadIdRef.current !== null || restoreCancelledRef.current) return;

        const detail = detailResult.value.data;
        const assets = toThreadAssets(detail);
        dispatch({
          type: 'thread/selected',
          threadId: saved,
          title: detail.title ?? '会话',
          history: toHistoryMessages(detail),
          ...assets,
          approvals:
            auditResult.status === 'fulfilled'
              ? toApprovalItems(auditResult.value.data.approvals ?? [])
              : [],
        });
        // 恢复会话时，昨天识别完的素材不该再弹一次「识别完成」
        seedNotifiedMedia(assets.threadUploads);
      } catch {
        clearLastThreadId();
      }
    })();
  }, [seedNotifiedMedia]);

  // notice 自动消失
  useEffect(() => {
    if (!state.notice) return;
    if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
    noticeTimerRef.current = window.setTimeout(() => {
      dispatch({ type: 'notice', notice: null });
    }, NOTICE_TTL_MS);
    return () => {
      if (noticeTimerRef.current) window.clearTimeout(noticeTimerRef.current);
    };
  }, [state.notice]);

  // 卸载（关页面/切到别的 feature）时中断所有流：前台一条 + 后台若干条
  useEffect(() => {
    const controllers = streamCtrlsRef.current;
    return () => {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
    };
  }, []);

  /* ---------------------------------------------------------------- */
  /* 会话                                                              */
  /* ---------------------------------------------------------------- */

  const ensureThread = useCallback(
    async (title?: string): Promise<string | null> => {
      if (threadIdRef.current) return threadIdRef.current;

      // mock 模式下用本地 fixture 创建，保证无后端也能演示；标题取任务摘要
      if (isMockMode()) {
        const created = mockCreateThread(title);
        threadIdRef.current = created.data.thread_id;
        dispatch({ type: 'thread/created', thread: created.data });
        dispatch({
          type: 'sessions/loaded',
          sessions: mockListThreads().data.map((thread) => ({ ...thread, pinned: false })),
          meta: { page: 1, pageSize: 8, total: mockListThreads().data.length },
        });
        return created.data.thread_id;
      }

      if (!threadPromiseRef.current) {
        threadPromiseRef.current = sessionsApi
          .createThread()
          .then((response) => {
            threadIdRef.current = response.data.thread_id;
            dispatch({ type: 'thread/created', thread: response.data });
            return response.data.thread_id;
          })
          .finally(() => {
            threadPromiseRef.current = null;
          });
      }
      try {
        return await threadPromiseRef.current;
      } catch (error) {
        notify('error', `新建会话失败：${errorMessage(error)}`);
        return null;
      }
    },
    [notify],
  );

  /** 重新拉一次会话详情：后台任务跑完后把新消息、产物、审批补回界面。 */
  const reloadThread = useCallback(
    async (threadId: string, note?: string) => {
      const [detailResult, auditResult] = await Promise.allSettled([
        sessionsApi.getThread(threadId),
        auditApi.getAudit(threadId),
      ]);
      if (threadIdRef.current !== threadId) return; // 期间用户又切走了
      if (detailResult.status === 'rejected') return;
      const detail = detailResult.value.data;
      dispatch({
        type: 'thread/selected',
        threadId,
        title: detail.title ?? '会话',
        history: toHistoryMessages(detail),
        ...toThreadAssets(detail),
        approvals:
          auditResult.status === 'fulfilled'
            ? toApprovalItems(auditResult.value.data.approvals ?? [])
            : [],
      });
      if (note) notify('info', note);
    },
    [notify],
  );

  /**
   * 只补拉产物与素材，不动对话。
   *
   * 产品要求：这一轮出的文件必须当场出现在对话里，其余（含同一轮多出的）
   * 自动收进「更早的产物」折叠区。
   * 正常靠 `artifact.ready` 事件就够了，但事件在某些路径上可能丢（早期的脚本产出、
   * 代理断流重连的边界），所以跑完再对一次账——代价是一次 GET，换来「永不要求用户刷新」。
   */
  const refreshAssets = useCallback(async (threadId: string) => {
    try {
      const response = await sessionsApi.getThread(threadId);
      if (threadIdRef.current !== threadId) return; // 期间用户切走了
      const assets = toThreadAssets(response.data);
      dispatch({
        type: 'thread/assets',
        artifacts: assets.artifacts ?? [],
        threadUploads: assets.threadUploads ?? [],
      });
    } catch {
      // 补拉失败不影响主流程：事件已经把大多数情况覆盖了
    }
  }, []);

  /**
   * 把正在跑的任务摘成「后台任务」：SSE 不断开，只是不再往当前会话的界面写事件。
   * 用户切到别的会话时可继续干别的事，任务在图上的输入框上方继续计时。
   */
  const detachCurrentStream = useCallback(() => {
    const key = activeKeyRef.current;
    const threadId = threadIdRef.current;
    const current = stateRef.current;
    if (!key || !threadId) return;
    if (current.status !== 'streaming' && current.status !== 'waiting_approval') return;

    detachedRef.current.add(key);
    upsertBackgroundTask({
      key,
      threadId,
      threadTitle: current.threadTitle || '会话',
      label: summarizeTitle(current.lastUserMessage ?? '任务'),
      runId: current.runId,
      startedAt: Date.now(),
      status: current.status === 'waiting_approval' ? 'waiting_approval' : 'running',
    });
    activeKeyRef.current = null;
    abortRef.current = null;
  }, []);

  const newThread = useCallback(() => {
    restoreCancelledRef.current = true;
    detachCurrentStream();
    // 用户主动开新会话：把「上次会话」清掉，否则刷新/回首页又会被恢复回来
    clearLastThreadId();
    dispatch({ type: 'thread/new' });
  }, [detachCurrentStream]);

  const renameThread = useCallback(
    async (threadId: string, title: string) => {
      const trimmed = title.trim();
      if (!trimmed) return;
      try {
        const response = await sessionsApi.updateThread(threadId, { title: trimmed });
        dispatch({ type: 'sessions/upsert', thread: response.data });
        notify('info', '会话已重命名');
      } catch (error) {
        notify('error', `重命名失败：${errorMessage(error)}`);
      }
    },
    [notify],
  );

  const toggleThreadPin = useCallback(
    async (threadId: string, pinned: boolean) => {
      try {
        // pinned 即调用方给出的目标值（SessionList 已做取反），直接透传
        const response = await sessionsApi.updateThread(threadId, { pinned });
        dispatch({ type: 'sessions/upsert', thread: response.data });
        notify('info', response.data.pinned ? '会话已置顶' : '已取消置顶');
      } catch (error) {
        notify('error', `置顶失败：${errorMessage(error)}`);
      }
    },
    [notify],
  );

  /**
   * 批量清理会话（左栏「批量清理」）。
   * - 按 200 个一批发请求（后端单次上限 200），跨页选中也不会被截断；
   * - 成功就回第一页：批量删完通常整页都空了，留在第 4 页只会看到「没有会话」；
   * - 返回是否成功，调用方据此决定要不要退出选择模式。
   */
  const cleanupThreads = useCallback(
    async (threadIds: string[]): Promise<boolean> => {
      const ids = [...new Set(threadIds.filter(Boolean))];
      if (ids.length === 0) return false;
      try {
        let deleted = 0;
        for (let start = 0; start < ids.length; start += BULK_DELETE_CHUNK) {
          const response = await sessionsApi.bulkDeleteThreads(
            ids.slice(start, start + BULK_DELETE_CHUNK),
          );
          deleted += response.data.deleted;
        }
        const activeRemoved = threadIdRef.current !== null && ids.includes(threadIdRef.current);
        dispatch({ type: 'sessions/removedMany', threadIds: ids });
        if (activeRemoved) clearLastThreadId();
        notify('info', deleted > 0 ? `已清理 ${deleted} 个会话` : '这些会话已经不在了');
        sessionsQueryRef.current = { ...sessionsQueryRef.current, page: 1 };
        void loadSessions();
        return true;
      } catch (error) {
        notify('error', `批量清理失败：${errorMessage(error)}`);
        return false;
      }
    },
    [loadSessions, notify],
  );

  /** 「全选全部」用：按 100/页（后端上限）把整个会话列表的 ID 捞出来，跨页也算上。 */
  const listAllThreadIds = useCallback(async (): Promise<string[]> => {
    const pageSize = 100;
    const ids: string[] = [];
    try {
      for (let page = 1; page <= MAX_SESSION_PAGES; page += 1) {
        const response = await sessionsApi.listThreads({ page, pageSize });
        const batch = response.data.threads.map((thread) => thread.thread_id);
        for (const threadId of batch) {
          if (!ids.includes(threadId)) ids.push(threadId);
        }
        if (batch.length < pageSize || ids.length >= response.data.total) break;
      }
    } catch (error) {
      notify('error', `读取会话列表失败：${errorMessage(error)}`);
    }
    return ids;
  }, [notify]);

  /**
   * 拖动重排（左栏）。
   *
   * 传上来的是「这一页的新顺序」，但落库要的是整份顺序：先按服务端当前顺序把
   * 全量 ID 拉回来，用这一页的新顺序替换掉原来的那一段，再整体提交。
   * 本地先改（拖完立刻见效），失败就重新拉列表纠正——比「先转圈再动」跟手。
   */
  const reorderThreads = useCallback(
    async (orderedIds: string[]) => {
      if (orderedIds.length === 0) return;
      dispatch({ type: 'sessions/reordered', threadIds: orderedIds });
      try {
        const allIds = await listAllThreadIds();
        if (allIds.length === 0) return;
        const pageIds = new Set(orderedIds);
        const anchor = allIds.findIndex((threadId) => pageIds.has(threadId));
        const rest = allIds.filter((threadId) => !pageIds.has(threadId));
        const merged = [...rest];
        merged.splice(anchor < 0 ? 0 : anchor, 0, ...orderedIds);
        await sessionsApi.reorderThreads(merged);
      } catch (error) {
        notify('error', `调整会话顺序失败：${errorMessage(error)}`);
        void loadSessions({ silent: true });
      }
    },
    [listAllThreadIds, loadSessions, notify],
  );

  const deleteThread = useCallback(
    async (threadId: string) => {
      const wasActive = threadIdRef.current === threadId;
      try {
        await sessionsApi.deleteThread(threadId);
        dispatch({ type: 'sessions/removed', threadId });
        if (wasActive) clearLastThreadId();
        notify('info', '会话已删除（软删）');
      } catch (error) {
        notify('error', `删除会话失败：${errorMessage(error)}`);
      }
    },
    [notify],
  );

  const selectThread = useCallback(
    async (threadId: string) => {
      if (threadId === threadIdRef.current) return;
      restoreCancelledRef.current = true;
      // 切走会话不打断正在跑的任务：转后台继续执行
      detachCurrentStream();

      const session = state.sessions.find((item) => item.thread_id === threadId);
      const [detailResult, auditResult] = await Promise.allSettled([
        sessionsApi.getThread(threadId),
        auditApi.getAudit(threadId),
      ]);

      if (detailResult.status === 'rejected') {
        // 顺序要紧：thread/selected 会用 createInitialState() 重建状态（notice 回到 null），
        // 先 notify 再 dispatch 会让错误提示立刻被抹掉、用户什么都看不到。
        dispatch({
          type: 'thread/selected',
          threadId,
          title: session?.title ?? '会话',
          history: [],
        });
        notify('error', `加载会话失败：${errorMessage(detailResult.reason)}`);
        return;
      }

      const detail = detailResult.value.data;
      const assets = toThreadAssets(detail);
      const approvals =
        auditResult.status === 'fulfilled'
          ? toApprovalItems(auditResult.value.data.approvals ?? [])
          : [];

      dispatch({
        type: 'thread/selected',
        threadId,
        title: detail.title ?? session?.title ?? '会话',
        history: toHistoryMessages(detail),
        ...assets,
        approvals,
      });
      // 老素材的识别结果不再当新闻播报（只报这一轮新传的）
      seedNotifiedMedia(assets.threadUploads);
    },
    [detachCurrentStream, notify, seedNotifiedMedia, state.sessions],
  );

  /* ---------------------------------------------------------------- */
  /* 上传                                                              */
  /* ---------------------------------------------------------------- */

  /**
   * 识别状态轮询：图片 OCR 几秒、录音转写几分钟，上传接口只回「识别中」，
   * 结果靠这里定时拉 `/threads/{id}/files` 补上。
   *
   * 节奏 2.5 秒：比这更快只是白耗请求（转写是分钟级的），更慢则图片识别完
   * 还要干等。识别完成后自己停，不会一直轮下去。
   */
  const pollMedia = useCallback(
    (threadId: string) => {
      if (mediaPollRef.current) window.clearTimeout(mediaPollRef.current);
      const tick = async (attempt = 0) => {
        try {
          const response = await artifactsApi.listThreadFiles(threadId);
          const files = response.data.files ?? [];
          dispatch({ type: 'upload/sync', files });
          for (const file of files) {
            if (!file.media) continue; // 文档解析是同步的，不在这里报「识别完成」
            const id = file.artifact_id ?? file.file_id;
            if (mediaNotifiedRef.current.has(id)) continue;
            if (file.status === 'ready') {
              mediaNotifiedRef.current.add(id);
              notify(
                'info',
                `${file.filename} 识别完成，${file.chars ?? 0} 字已可用`,
                response.traceId,
              );
            } else if (file.status === 'failed') {
              mediaNotifiedRef.current.add(id);
              notify(
                'error',
                `${file.filename} 识别失败：${file.media.error || '可以在素材上点重试'}`,
                response.traceId,
              );
            }
          }
          if (files.some((file) => file.status === 'processing')) {
            mediaPollRef.current = window.setTimeout(() => void tick(attempt), 2500);
          } else {
            mediaPollRef.current = null;
          }
        } catch {
          // 网络抖一下不代表识别失败：前几次继续追，追不上就交给用户手动刷新
          if (attempt < 5) {
            mediaPollRef.current = window.setTimeout(() => void tick(attempt + 1), 3000);
          } else {
            mediaPollRef.current = null;
          }
        }
      };
      void tick(0);
    },
    [dispatch, notify],
  );

  const performUpload = useCallback(
    async (localId: string, file: File, threadId: string): Promise<boolean> => {
      dispatch({ type: 'upload/begin', localId });
      try {
        const response = await artifactsApi.uploadFile(threadId, file, {
          onProgress: (progress) => dispatch({ type: 'upload/progress', localId, progress }),
        });
        dispatch({ type: 'upload/success', localId, response: response.data });
        const processing = response.data.status === 'processing';
        notify(
          'info',
          processing
            ? `已收到 ${file.name}，正在识别文字（${response.data.media?.label || '素材'}），完成后会提示你`
            : response.data.note
              ? `已添加 ${file.name}：${response.data.note}`
              : response.data.parsed === false
                ? `已上传 ${file.name}，解析失败（可在任务中重试）`
                : `已上传 ${file.name}${response.data.chars ? `，解析 ${response.data.chars} 字` : ''}`,
          response.traceId,
        );
        if (processing) pollMedia(threadId);
        const textPreview = response.data.text_preview;
        if (textPreview) {
          dispatch({ type: 'upload/preview', localId, preview: textPreview.slice(0, 200) });
        } else {
          const artifactId = response.data.artifact_id ?? response.data.file_id;
          if (artifactId) {
            void artifactsApi
              .fetchPreviewText(artifactId, 200)
              .then((preview) => {
                if (preview) dispatch({ type: 'upload/preview', localId, preview });
              })
              .catch(() => undefined);
          }
        }
        return true;
      } catch (error) {
        dispatch({ type: 'upload/error', localId, message: errorMessage(error) });
        notify(
          'error',
          `上传失败：${errorMessage(error)}`,
          error instanceof ApiError ? error.traceId : null,
        );
        return false;
      }
    },
    [notify, pollMedia],
  );

  /**
   * 提交任务前把暂存的附件真正传上去。
   * 上传必须挂在某个会话下，但「选个文件就凭空多一个会话」不能接受：
   * 现在选文件只进本地队列，等用户真的发任务（`sendMessage`）时才建会话 + 上传。
   */
  const flushStagedUploads = useCallback(
    async (threadId: string): Promise<boolean> => {
      const staged = stateRef.current.uploads.filter(
        (upload) => upload.status === 'staged' && upload.file,
      );
      for (const upload of staged) {
        const ok = await performUpload(upload.local_id, upload.file as File, threadId);
        if (!ok) return false;
      }
      return true;
    },
    [performUpload],
  );

  /**
   * 队列任务用的上传：素材是入队时摘下来的那一批（可能已经传过），
   * 不能从 state.uploads 里找——那份列表早就搬空了。
   */
  const flushUploads = useCallback(
    async (uploads: UploadItem[], threadId: string): Promise<boolean> => {
      for (const upload of uploads) {
        if (upload.status === 'parsed' || upload.file_id) continue; // 已经传过
        if (upload.status === 'error' || !upload.file) continue; // 传失败的没必要拦住整条任务
        const ok = await performUpload(upload.local_id, upload.file, threadId);
        if (!ok) return false;
      }
      return true;
    },
    [performUpload],
  );

  /* ---------------------------------------------------------------- */
  /* 运行                                                              */
  /* ---------------------------------------------------------------- */

  const runStream = useCallback(
    async (
      threadId: string,
      message: string,
      outputFormat?: string,
      project?: { id: string; files?: string[] } | null,
      approvalMode?: string,
      docStyle?: Record<string, unknown>,
    ) => {
      const key = `stream_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
      const controller = new AbortController();
      streamCtrlsRef.current.set(key, controller);
      activeKeyRef.current = key;
      abortRef.current = controller;

      /** 只有还在前台的流才允许写界面；被摘成后台任务后一律静默 */
      const isActive = () => activeKeyRef.current === key;
      const emit = (action: WorkbenchAction) => {
        if (isActive()) dispatch(action);
      };

      emit({ type: 'run/connection', connection: 'connecting' });

      let lastEventId: string | null = null;
      let lastSeq = 0;
      let runId: string | null = null;
      let terminal = false;

      const applyFrame = (frame: SseFrame): void => {
        if (frame.id) {
          const seq = Number(frame.id);
          if (Number.isFinite(seq)) {
            if (seq <= lastSeq) return; // 续传去重
            lastSeq = seq;
          }
          lastEventId = frame.id;
        }
        let payload: unknown;
        try {
          payload = JSON.parse(frame.data) as unknown;
        } catch {
          return; // data 不是合法 JSON：忽略该帧
        }
        const parsed = parseRunEvent(frame.event, payload);
        if (!parsed) return; // 未知事件 / 版本不符：忽略
        if (parsed.name === 'run.started') {
          runId = parsed.event.run_id;
          if (detachedRef.current.has(key)) patchBackgroundTask(key, { runId });
        }
        if (parsed.name === 'approval.required' && detachedRef.current.has(key)) {
          // 后台任务卡在审批：指示条换成「等你审批」，用户点回去就能处理
          patchBackgroundTask(key, { status: 'waiting_approval', runId });
        }
        if (parsed.name === 'run.completed' || parsed.name === 'run.failed') terminal = true;
        emit({
          type: 'run/event',
          parsed,
          frameId: frame.id,
          at: new Date().toISOString(),
        });
      };

      const reconnect = async (): Promise<boolean> => {
        for (let attempt = 1; attempt <= SSE_MAX_RECONNECTS; attempt += 1) {
          if (controller.signal.aborted) return false;
          emit({ type: 'run/connection', connection: 'reconnecting' });
          await new Promise((resolve) =>
            setTimeout(resolve, SSE_RECONNECT_BASE_DELAY_MS * attempt),
          );
          if (controller.signal.aborted) return false;
          let opened = false;
          await resumeRunEvents(
            { runId: runId ?? '', lastEventId, signal: controller.signal },
            {
              onFrame: applyFrame,
              onOpen: () => {
                opened = true;
                emit({ type: 'run/connection', connection: 'open' });
              },
              onFailure: () => undefined,
              onClose: () => undefined,
              onAbort: () => undefined,
            },
          );
          if (terminal) return true;
          if (opened) continue; // 接上了但流又结束，继续下一轮
        }
        return false;
      };

      const handlers = {
        onFrame: applyFrame,
        onOpen: () => emit({ type: 'run/connection', connection: 'open' }),
        onFailure: () => undefined,
        onClose: () => undefined,
        onAbort: () => undefined,
      };

      try {
        if (isMockMode()) {
          await runMockStream(
            { threadId, message, outputFormat, docStyle, signal: controller.signal },
            {
              ...handlers,
              onFailure: (failure: { code: string; message: string; retryable: boolean }) => {
                emit({
                  type: 'run/failed',
                  error: failureToError(failure),
                  at: new Date().toISOString(),
                });
              },
              onClose: () => emit({ type: 'run/streamClosed', at: new Date().toISOString() }),
            },
          );
          return;
        }

        await streamRun(
          {
            threadId,
            message,
            outputFormat,
            docStyle,
            signal: controller.signal,
            ...(project ? { projectId: project.id, projectFiles: project.files } : {}),
            ...(approvalMode ? { approvalMode } : {}),
            ...(RUN_MODE_OVERRIDE ? { mode: RUN_MODE_OVERRIDE } : {}),
          },
          handlers,
        );

        if (!terminal && !controller.signal.aborted && runId) {
          const recovered = await reconnect();
          if (!recovered && !terminal && !controller.signal.aborted) {
            emit({
              type: 'run/failed',
              error: {
                code: 'RECONNECT_FAILED',
                message: '连接中断，自动重连失败；已生成的内容保留，可点击「重试」重新运行',
                retryable: true,
              },
              at: new Date().toISOString(),
            });
            return;
          }
        }

        // 流结束但没有终态事件（且无法恢复）→ 标记错误，避免静默卡在 streaming
        if (!terminal && !controller.signal.aborted) {
          emit({
            type: 'run/failed',
            error: {
              code: 'STREAM_CLOSED',
              message: '事件流意外中断，未收到运行结束事件',
              retryable: true,
            },
            at: new Date().toISOString(),
          });
        } else {
          emit({ type: 'run/streamClosed', at: new Date().toISOString() });
        }
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        if (activeKeyRef.current === key) activeKeyRef.current = null;
        streamCtrlsRef.current.delete(key);
        // 会话列表的 message_count / updated_at 由后端更新，跑完后刷新一次
        void loadSessions();
        // 产物对账：把这一轮新出的文件补进对话，别让用户按 F5
        if (!detachedRef.current.has(key)) void refreshAssets(threadId);

        if (detachedRef.current.delete(key)) {
          // 后台任务收尾：撤掉指示条；用户正停在这个会话，就把新消息与产物补拉回来
          removeBackgroundTask(key);
          if (threadIdRef.current === threadId) {
            void reloadThread(threadId, '后台任务已完成');
          } else {
            notify('info', `后台任务已完成：${summarizeTitle(message)}`);
          }
        }
      }
    },
    [loadSessions, notify, refreshAssets, reloadThread],
  );

  const sendMessage = useCallback(
    async (
      rawMessage: string,
      outputFormat?: string,
      project?: { id: string; files?: string[] } | null,
      approvalMode?: string,
      docStyle?: Record<string, unknown>,
    ) => {
      const message = rawMessage.trim();
      if (!message) return;

      /**
       * 上一个任务还在跑：不拦人、也不丢弃，直接排进队列。
       * 之前这里是「运行中不能发送」，用户写好的话只能先存到别处，很不顺。
       */
      if (selectRunBusy(stateRef.current)) {
        const threadId = threadIdRef.current;
        if (!threadId) {
          notify('info', '会话还没准备好，请稍等一秒再发');
          return;
        }
        const carried = stateRef.current.uploads.filter(
          (upload) => upload.status === 'parsed' || upload.status === 'staged',
        );
        const item: QueuedMessage = {
          id: `q_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
          threadId,
          text: message,
          ...(outputFormat ? { output_format: outputFormat } : {}),
          ...(docStyle && Object.keys(docStyle).length > 0 ? { doc_style: docStyle } : {}),
          project: project ?? null,
          ...(approvalMode ? { approval_mode: approvalMode } : {}),
          uploads: carried,
          created_at: new Date().toISOString(),
        };
        dispatch({ type: 'queue/add', item });
        notify('info', '当前任务还在跑，已加入队列：结束后自动接着执行');
        return;
      }

      const threadId = await ensureThread(summarizeTitle(message));
      if (!threadId) return;
      // 首次提交才会真正上传暂存素材（上传需要会话 id，但不能因此提前建会话）
      const uploaded = await flushStagedUploads(threadId);
      if (!uploaded) {
        notify('error', '素材上传失败，本次任务没有提交');
        return;
      }
      dispatch({ type: 'run/begin', threadId, message, at: new Date().toISOString() });
      await runStream(threadId, message, outputFormat, project ?? null, approvalMode, docStyle);
    },
    [ensureThread, flushStagedUploads, notify, runStream],
  );

  /**
   * 队列出队：当前没有任务在跑时，取本会话最早的一条直接执行。
   * 用 ref 加锁，避免 effect 重复触发把同一条发两遍。
   */
  const drainingRef = useRef(false);
  const drainQueue = useCallback(async () => {
    if (drainingRef.current) return;
    const current = stateRef.current;
    if (current.queuePaused) return;
    if (selectRunBusy(current)) return;
    const next = current.queue.find((item) => item.threadId === current.threadId);
    if (!next) return;

    drainingRef.current = true;
    try {
      const threadId = current.threadId;
      if (!threadId) return;
      // 素材先落地：上传失败就跳过这条（否则任务会在缺素材的情况下跑出错误结果）
      const uploaded = await flushUploads(next.uploads, threadId);
      if (!uploaded) {
        dispatch({ type: 'queue/remove', id: next.id });
        notify('error', '队列任务的素材上传失败，已跳过该条');
        return;
      }
      dispatch({ type: 'queue/remove', id: next.id });
      dispatch({
        type: 'run/begin',
        threadId,
        message: next.text,
        at: new Date().toISOString(),
      });
      await runStream(
        threadId,
        next.text,
        next.output_format,
        next.project ?? null,
        next.approval_mode,
        next.doc_style,
      );
    } finally {
      drainingRef.current = false;
    }
  }, [flushUploads, notify, runStream]);

  // 状态一空下来就看看队列里还有没有活：这就是「上一个任务完成后自动接着执行」
  useEffect(() => {
    void drainQueue();
  }, [drainQueue, state.status, state.queue, state.queuePaused, state.threadId]);

  /** 编辑排队任务：拿回输入框改，素材也一并还回去。 */
  const editQueued = useCallback((id: string) => {
    const item = stateRef.current.queue.find((entry) => entry.id === id);
    if (!item) return null;
    dispatch({ type: 'queue/remove', id });
    if (item.uploads.length > 0) dispatch({ type: 'queue/returnUploads', uploads: item.uploads });
    return item.text;
  }, []);

  /** 删除排队任务：已经传上去的素材顺手软删，免得它留在会话素材里。 */
  const removeQueued = useCallback(
    async (id: string) => {
      const item = stateRef.current.queue.find((entry) => entry.id === id);
      if (!item) return;
      dispatch({ type: 'queue/remove', id });
      for (const upload of item.uploads) {
        if (!upload.file_id) continue;
        try {
          await artifactsApi.deleteFile(upload.file_id);
        } catch {
          // 删不掉也不该拦住用户，素材最多留在会话里
        }
      }
      notify('info', '已从队列移除');
    },
    [notify],
  );

  /** 优先执行排队任务：提到队首，当前任务一结束就先跑它。 */
  const promoteQueued = useCallback(
    (id: string) => {
      const item = stateRef.current.queue.find((entry) => entry.id === id);
      if (!item) return;
      dispatch({ type: 'queue/promote', id });
      notify(
        'info',
        stateRef.current.status === 'streaming' || stateRef.current.status === 'waiting_approval'
          ? '已提到队首：当前任务结束后立刻执行这条'
          : '已解除暂停，马上接着执行这条',
      );
    },
    [notify],
  );

  const resumeQueue = useCallback(() => dispatch({ type: 'queue/resume' }), []);

  const stopRun = useCallback(() => {
    const runId = state.runId;
    abortRef.current?.abort();
    abortRef.current = null;
    dispatch({ type: 'run/stopped', at: new Date().toISOString() });
    // 用户按了停止就是想停下来：队列里有活也先歇着，别刚停就自己又跑起来
    if (stateRef.current.queue.length > 0) dispatch({ type: 'queue/pause' });

    // 先本地停流，再通知后端取消（后端取消接口可能尚未上线，404 时优雅提示）
    if (runId && !isMockMode()) {
      void runsApi.cancelRun(runId).catch((error: unknown) => {
        if (error instanceof ApiError && error.code === 'ENDPOINT_UNAVAILABLE') {
          notify('info', `${endpointUnavailableMessage('取消运行')}；已本地停止事件流`);
          return;
        }
        notify('error', `取消运行失败：${errorMessage(error)}`);
      });
    }
  }, [notify, state.runId]);

  const retryRun = useCallback(
    (outputFormat?: string, docStyle?: Record<string, unknown>) => {
      if (!state.lastUserMessage) {
        notify('info', '没有可重试的任务');
        return;
      }
      void sendMessage(state.lastUserMessage, outputFormat, undefined, undefined, docStyle);
    },
    [notify, sendMessage, state.lastUserMessage],
  );

  /* ---------------------------------------------------------------- */
  /* 审批                                                              */
  /* ---------------------------------------------------------------- */

  const submitApproval = useCallback(
    async (approvalId: string, decision: ApprovalDecision) => {
      const threadId = threadIdRef.current;
      if (!threadId) {
        notify('error', '缺少会话，无法提交审批');
        return;
      }
      dispatch({ type: 'approval/submitting', approvalId });
      try {
        await runsApi.submitApproval(threadId, approvalId, decision);
        dispatch({
          type: 'approval/decided',
          approvalId,
          decision,
          at: new Date().toISOString(),
        });
      } catch (error) {
        if (error instanceof ApiError && error.code === 'APPROVAL_ALREADY_DECIDED') {
          dispatch({
            type: 'approval/decided',
            approvalId,
            decision,
            at: new Date().toISOString(),
          });
          notify('info', '该审批已处理过（幂等）');
          return;
        }
        dispatch({
          type: 'approval/error',
          approvalId,
          message: errorMessage(error),
        });
        notify(
          'error',
          `提交审批失败：${errorMessage(error)}`,
          error instanceof ApiError ? error.traceId : null,
        );
      }
    },
    [notify],
  );

  const uploadOne = useCallback(
    async (file: File): Promise<void> => {
      const localId = `upload_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
      const ext = `.${(file.name.split('.').pop() ?? '').toLowerCase()}`;

      // 这里不再按后缀挡：拖进来的东西五花八门（旧版 .doc、.zip、相机导出的 .heic…），
      // 收不收由后端判断——它认得格式就解析，认不出就收下并说明「读不出文字」。
      // 前端拦一遍只会让人卡在「到底能传什么」上。
      const limitBytes = maxUploadBytesForFile(file.name);
      if (file.size > limitBytes) {
        const limitMb = Math.round(limitBytes / (1024 * 1024));
        dispatch({
          type: 'upload/start',
          item: {
            local_id: localId,
            filename: file.name,
            size: file.size,
            status: 'error',
            error: `文件超过 ${limitMb}MB 上限`,
          },
        });
        notify('error', `${file.name} 超过 ${limitMb}MB 上限`);
        return;
      }

      const threadId = threadIdRef.current;
      dispatch({
        type: 'upload/start',
        item: {
          local_id: localId,
          filename: file.name,
          size: file.size,
          status: threadId ? 'uploading' : 'staged',
          progress: 0,
          error: null,
          file,
          ...(ext ? { ext } : {}),
        },
      });

      // 已有会话：立刻传（用户就在这个会话里，不必等提交）
      if (threadId) await performUpload(localId, file, threadId);
    },
    [notify, performUpload],
  );

  const uploadFile = useCallback((file: File) => uploadOne(file), [uploadOne]);

  /** 多文件上传：逐个上传（每个文件独立进度与错误），顺序执行避免后端压力。 */
  const uploadFiles = useCallback(
    async (files: File[]) => {
      for (const file of files) {
        await uploadOne(file);
      }
    },
    [uploadOne],
  );

  /**
   * 移除素材：已经上传成功的要在服务端一起删掉（软删进回收站），
   * 否则只是清了本地列表，重进会话又会从 /threads/{id} 读回来。
   */
  const removeUpload = useCallback(
    async (localId: string) => {
      const upload = stateRef.current.uploads.find((item) => item.local_id === localId);
      if (!upload) return;
      if (upload.file_id) {
        try {
          await artifactsApi.deleteFile(upload.file_id);
        } catch (error) {
          notify('error', `移除素材失败：${errorMessage(error)}`);
          return;
        }
      }
      dispatch({ type: 'upload/remove', localId });
    },
    [notify],
  );

  /** 识别失败后重试：模型下载失败、CPU 忙不过来是常见原因，重跑一次比重新上传省事。 */
  const retryUpload = useCallback(
    async (localId: string) => {
      const upload = stateRef.current.uploads.find((item) => item.local_id === localId);
      const fileId = upload?.artifact_id ?? upload?.file_id;
      const threadId = threadIdRef.current;
      if (!fileId || !threadId) return;
      try {
        await artifactsApi.recognizeFile(fileId);
        dispatch({ type: 'upload/retry', localId });
        pollMedia(threadId);
      } catch (error) {
        notify('error', `重试识别失败：${errorMessage(error)}`);
      }
    },
    [notify, pollMedia],
  );

  /* ---------------------------------------------------------------- */
  /* 产物元数据 / 审计                                                 */
  /* ---------------------------------------------------------------- */

  const loadArtifactMeta = useCallback(async (artifactId: string) => {
    dispatch({ type: 'artifact/metaLoading', artifactId });
    try {
      const response = await artifactsApi.getArtifact(artifactId);
      dispatch({
        type: 'artifact/meta',
        artifactId,
        sha256: response.data.sha256,
        createdAt: response.data.created_at,
      });
    } catch (error) {
      dispatch({ type: 'artifact/metaError', artifactId, message: errorMessage(error) });
    }
  }, []);

  const openAudit = useCallback(async () => {
    const threadId = threadIdRef.current;
    dispatch({ type: 'audit/open' });
    if (!threadId) return;
    dispatch({ type: 'audit/loading' });
    try {
      const response = await auditApi.getAudit(threadId);
      dispatch({ type: 'audit/loaded', data: response.data });
    } catch (error) {
      dispatch({ type: 'audit/error', message: errorMessage(error) });
    }
  }, []);

  /**
   * 停掉一个后台任务：先断本地流，再请后端取消（接口可能未上线，失败不打扰用户）。
   * 断流后 runStream 的 finally 会走「已不是后台任务」分支，不会再弹完成提示。
   */
  const stopBackgroundTask = useCallback(
    (key: string) => {
      const task = getBackgroundTask(key);
      streamCtrlsRef.current.get(key)?.abort();
      streamCtrlsRef.current.delete(key);
      detachedRef.current.delete(key);
      removeBackgroundTask(key);
      if (task?.runId && !isMockMode()) {
        void runsApi.cancelRun(task.runId).catch(() => undefined);
      }
      notify('info', `已停止后台任务：${task?.label ?? '任务'}`);
    },
    [notify],
  );

  const closeAudit = useCallback(() => dispatch({ type: 'audit/close' }), []);
  const dismissNotice = useCallback(() => dispatch({ type: 'notice', notice: null }), []);

  const pendingApproval = selectBlockingApproval(state);
  const runBusy = selectRunBusy(state);
  const isStreaming = selectIsStreaming(state);

  return {
    state,
    pendingApproval,
    runBusy,
    isStreaming,
    sendMessage,
    stopRun,
    stopBackgroundTask,
    retryRun,
    submitApproval,
    uploadFile,
    uploadFiles,
    removeUpload,
    retryUpload,
    editQueued,
    removeQueued,
    promoteQueued,
    resumeQueue,
    renameThread,
    toggleThreadPin,
    deleteThread,
    cleanupThreads,
    reorderThreads,
    listAllThreadIds,
    newThread,
    selectThread,
    loadSessions,
    goToSessionsPage,
    loadArtifactMeta,
    openAudit,
    closeAudit,
    checkHealth,
    dismissNotice,
    notify,
  };
}

export type WorkbenchController = ReturnType<typeof useWorkbench>;
