/**
 * 设置中心接口单测（mock 模式 + 真实请求两条路径都要覆盖）。
 *
 * 设置页是「唯一能写入密钥」的入口，其中 saveModelKey 是本轮新增能力
 * （可直接粘贴供应商 Key），因此重点断言：
 *   - 明文只出现在请求体里，返回值必须是掩码；
 *   - mock 模式绝不落盘任何明文。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const state = vi.hoisted(() => ({ mockMode: false }));

vi.mock('../../shared/config/runtime', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../shared/config/runtime')>();
  return { ...actual, isMockMode: () => state.mockMode };
});

const STORAGE_KEY = 'office-agent.user-templates.v1';

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => 'application/json' },
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** 重新加载模块，拿到干净的 MOCK_MODELS（mock 分支会就地修改这个数组）。 */
async function freshSettingsApi() {
  vi.resetModules();
  const module = await import('./api');
  return module.settingsApi;
}

function fetchMock(): ReturnType<typeof vi.fn> {
  return globalThis.fetch as unknown as ReturnType<typeof vi.fn>;
}

function lastCall(): [string, { method?: string; body?: string }] {
  const mock = fetchMock();
  const call = mock.mock.calls[mock.mock.calls.length - 1] as
    [string, { method?: string; body?: string }] | undefined;
  if (!call) throw new Error('还没有发生任何 fetch 调用');
  return call;
}

beforeEach(() => {
  state.mockMode = false;
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => jsonResponse(200, {})),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
  window.localStorage.removeItem(STORAGE_KEY);
});

/* ------------------------------------------------------------------ */
/* mock 模式                                                           */
/* ------------------------------------------------------------------ */

describe('settingsApi（mock 模式）', () => {
  beforeEach(() => {
    state.mockMode = true;
  });

  it('health 返回 mock 运行信息，不发任何请求', async () => {
    const api = await freshSettingsApi();
    const result = await api.health();
    expect(result.data.status).toBe('ok');
    expect(result.data.mock).toBe(true);
    expect(result.data.engine_effective).toBe('mock');
    expect(result.traceId).toBe('mock-trace');
    expect(fetchMock()).not.toHaveBeenCalled();
  });

  it('getSettings 返回本地 fixture，含审批规则与密钥引用', async () => {
    const api = await freshSettingsApi();
    const result = await api.getSettings();
    expect(result.data.approval_rules).toContain('file.delete');
    expect(result.data.secrets.deepseek?.ref).toBe('env:DEEPSEEK_API_KEY');
    // 关键：mock 数据里不应出现任何明文密钥
    expect(JSON.stringify(result.data)).not.toMatch(/sk-[A-Za-z0-9]{8,}/);
  });

  it('updateSettings 合并 patch 并覆盖 trace_id', async () => {
    const api = await freshSettingsApi();
    const result = await api.updateSettings({
      mock_mode: false,
      model_provider: 'deepseek',
      max_upload_mb: 64,
    });
    expect(result.data.model_provider).toBe('deepseek');
    expect(result.data.max_upload_mb).toBe(64);
    expect(result.data.trace_id).toBe('mock-trace');
  });

  it('listModels 列出全部已知供应商，只有 mock 是已配置', async () => {
    const api = await freshSettingsApi();
    const result = await api.listModels();
    const models = result.data.models;
    expect(models).toHaveLength(5);
    expect(models[0]).toMatchObject({ id: 'mock', builtin: true, configured: true });
    // 未配置 Key 的供应商也要返回，界面才能标注出差异
    const others = models.slice(1);
    expect(others.map((model) => model.provider)).toEqual(['deepseek', 'qwen', 'glm', 'workbuddy']);
    expect(others.every((model) => model.configured === false)).toBe(true);
    // WorkBuddy 没有默认端点：列表里要能看出「缺的是地址」而不是「缺 Key」
    expect(others[3]).toMatchObject({ base_url: '', api_key_ref: 'env:WORKBUDDY_API_KEY' });
  });

  it('upsertModel：已存在供应商就地更新，新供应商才追加', async () => {
    const api = await freshSettingsApi();
    // 已知供应商（deepseek）再登记一次：只更新引用，不新增条目
    const updated = await api.upsertModel({
      provider: 'deepseek',
      api_key_ref: 'env:DEEPSEEK_API_KEY',
      base_url: 'https://example.test/v1',
    });
    expect(updated.data).toMatchObject({
      id: 'env:deepseek',
      provider: 'deepseek',
      api_key_ref: 'env:DEEPSEEK_API_KEY',
    });
    expect((await api.listModels()).data.models).toHaveLength(5);

    // 未知供应商才追加
    const created = await api.upsertModel({
      provider: 'openai',
      api_key_ref: 'env:OPENAI_API_KEY',
    });
    expect(created.data).toMatchObject({
      id: 'mock-openai',
      provider: 'openai',
      api_key_ref: 'env:OPENAI_API_KEY',
      configured: false,
      builtin: false,
    });
    expect((await api.listModels()).data.models).toHaveLength(6);
  });

  it('saveModelKey：置为已配置，返回掩码且 persisted=false（不落盘明文）', async () => {
    const api = await freshSettingsApi();
    const result = await api.saveModelKey('mock', { api_key: 'sk-abcdefgh1234' });
    expect(result.data).toMatchObject({
      provider: 'mock',
      configured: true,
      persisted: false,
      masked: 'sk-****1234',
    });
    expect(result.data.api_key_ref).toBe('mock');
    expect((await api.listModels()).data.models[0]?.configured).toBe(true);
  });

  it('saveModelKey：未知 id 时用 env: 前缀推断 provider 并回默认引用名', async () => {
    const api = await freshSettingsApi();
    const result = await api.saveModelKey('env:GLM_API_KEY', { api_key: 'sk-0123456789abcdef' });
    expect(result.data.provider).toBe('GLM_API_KEY');
    expect(result.data.api_key_ref).toBe('env:API_KEY');
    expect(result.data.masked).toBe('sk-****cdef');
  });

  it('saveModelKey：可自定义 env_name', async () => {
    const api = await freshSettingsApi();
    const result = await api.saveModelKey('env:QWEN_API_KEY', {
      api_key: 'sk-aaaaaaaaaaaabbbb',
      env_name: 'QWEN_API_KEY',
    });
    expect(result.data.api_key_ref).toBe('env:QWEN_API_KEY');
  });

  it('listTools / listSubagents / listSkills 返回空集合', async () => {
    const api = await freshSettingsApi();
    expect((await api.listTools()).data.tools).toEqual([]);
    expect((await api.listSubagents()).data.subagents).toEqual([]);
    const skills = await api.listSkills();
    expect(skills.data.skills).toEqual([]);
    expect(skills.data.prompt_chars).toBe(0);
  });

  it('testModel 直接返回成功提示', async () => {
    const api = await freshSettingsApi();
    const result = await api.testModel('mock');
    expect(result).toMatchObject({ ok: true, latency_ms: 1 });
    expect(result.message).toContain('mock');
  });
});

/* ------------------------------------------------------------------ */
/* 真实请求路径                                                        */
/* ------------------------------------------------------------------ */

describe('settingsApi（真实请求）', () => {
  it('health 走 /api/v1/health', async () => {
    const api = await freshSettingsApi();
    await api.health();
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/health');
    expect(init.method).toBe('GET');
  });

  it('updateSettings 以 PUT 提交 JSON patch', async () => {
    const api = await freshSettingsApi();
    await api.updateSettings({ mock_mode: false });
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/settings');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body as string)).toEqual({ mock_mode: false });
  });

  it('saveModelKey 走 PUT /models/{id}/key，id 做 URL 编码', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          trace_id: 't-1',
          provider: 'deepseek',
          api_key_ref: 'env:DEEPSEEK_API_KEY',
          configured: true,
          masked: 'sk-****abcd',
          persisted: true,
        }),
      ),
    );
    const api = await freshSettingsApi();
    const result = await api.saveModelKey('deep seek/id', {
      api_key: 'sk-secret-value-abcd',
      env_name: 'DEEPSEEK_API_KEY',
    });
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/models/deep%20seek%2Fid/key');
    expect(init.method).toBe('PUT');
    // 明文只在请求体出现；响应里必须是掩码
    expect(JSON.parse(init.body as string).api_key).toBe('sk-secret-value-abcd');
    expect(result.data.masked).toBe('sk-****abcd');
    expect(JSON.stringify(result.data)).not.toContain('sk-secret-value-abcd');
  });

  it('upsertModel 走 POST /models', async () => {
    const api = await freshSettingsApi();
    await api.upsertModel({ provider: 'deepseek', api_key_ref: 'env:DEEPSEEK_API_KEY' });
    const [url, init] = lastCall();
    expect(url).toBe('/api/v1/models');
    expect(init.method).toBe('POST');
  });

  it('listModels / listTools / listSubagents / listSkills 分别走各自端点', async () => {
    const api = await freshSettingsApi();
    await api.listModels();
    expect(lastCall()[0]).toBe('/api/v1/models');
    await api.listTools();
    expect(lastCall()[0]).toBe('/api/v1/tools');
    await api.listSubagents();
    expect(lastCall()[0]).toBe('/api/v1/subagents');
    await api.listSkills();
    expect(lastCall()[0]).toBe('/api/v1/skills');
  });

  it('testModel 成功时拼上后端返回的模型名', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          trace_id: 't',
          ok: true,
          latency_ms: 320,
          returned_model: 'deepseek-chat',
        }),
      ),
    );
    const api = await freshSettingsApi();
    const result = await api.testModel('deepseek');
    expect(result).toEqual({
      ok: true,
      message: '连接正常（deepseek-chat）',
      latency_ms: 320,
    });
  });

  it('testModel 失败时用后端 reason 作为提示', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, { trace_id: 't', ok: false, reason: 'API Key 无效', latency_ms: 10 }),
      ),
    );
    const api = await freshSettingsApi();
    expect(await api.testModel('deepseek')).toMatchObject({
      ok: false,
      message: 'API Key 无效',
    });
  });

  it('testModel 失败且无 reason 时兜底文案', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(200, { trace_id: 't', ok: false })),
    );
    const api = await freshSettingsApi();
    expect((await api.testModel('deepseek')).message).toBe('连接失败');
  });

  it('testModel 遇 404/405 标记 unavailable（后端版本较低）', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => jsonResponse(404, { trace_id: 't' })),
    );
    const api = await freshSettingsApi();
    expect(await api.testModel('deepseek')).toEqual({
      ok: false,
      unavailable: true,
      message: '当前后端版本较低，暂不支持测试连接',
    });
  });

  it('testModel 其它 ApiError 透出原始消息', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(500, { trace_id: 't', error: { code: 'E', message: '后端开小差了' } }),
      ),
    );
    const api = await freshSettingsApi();
    expect(await api.testModel('deepseek')).toMatchObject({
      ok: false,
      message: '后端开小差了',
    });
  });
});

describe('存储目录接口', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    state.mockMode = false;
  });

  it('setStoragePath 走 PUT /storage/paths，body 带 kind 与绝对路径', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          trace_id: 't1',
          kind: 'artifacts',
          ok: true,
          path: 'D:/产物',
          exists: true,
          files: 0,
          error: null,
        }),
      ),
    );
    const api = await freshSettingsApi();
    const response = await api.setStoragePath('artifacts', 'D:/产物');

    expect(response.data.ok).toBe(true);
    expect(response.data.path).toBe('D:/产物');
    const [url, init] = lastCall();
    expect(url).toContain('/storage/paths');
    expect(init.method).toBe('PUT');
    expect(JSON.parse(init.body ?? '{}')).toEqual({ kind: 'artifacts', path: 'D:/产物' });
  });

  it('browseDir 走 GET /storage/browse，路径要 encodeURIComponent', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          trace_id: 't3',
          path: 'C:/Users/我 的文档',
          parent: 'C:/Users',
          dirs: [{ name: '产物', path: 'C:/Users/我 的文档/产物' }],
          roots: [{ name: 'C:', path: 'C:/' }],
          error: null,
        }),
      ),
    );
    const api = await freshSettingsApi();
    const response = await api.browseDir('C:/Users/我 的文档');

    expect(response.data.dirs).toHaveLength(1);
    const [url, init] = lastCall();
    expect(url).toContain('/storage/browse?path=');
    expect(url).toContain(encodeURIComponent('C:/Users/我 的文档'));
    expect(init.method ?? 'GET').toBe('GET');
  });

  it('makeDir 走 POST /storage/browse/mkdir', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, { trace_id: 't4', ok: true, path: 'D:/新建', error: null }),
      ),
    );
    const api = await freshSettingsApi();
    const response = await api.makeDir('D:/', '新建');

    expect(response.data.ok).toBe(true);
    const [url, init] = lastCall();
    expect(url).toContain('/storage/browse/mkdir');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body ?? '{}')).toEqual({ path: 'D:/', name: '新建' });
  });

  it('传 null 表示恢复默认目录', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        jsonResponse(200, {
          trace_id: 't2',
          kind: 'uploads',
          ok: true,
          path: 'E:/repo/data/uploads',
          exists: true,
          files: 3,
          error: null,
        }),
      ),
    );
    const api = await freshSettingsApi();
    await api.setStoragePath('uploads', null);
    const [, init] = lastCall();
    expect(JSON.parse(init.body ?? '{}')).toEqual({ kind: 'uploads', path: null });
  });

  it('mock 模式下不真的发请求', async () => {
    state.mockMode = true;
    const spy = vi.fn();
    vi.stubGlobal('fetch', spy);
    const api = await freshSettingsApi();
    const response = await api.setStoragePath('artifacts', 'D:/随便');
    expect(response.data.ok).toBe(true);
    expect(spy).not.toHaveBeenCalled();
  });
});
