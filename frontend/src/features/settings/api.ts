/** 设置中心接口（feature: settings，正式 /api/v1）。 */
import { isMockMode } from '../../shared/config/runtime';
import { ApiError, isEndpointUnavailable, requestV1 } from '../../shared/lib/api';
import type {
  HealthOut,
  ModelBalanceOut,
  ModelKeyDisconnectOut,
  ModelKeyOut,
  ModelListOut,
  ModelOut,
  SettingsOut,
  SettingsUpdateIn,
  SkillListOut,
  SkillOut,
  SubagentListOut,
  SubagentOut,
  ToolListOut,
  ToolOut,
} from '../../shared/api/types';
import type { ApiResponse } from '../../shared/types/api';

const MOCK_SETTINGS: SettingsOut = {
  trace_id: 'mock-trace',
  engine: 'real',
  approval_rules: ['doc.generate_report', 'file.delete', 'code.run_python'],
  mock_mode: true,
  model_provider: 'mock',
  model_name: 'mock-scripted',
  fallback_chain: ['deepseek', 'qwen', 'glm', 'mock'],
  max_upload_mb: 20,
  model_timeout_seconds: 20,
  approval_timeout_seconds: 180,
  feature_flags: { artifacts_center: true, audit_export: true },
  sources: { mock_mode: 'db', model_provider: 'db', model_name: 'db' },
  env_hints: { MOCK_MODE: 'true' },
  secrets: {
    deepseek: { configured: false, ref: 'env:DEEPSEEK_API_KEY' },
    qwen: { configured: false, ref: 'env:QWEN_API_KEY' },
    glm: { configured: false, ref: 'env:GLM_API_KEY' },
  },
  database_url: 'sqlite:///data/app.db',
  upload_dir: './data/uploads',
  artifact_dir: './data/artifacts',
  log_level: 'INFO',
  environment: 'mock',
};

/**
 * mock 模式下的模型清单：与后端一致地「列出全部已知供应商」，
 * 未配置 Key 的也返回（configured=false），界面才能标注出差异。
 */
const MOCK_MODELS: ModelOut[] = [
  {
    id: 'mock',
    provider: 'mock',
    base_url: '',
    model: 'mock-scripted',
    api_key_ref: 'mock',
    configured: true,
    enabled: true,
    priority: 0,
    builtin: true,
    last_probe: null,
    extra: {},
  },
  {
    id: 'env:deepseek',
    provider: 'deepseek',
    base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-chat',
    api_key_ref: 'env:DEEPSEEK_API_KEY',
    configured: false,
    enabled: true,
    priority: 10,
    builtin: true,
    last_probe: null,
    extra: {},
  },
  {
    id: 'env:qwen',
    provider: 'qwen',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    api_key_ref: 'env:QWEN_API_KEY',
    configured: false,
    enabled: true,
    priority: 20,
    builtin: true,
    last_probe: null,
    extra: {},
  },
  {
    id: 'env:glm',
    provider: 'glm',
    base_url: 'https://open.bigmodel.cn/api/paas/v4',
    model: 'glm-4-plus',
    api_key_ref: 'env:GLM_API_KEY',
    configured: false,
    enabled: true,
    priority: 30,
    builtin: true,
    last_probe: null,
    extra: {},
  },
  {
    // 演示模式也把它列出来：让人先看见「还有个 WorkBuddy 可以用」，再去填地址
    id: 'env:workbuddy',
    provider: 'workbuddy',
    base_url: '',
    model: 'workbuddy-chat',
    api_key_ref: 'env:WORKBUDDY_API_KEY',
    configured: false,
    enabled: true,
    priority: 40,
    builtin: true,
    last_probe: null,
    extra: {},
  },
];

export interface ModelTestResult {
  ok: boolean;
  message: string;
  latency_ms?: number;
  unavailable?: boolean;
}

/** 本机存储目录（上传素材 / 产物）：设置页需要真实路径 + 一键打开。 */
export type StorageKind = 'uploads' | 'artifacts';

export interface StoragePathOut {
  path: string;
  exists: boolean;
  files: number;
}

export interface StoragePathsOut {
  uploads: StoragePathOut;
  artifacts: StoragePathOut;
}

export interface StorageRevealOut {
  kind: StorageKind;
  path: string;
  opened: boolean;
  error: string | null;
}

/** 目录选择器：只列子目录，够用户点进去选一个位置。 */
export interface BrowseDirEntry {
  name: string;
  path: string;
}

export interface BrowseOut {
  path: string;
  parent: string | null;
  dirs: BrowseDirEntry[];
  roots: BrowseDirEntry[];
  error: string | null;
}

export interface MkdirOut {
  ok: boolean;
  path: string | null;
  error: string | null;
}

export interface StorageSetOut {
  kind: StorageKind;
  ok: boolean;
  path: string;
  exists?: boolean;
  files?: number;
  error: string | null;
}

/** 意见反馈：后端只落本机存档 + 拼邮件素材，真正的「发送」由邮件客户端完成。 */
export type FeedbackKind = 'bug' | 'idea' | 'other';

export interface FeedbackIn {
  kind: FeedbackKind;
  message: string;
  contact?: string;
  /** 附带版本/引擎/窗口形态等环境信息（不含任何文档内容） */
  include_diagnostics?: boolean;
  /** 只用于邮件正文的展示信息 */
  client?: Record<string, string>;
}

export interface FeedbackOut {
  trace_id: string;
  id: string;
  kind: string;
  saved: boolean;
  saved_path: string;
  /** 开发者收件邮箱；空串 = 还没配置，此时 mailto 也是空 */
  target: string;
  subject: string;
  body: string;
  mailto: string;
  truncated: boolean;
}

export const settingsApi = {
  /** 健康检查 + 当前模式（mock/real）。 */
  async health(signal?: AbortSignal): Promise<ApiResponse<HealthOut>> {
    if (isMockMode()) {
      return {
        data: {
          trace_id: 'mock-trace',
          status: 'ok',
          version: 'mock',
          git_sha: 'mock',
          git_sha_live: 'mock',
          mode: 'mock',
          provider: 'mock',
          model: 'mock-scripted',
          degraded: false,
          degraded_reason: '',
          mock: true,
          tools: 4,
          subagents: 1,
          skills: [],
          prompt_version: 'mock',
          engine: 'real',
          engine_effective: 'mock',
          engine_supported: true,
          engine_reason: '演示数据：没有真实后端',
          model_ready: true,
          model_hint: '',
          engines: ['mock', 'real', 'deepagents'],
          approval_tools: ['doc.generate_report', 'file.delete', 'code.run_python'],
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<HealthOut>('/health', 'GET', { signal, timeoutMs: 4000 });
  },

  async getSettings(signal?: AbortSignal): Promise<ApiResponse<SettingsOut>> {
    if (isMockMode()) return { data: MOCK_SETTINGS, traceId: 'mock-trace' };
    return requestV1<SettingsOut>('/settings', 'GET', { signal });
  },

  /** 本机存储目录：上传素材 / 产物的绝对路径 + 文件数（设置页要能真访问）。 */
  async getStoragePaths(signal?: AbortSignal): Promise<ApiResponse<StoragePathsOut>> {
    if (isMockMode()) {
      return {
        data: {
          uploads: { path: 'data/uploads', exists: true, files: 0 },
          artifacts: { path: 'data/artifacts', exists: true, files: 0 },
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<StoragePathsOut>('/storage/paths', 'GET', { signal });
  },

  /** 在系统文件管理器里打开目录（后端只允许 uploads / artifacts 两个固定目录）。 */
  async revealStorage(
    kind: StorageKind,
    signal?: AbortSignal,
  ): Promise<ApiResponse<StorageRevealOut>> {
    if (isMockMode()) {
      return {
        data: { kind, path: `data/${kind}`, opened: true, error: null },
        traceId: 'mock-trace',
      };
    }
    return requestV1<StorageRevealOut>('/storage/reveal', 'POST', {
      signal,
      body: JSON.stringify({ kind }),
    });
  },

  /** 浏览本机文件夹（目录选择器）：只列子目录，不列文件。 */
  async browseDir(path: string | null, signal?: AbortSignal): Promise<ApiResponse<BrowseOut>> {
    if (isMockMode()) {
      return {
        data: {
          path: path ?? 'C:\\Users\\demo',
          parent: 'C:\\Users',
          dirs: [{ name: 'Documents', path: 'C:\\Users\\demo\\Documents' }],
          roots: [{ name: 'C:', path: 'C:\\' }],
          error: null,
        },
        traceId: 'mock-trace',
      };
    }
    const query = path ? `?path=${encodeURIComponent(path)}` : '';
    return requestV1<BrowseOut>(`/storage/browse${query}`, 'GET', { signal });
  },

  /** 在浏览到的位置新建文件夹，省得用户先去资源管理器建好再回来选。 */
  async makeDir(path: string, name: string, signal?: AbortSignal): Promise<ApiResponse<MkdirOut>> {
    if (isMockMode()) {
      return {
        data: { ok: true, path: `${path}\\${name}`, error: null },
        traceId: 'mock-trace',
      };
    }
    return requestV1<MkdirOut>('/storage/browse/mkdir', 'POST', {
      signal,
      body: JSON.stringify({ path, name }),
    });
  },

  /** 修改存储目录（绝对路径）；传 null 表示恢复默认目录。 */
  async setStoragePath(
    kind: StorageKind,
    path: string | null,
    signal?: AbortSignal,
  ): Promise<ApiResponse<StorageSetOut>> {
    if (isMockMode()) {
      return {
        data: {
          kind,
          ok: true,
          path: path ?? `data/${kind}`,
          exists: true,
          files: 0,
          error: null,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<StorageSetOut>('/storage/paths', 'PUT', {
      signal,
      body: JSON.stringify({ kind, path }),
    });
  },

  /**
   * 提交意见反馈：后端写一条本机存档，并返回邮件素材（标题/正文/mailto）。
   * 邮箱没配时 `target`/`mailto` 为空，界面走「复制内容自己发」。
   */
  async sendFeedback(payload: FeedbackIn, signal?: AbortSignal): Promise<ApiResponse<FeedbackOut>> {
    if (isMockMode()) {
      const body = `${payload.message}\n\n—— 演示模式：不会真的发信 ——`;
      return {
        data: {
          trace_id: 'mock-trace',
          id: 'fb_mock',
          kind: payload.kind,
          saved: true,
          saved_path: 'data/feedback/feedback.jsonl',
          target: '',
          subject: '[Office Agent] 功能建议',
          body,
          mailto: '',
          truncated: false,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<FeedbackOut>('/feedback', 'POST', {
      signal,
      body: JSON.stringify(payload),
    });
  },

  async updateSettings(
    patch: SettingsUpdateIn,
    signal?: AbortSignal,
  ): Promise<ApiResponse<SettingsOut>> {
    if (isMockMode()) {
      return {
        data: { ...MOCK_SETTINGS, ...patch, trace_id: 'mock-trace' } as SettingsOut,
        traceId: 'mock-trace',
      };
    }
    return requestV1<SettingsOut>('/settings', 'PUT', {
      signal,
      body: JSON.stringify(patch),
    });
  },

  async listModels(signal?: AbortSignal): Promise<ApiResponse<ModelListOut>> {
    if (isMockMode()) {
      return { data: { trace_id: 'mock-trace', models: MOCK_MODELS }, traceId: 'mock-trace' };
    }
    return requestV1<ModelListOut>('/models', 'GET', { signal });
  },

  /**
   * 登记/更新模型供应商（api_key_ref 只允许 env:NAME，后端不存明文 Key）。
   * mock 模式下写入本地内存列表，便于无后端演示完整流程。
   */
  async upsertModel(
    payload: {
      id?: string;
      provider: string;
      model?: string;
      api_key_ref: string;
      base_url?: string;
    },
    signal?: AbortSignal,
  ): Promise<ApiResponse<ModelOut>> {
    if (isMockMode()) {
      const existing = MOCK_MODELS.find((item) => item.provider === payload.provider);
      const next: ModelOut = existing
        ? { ...existing, api_key_ref: payload.api_key_ref }
        : {
            id: `mock-${payload.provider}`,
            provider: payload.provider,
            base_url: payload.base_url ?? '',
            model: payload.model ?? `${payload.provider}-chat`,
            api_key_ref: payload.api_key_ref,
            configured: false,
            enabled: true,
            priority: 100,
            builtin: false,
            last_probe: null,
            extra: {},
          };
      if (existing) {
        MOCK_MODELS[MOCK_MODELS.indexOf(existing)] = next;
      } else {
        MOCK_MODELS.push(next);
      }
      return { data: next, traceId: 'mock-trace' };
    }
    return requestV1<ModelOut>('/models', 'POST', {
      signal,
      body: JSON.stringify(payload),
    });
  },

  /**
   * 保存供应商 Key（明文只经 HTTPS 发到本机后端，落本地 .env；响应仅回掩码）。
   * mock 模式只把状态置为「已配置」，不保存任何明文。
   */
  async saveModelKey(
    modelId: string,
    payload: { api_key: string; env_name?: string },
    signal?: AbortSignal,
  ): Promise<ApiResponse<ModelKeyOut>> {
    if (isMockMode()) {
      const target = MOCK_MODELS.find(
        (item) => item.id === modelId || item.provider === modelId.replace(/^env:/, ''),
      );
      if (target) target.configured = true;
      return {
        data: {
          trace_id: 'mock-trace',
          provider: target?.provider ?? modelId.replace(/^env:/, ''),
          api_key_ref: target?.api_key_ref ?? `env:${payload.env_name ?? 'API_KEY'}`,
          configured: true,
          masked: `${payload.api_key.slice(0, 3)}****${payload.api_key.slice(-4)}`,
          persisted: false,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<ModelKeyOut>(`/models/${encodeURIComponent(modelId)}/key`, 'PUT', {
      signal,
      body: JSON.stringify(payload),
    });
  },

  /**
   * 断开某个模型的 Key：后端把进程 env、Settings 与本地 .env 三处同清，
   * 分享/部署项目前用它止损（Key 留在 .env 里会跟着数据目录被拷走）。
   */
  async removeModelKey(
    modelId: string,
    signal?: AbortSignal,
  ): Promise<ApiResponse<ModelKeyDisconnectOut>> {
    if (isMockMode()) {
      const target = MOCK_MODELS.find(
        (item) => item.id === modelId || item.provider === modelId.replace(/^env:/, ''),
      );
      if (target) target.configured = false;
      return {
        data: {
          trace_id: 'mock-trace',
          provider: target?.provider ?? modelId.replace(/^env:/, ''),
          api_key_ref: target?.api_key_ref ?? `env:API_KEY`,
          configured: false,
          disconnected: true,
          persisted: true,
        },
        traceId: 'mock-trace',
      };
    }
    return requestV1<ModelKeyDisconnectOut>(
      `/models/${encodeURIComponent(modelId)}/key`,
      'DELETE',
      {
        signal,
      },
    );
  },

  async listTools(signal?: AbortSignal): Promise<ApiResponse<ToolListOut>> {
    if (isMockMode()) return { data: { trace_id: 'mock-trace', tools: [] }, traceId: 'mock-trace' };
    return requestV1<ToolListOut>('/tools', 'GET', { signal });
  },

  async listSubagents(signal?: AbortSignal): Promise<ApiResponse<SubagentListOut>> {
    if (isMockMode()) {
      return { data: { trace_id: 'mock-trace', subagents: [] }, traceId: 'mock-trace' };
    }
    return requestV1<SubagentListOut>('/subagents', 'GET', { signal });
  },

  async listSkills(signal?: AbortSignal): Promise<ApiResponse<SkillListOut>> {
    if (isMockMode()) {
      return {
        data: { trace_id: 'mock-trace', skills: [], prompt_chars: 0 },
        traceId: 'mock-trace',
      };
    }
    return requestV1<SkillListOut>('/skills', 'GET', { signal });
  },

  /**
   * 账户余额：GET /models/{model_id}/balance（DeepSeek 有 /user/balance）。
   * 对账用——拿同一把 Key 问供应商还有多少钱，跟控制台一比就知道是不是同一个账号。
   */
  async getBalance(modelId: string, signal?: AbortSignal): Promise<ApiResponse<ModelBalanceOut>> {
    return requestV1<ModelBalanceOut>(`/models/${encodeURIComponent(modelId)}/balance`, 'GET', {
      signal,
      timeoutMs: 20_000,
    });
  },

  /**
   * 连通性测试：POST /models/{model_id}/test。
   * 后端未上线该端点（404）时返回 unavailable=true，设置页展示版本提示。
   */
  async testModel(modelId: string, signal?: AbortSignal): Promise<ModelTestResult> {
    if (isMockMode()) {
      return { ok: true, message: 'mock 模式无需真实连通（本地 fixture）', latency_ms: 1 };
    }
    try {
      const response = await requestV1<{
        ok?: boolean;
        reason?: string | null;
        latency_ms?: number;
        returned_model?: string | null;
      }>(`/models/${encodeURIComponent(modelId)}/test`, 'POST', {
        signal,
        timeoutMs: 30_000,
      });
      const ok = Boolean(response.data.ok);
      return {
        ok,
        message: ok
          ? `连接正常${response.data.returned_model ? `（${response.data.returned_model}）` : ''}`
          : (response.data.reason ?? '连接失败'),
        latency_ms: response.data.latency_ms,
      };
    } catch (error) {
      if (isEndpointUnavailable(error)) {
        return { ok: false, unavailable: true, message: '当前后端版本较低，暂不支持测试连接' };
      }
      if (error instanceof ApiError) return { ok: false, message: error.message };
      return { ok: false, message: '连通性测试失败' };
    }
  },
};

export type { ModelOut, SettingsOut, SkillOut, SubagentOut, ToolOut };
