/** 产物接口（feature: artifacts，正式 /api/v1）。 */
import {
  MEDIA_KIND_LABELS,
  OUTPUT_FORMATS,
  UPLOADABLE_EXTENSIONS,
  maxUploadMbForFile,
  mediaKindOf,
} from '../../shared/config/output-formats';
import { isMockMode } from '../../shared/config/runtime';
import { API_V1_BASE, UPLOAD_TIMEOUT_MS } from '../../shared/config/runtime';
import { encodeId, requestV1 } from '../../shared/lib/api';
import { notifyArtifactsChanged } from '../../shared/lib/artifacts-signal';
import { mockGetArtifact, mockUploadFile } from '../../shared/lib/mock-run';
import type { ArtifactOut } from '../../shared/api/types';
import type { ApiResponse, ThreadFile, UploadResponse } from '../../shared/types/api';

export interface ArtifactListQuery {
  threadId?: string;
  runId?: string;
  type?: string;
  page?: number;
  pageSize?: number;
}

export interface ArtifactListData {
  artifacts: ArtifactOut[];
  total: number;
  page: number;
  page_size: number;
}

/** 上传结果（兼容 v0.1 单文件顶层字段 + files 列表 + 文本预览）。 */
export interface UploadResult extends UploadResponse {
  text_preview?: string;
  files?: UploadResponse[];
}

export interface ThreadFileListData {
  thread_id?: string;
  files: ThreadFile[];
}

/** 批量删除的单条结果（部分成功语义：失败的 ID 逐条给出原因）。 */
export interface BatchDeleteItem {
  artifact_id: string;
  deleted: boolean;
  message: string;
}

export interface BatchDeleteResult {
  requested: number;
  deleted: number;
  failed: BatchDeleteItem[];
  trashed: string[];
}

/** 回收站条目：比普通产物多「删除时间」与「文件是否还在」。 */
export interface TrashItem extends ArtifactOut {
  deleted_at: string | null;
  restorable: boolean;
}

export interface TrashListData {
  artifacts: TrashItem[];
  total: number;
  page: number;
  page_size: number;
}

/** 用系统默认程序打开的结果（装了 WPS 通常就是 WPS）。 */
export interface OpenFileResult {
  artifact_id: string;
  path: string;
  opened: boolean;
  error: string | null;
}

/** 支持的上传扩展名：文档 + 媒体，一律从共享格式表取（后端同一个来源）。 */
export const ACCEPTED_UPLOAD_EXTENSIONS = UPLOADABLE_EXTENSIONS;

/** 单文件大小上限 20MB（与后端 max_upload_mb 默认值一致）。 */
export const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

/** 图片 / 录音 / 视频的上限（与后端 max_media_mb 默认值一致）。 */
export const MAX_MEDIA_BYTES = 200 * 1024 * 1024;

/** 按文件类型给出上限：文档 20MB，图片与音视频 200MB。 */
export function maxUploadBytesForFile(filename: string): number {
  return maxUploadMbForFile(filename) * 1024 * 1024;
}

/**
 * 产物类型：产物中心只列 Agent 生成的文件。
 * 上传素材（type=upload）不是产物——文件名经常撞车（上传 cet4成绩.pdf → 生成 cet4成绩.pdf），
 * 混进产物列表根本分不清哪个是结果；素材在工作台右侧「本次素材」里看。
 *
 * 顺序是**筛选下拉的展示顺序**（Word、表格、PDF、PPT、文本），不是格式表的顺序；
 * 有哪些类型仍由格式表决定，删/加格式不用改这里。
 */
const ARTIFACT_TYPE_ORDER = ['docx', 'xlsx', 'pdf', 'pptx', 'txt'];

export const ARTIFACT_TYPES = ARTIFACT_TYPE_ORDER.filter((type) =>
  (OUTPUT_FORMATS as readonly string[]).includes(type),
);

/** 每个类型都要有中文标明，缺失时回退为类型名本身。
 *  upload 只出现在素材列表（工作台右栏），产物中心用不到，但标签留着兜底。 */
export const ARTIFACT_TYPE_LABELS: Record<string, string> = {
  docx: 'Word 文档',
  xlsx: 'Excel 表格',
  pdf: 'PDF',
  pptx: 'PPT 演示文稿',
  txt: '文本',
  md: 'Markdown',
  csv: 'CSV 表格',
  html: '网页',
  upload: '上传文件',
};

export type ArtifactTone = 'brand' | 'ok' | 'warn' | 'neutral' | 'accent';

/** 类型徽标色调（产物卡片 / 产物中心 / 素材列表共用）。 */
export function artifactTypeTone(type: string): ArtifactTone {
  if (type === 'docx' || type === 'html') return 'brand';
  if (type === 'xlsx' || type === 'csv') return 'ok';
  if (type === 'pdf' || type === 'pptx') return 'warn';
  if (type === 'md') return 'accent';
  return 'neutral';
}

/** 上传素材的类型标签：优先按扩展名命中，未知名回退大写扩展名。
 *  图片 / 录音 / 视频不报「PNG」「MP3」，而是说清是哪一类素材（图片、会议录音…），
 *  因为它们和文档不是一回事：传进来还要等识别。 */
export function uploadTypeLabel(filename: string, ext?: string): string {
  const rawExt = (ext ?? filename.split('.').pop() ?? '').replace(/^\./, '').toLowerCase();
  if (!rawExt) return '文件';
  const kind = mediaKindOf(`x.${rawExt}`);
  if (kind) return MEDIA_KIND_LABELS[kind] ?? rawExt.toUpperCase();
  return ARTIFACT_TYPE_LABELS[rawExt] ?? rawExt.toUpperCase();
}

function toArtifactOut(meta: {
  artifact_id: string;
  type: string;
  filename: string;
  size: number;
  sha256?: string;
  created_at?: string;
  download_url: string;
  preview_url: string;
  thread_id?: string;
  run_id?: string | null;
}): ArtifactOut {
  return {
    artifact_id: meta.artifact_id,
    type: meta.type,
    filename: meta.filename,
    size: meta.size,
    sha256: meta.sha256 ?? '',
    content_type: '',
    created_at: meta.created_at ?? new Date().toISOString(),
    thread_id: meta.thread_id ?? '',
    run_id: meta.run_id ?? null,
    download_url: meta.download_url,
    preview_url: meta.preview_url,
    extra: {},
    has_preview_file: false,
    has_text: true,
  };
}

export const artifactsApi = {
  async listArtifacts(
    query: ArtifactListQuery = {},
    signal?: AbortSignal,
  ): Promise<ApiResponse<ArtifactListData>> {
    if (isMockMode()) {
      const known = mockGetArtifact('art_01');
      const items = known.data ? [toArtifactOut(known.data)] : [];
      return {
        data: { artifacts: items, total: items.length, page: 1, page_size: 20 },
        traceId: known.traceId ?? null,
      };
    }
    const params = new URLSearchParams();
    if (query.threadId) params.set('thread_id', query.threadId);
    if (query.runId) params.set('run_id', query.runId);
    if (query.type) params.set('type', query.type);
    params.set('page', String(query.page ?? 1));
    params.set('page_size', String(query.pageSize ?? 20));
    const search = params.toString();
    return requestV1<ArtifactListData>(`/artifacts${search ? `?${search}` : ''}`, 'GET', {
      signal,
    });
  },

  async getArtifact(artifactId: string, signal?: AbortSignal): Promise<ApiResponse<ArtifactOut>> {
    if (isMockMode()) {
      const response = mockGetArtifact(artifactId);
      return { data: toArtifactOut(response.data), traceId: response.traceId ?? null };
    }
    return requestV1<ArtifactOut>(`/artifacts/${encodeId(artifactId)}`, 'GET', { signal });
  },

  /** 下载地址（后端 FileResponse，软删后 404）。 */
  artifactDownloadUrl(artifactId: string): string {
    return `${API_V1_BASE}/artifacts/${encodeId(artifactId)}/download`;
  },

  /**
   * 内联地址：同一个下载接口加 `inline=1`，让 Content-Disposition 变成 inline。
   * 预览 iframe 必须用它——默认的 attachment 会让浏览器直接下载 PDF，点了「预览」反而落盘。
   */
  artifactInlineUrl(artifactId: string): string {
    return `${this.artifactDownloadUrl(artifactId)}?inline=1`;
  },

  /** 预览地址（后端 HTML 片段，可在新标签打开）。 */
  artifactPreviewUrl(artifactId: string): string {
    return `${API_V1_BASE}/artifacts/${encodeId(artifactId)}/preview`;
  },

  /**
   * 上传素材（XHR 以支持上传进度）。
   * 成功后返回与后端 UploadResultOut 一致的结构（顶层为首个文件字段）。
   */
  uploadFile(
    threadId: string,
    file: File,
    options: { onProgress?: (progress: number) => void; signal?: AbortSignal } = {},
  ): Promise<ApiResponse<UploadResult>> {
    if (isMockMode()) {
      return mockUploadFile(threadId, file).then((response) => ({
        data: response.data as UploadResult,
        traceId: response.traceId ?? null,
      }));
    }
    return new Promise<ApiResponse<UploadResult>>((resolve, reject) => {
      const form = new FormData();
      form.append('file', file);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${API_V1_BASE}/threads/${encodeId(threadId)}/files`);
      xhr.responseType = 'text';
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && options.onProgress) {
          options.onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => {
        let raw: unknown = null;
        try {
          raw = xhr.responseText ? (JSON.parse(xhr.responseText) as unknown) : null;
        } catch {
          raw = null;
        }
        if (xhr.status >= 200 && xhr.status < 300) {
          const trace =
            raw &&
            typeof raw === 'object' &&
            typeof (raw as { trace_id?: unknown }).trace_id === 'string'
              ? ((raw as { trace_id: string }).trace_id as string)
              : null;
          resolve({ data: raw as UploadResult, traceId: trace });
          return;
        }
        const body = raw as {
          error?: { code?: string; message?: string };
          trace_id?: string;
        } | null;
        const message = body?.error?.message ?? `上传失败（HTTP ${xhr.status}）`;
        const error = new Error(message) as Error & {
          code?: string;
          status?: number;
          traceId?: string | null;
        };
        error.code = body?.error?.code ?? `HTTP_${xhr.status}`;
        error.status = xhr.status;
        error.traceId = body?.trace_id ?? null;
        reject(error);
      };
      xhr.onerror = () => reject(new Error('无法连接后端（/api 代理未通或服务未启动）'));
      xhr.ontimeout = () => reject(new Error('上传超时'));
      xhr.timeout = UPLOAD_TIMEOUT_MS;
      if (options.signal) {
        options.signal.addEventListener('abort', () => xhr.abort(), { once: true });
      }
      xhr.send(form);
    });
  },

  /**
   * 会话素材列表：比整份会话详情轻得多，用来轮询「识别好了没」。
   * 图片 OCR 几秒、录音转写几分钟，界面靠这条接口把状态从「识别中」翻成字数。
   */
  async listThreadFiles(
    threadId: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ThreadFileListData>> {
    if (isMockMode()) return { data: { files: [] }, traceId: null };
    return requestV1<ThreadFileListData>(`/threads/${encodeId(threadId)}/files`, 'GET', { signal });
  },

  /** 识别失败后重试：模型没下下来、机器临时忙不过来时不用删了重传。 */
  async recognizeFile(
    fileId: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<{ artifact_id: string; status: string }>> {
    if (isMockMode()) return { data: { artifact_id: fileId, status: 'processing' }, traceId: null };
    return requestV1<{ artifact_id: string; status: string }>(
      `/files/${encodeId(fileId)}/recognize`,
      'POST',
      { signal },
    );
  },

  /** 拉取产物文本预览（后端返回 HTML 片段，剥掉标签后取前 limit 字）。 */
  async fetchPreviewText(artifactId: string, limit = 200): Promise<string> {
    if (isMockMode()) {
      const known = mockGetArtifact(artifactId);
      return (known.data.filename ?? '').slice(0, limit);
    }
    const response = await fetch(artifactsApi.artifactPreviewUrl(artifactId), {
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`预览不可用（HTTP ${response.status}）`);
    const html = await response.text();
    const matched = /<pre[^>]*>([\s\S]*?)<\/pre>/i.exec(html);
    const source = matched?.[1] ?? html.replace(/<[^>]+>/g, ' ');
    const decoded = source
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&amp;/g, '&');
    return decoded.trim().slice(0, limit);
  },

  async deleteArtifact(artifactId: string, signal?: AbortSignal): Promise<ApiResponse<unknown>> {
    const response = await requestV1<unknown>(`/artifacts/${encodeId(artifactId)}`, 'DELETE', {
      signal,
    });
    // 删完喊一声：会话列表的「N 产物」要跟着变（它不由产物列表驱动）
    notifyArtifactsChanged();
    return response;
  },

  /**
   * 删除会话素材（软删 + 移入回收站）。
   * 移除按钮如果只清本地状态，重进会话时素材会从服务端再读回来——所以必须落库。
   */
  async deleteFile(fileId: string, signal?: AbortSignal): Promise<ApiResponse<unknown>> {
    if (isMockMode()) return { data: { deleted: true }, traceId: null };
    return requestV1<unknown>(`/files/${encodeId(fileId)}`, 'DELETE', { signal });
  },

  /** 回收站列表（已软删的产物，按删除时间倒序）。 */
  async listTrash(
    page = 1,
    pageSize = 20,
    signal?: AbortSignal,
  ): Promise<ApiResponse<TrashListData>> {
    if (isMockMode()) {
      return { data: { artifacts: [], total: 0, page, page_size: pageSize }, traceId: null };
    }
    return requestV1<TrashListData>(`/artifacts/trash?page=${page}&page_size=${pageSize}`, 'GET', {
      signal,
    });
  },

  /** 从回收站恢复（文件挪回原目录）。 */
  async restoreArtifact(artifactId: string, signal?: AbortSignal): Promise<ApiResponse<unknown>> {
    if (isMockMode()) return { data: { restored: true }, traceId: null };
    const response = await requestV1<unknown>(
      `/artifacts/${encodeId(artifactId)}/restore`,
      'POST',
      {
        signal,
      },
    );
    notifyArtifactsChanged();
    return response;
  },

  /** 彻底删除（回收站里的文件与记录一起清掉，不可恢复）。 */
  async purgeArtifact(artifactId: string, signal?: AbortSignal): Promise<ApiResponse<unknown>> {
    if (isMockMode()) return { data: { purged: true }, traceId: null };
    const response = await requestV1<unknown>(
      `/artifacts/${encodeId(artifactId)}/purge`,
      'DELETE',
      {
        signal,
      },
    );
    notifyArtifactsChanged();
    return response;
  },

  /** 用系统默认程序打开文件：装了 WPS 就是 WPS，装了 Office 就是 Office。 */
  async openArtifact(
    artifactId: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<OpenFileResult>> {
    if (isMockMode()) {
      return {
        data: {
          artifact_id: artifactId,
          path: '',
          opened: false,
          error: '演示模式不会真的打开本地文件',
        },
        traceId: null,
      };
    }
    return requestV1<OpenFileResult>(`/artifacts/${encodeId(artifactId)}/open`, 'POST', { signal });
  },

  /** 批量软删（单次上限 200，后端去重；失败的 ID 逐条返回，不影响其余）。 */
  async deleteArtifacts(
    artifactIds: string[],
    signal?: AbortSignal,
  ): Promise<ApiResponse<BatchDeleteResult>> {
    if (isMockMode()) {
      notifyArtifactsChanged();
      return {
        data: {
          requested: artifactIds.length,
          deleted: artifactIds.length,
          failed: [],
          trashed: [],
        },
        traceId: null,
      };
    }
    const response = await requestV1<BatchDeleteResult>('/artifacts/batch-delete', 'POST', {
      signal,
      body: JSON.stringify({ artifact_ids: artifactIds }),
    });
    notifyArtifactsChanged();
    return response;
  },
};
