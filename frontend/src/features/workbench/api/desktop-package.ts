/**
 * 桌面端安装包接口（正式 /api/v1）。
 *
 * 「下载」不是浏览器下载，而是让本机后端把安装包复制到下载目录：只有这样页面才拿得到
 * 真实绝对路径，用户删掉桌面端之后还能照着这个路径把文件找回来。
 * 后端记不住（没有安装包 / 目录不可写）时，组件退回旧的「打开下载链接」方式。
 */
import { isMockMode } from '../../../shared/config/runtime';
import { requestV1 } from '../../../shared/lib/api';
import type { ApiResponse } from '../../../shared/types/api';

export interface DesktopSavedOut {
  /** 保存完成时的绝对路径 */
  path: string;
  filename: string;
  size: number;
  saved_at: string;
  /** 此刻文件是否还在；被删 / 被移走为 false */
  exists: boolean;
  dir_exists: boolean;
  /** exists=false 时的原因（缺文件 / 缺目录） */
  error: string | null;
}

export interface DesktopPackageOut {
  trace_id?: string;
  available: boolean;
  filename: string;
  size: number;
  platform: string;
  /** 不指定目录时的默认保存位置（系统下载目录） */
  default_dir: string;
  saved: DesktopSavedOut | null;
}

export interface DesktopDownloadOut {
  trace_id?: string;
  ok: boolean;
  path: string | null;
  saved: DesktopSavedOut | null;
  error: string | null;
}

export interface DesktopActionOut {
  trace_id?: string;
  ok: boolean;
  path: string | null;
  exists: boolean;
  error: string | null;
}

/** mock 模式下假装「这次会话里存过一次」，界面不会一进来就空着。 */
let mockSaved: DesktopSavedOut | null = null;

const MOCK_DIR = 'C:\\Users\\demo\\Downloads';

function mockStatus(): DesktopPackageOut {
  return {
    trace_id: 'mock-trace',
    available: true,
    filename: 'Office Agent.exe',
    size: 38_398_060,
    platform: 'windows',
    default_dir: MOCK_DIR,
    saved: mockSaved,
  };
}

export const desktopPackageApi = {
  /** 可交付状态 + 上次保存的位置（页面进来就读，刷新不丢）。 */
  async status(signal?: AbortSignal): Promise<ApiResponse<DesktopPackageOut>> {
    if (isMockMode()) {
      return { data: mockStatus(), traceId: 'mock-trace' };
    }
    return requestV1<DesktopPackageOut>('/desktop/package', 'GET', { signal });
  },

  /** 把安装包保存到本机；不传目录就落进系统下载目录。 */
  async download(
    targetDir?: string | null,
    signal?: AbortSignal,
  ): Promise<ApiResponse<DesktopDownloadOut>> {
    if (isMockMode()) {
      mockSaved = {
        path: `${MOCK_DIR}\\Office Agent.exe`,
        filename: 'Office Agent.exe',
        size: 38_398_060,
        saved_at: new Date().toISOString(),
        exists: true,
        dir_exists: true,
        error: null,
      };
      return {
        data: {
          trace_id: 'mock-trace',
          ok: true,
          path: mockSaved.path,
          saved: mockSaved,
          error: null,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<DesktopDownloadOut>('/desktop/package/download', 'POST', {
      body: JSON.stringify({ target_dir: targetDir ?? null }),
      signal,
    });
  },

  /** 在系统文件管理器里定位这个文件（文件没了就打开所在目录）。 */
  async reveal(signal?: AbortSignal): Promise<ApiResponse<DesktopActionOut>> {
    if (isMockMode()) {
      return {
        data: {
          trace_id: 'mock-trace',
          ok: true,
          path: mockSaved?.path ?? null,
          exists: Boolean(mockSaved),
          error: null,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<DesktopActionOut>('/desktop/package/reveal', 'POST', { signal });
  },

  /** 打开安装包 / 再次启动桌面端。 */
  async open(signal?: AbortSignal): Promise<ApiResponse<DesktopActionOut>> {
    if (isMockMode()) {
      return {
        data: {
          trace_id: 'mock-trace',
          ok: true,
          path: mockSaved?.path ?? null,
          exists: Boolean(mockSaved),
          error: null,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<DesktopActionOut>('/desktop/package/open', 'POST', { signal });
  },
};
