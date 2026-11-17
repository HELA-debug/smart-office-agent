import { useCallback, useEffect, useMemo, useState } from 'react';
import { providerLabel } from '../../shared/config/providers';
import { errorMessage } from '../../shared/lib/api';
import {
  FONT_FAMILIES,
  FONT_SCALE_DEFAULT,
  FONT_SCALE_MAX,
  FONT_SCALE_MIN,
  UI_SCALE_DEFAULT,
  UI_SCALE_MAX,
  UI_SCALE_MIN,
  WEIGHT_DEFAULT,
  WEIGHT_MAX,
  WEIGHT_MIN,
  resetAppearance,
  setFontFamily,
  setFontScale,
  setFontWeight,
  setTheme,
  setUiScale,
  useFontFamily,
  useFontScale,
  useFontWeight,
  useTheme,
  useUiScale,
} from '../../shared/lib/theme';
import {
  THINKING_VIEW_OPTIONS,
  setThinkingView,
  useThinkingView,
} from '../../shared/lib/thinking-pref';
import {
  IconCheck,
  IconFolder,
  IconInfo,
  IconMoon,
  IconRefresh,
  IconSparkle,
  IconSun,
} from '../../shared/ui/Icons';
import { PageShell } from '../../shared/ui/PageShell';
import { Badge, Button, Card, CardError, CardLoading } from '../../shared/ui/primitives';
import { Select } from '../../shared/ui/Select';
import { settingsApi } from './api';
import { DirPickerModal } from './components/DirPickerModal';
import { EndpointModal } from './components/EndpointModal';
import { KeyRefModal } from './components/KeyRefModal';
import { ModelListCard } from './components/ModelListCard';
import {
  ScaleSlider,
  SettingRow,
  SettingSection,
  ThemeSwitch,
  Toggle,
} from './components/SettingRows';
import {
  applyEngineSwitch,
  applyMockModeSwitch,
  engineSwitchNote,
  isSettingsDirty,
  toSettingsForm,
  validateSettings,
} from './form';
import { maskedKey } from './keys';
import type { ModelOut, SettingsOut, StorageKind, StoragePathsOut } from './api';
import type { FormState } from './form';
import type { HealthOut, SettingsUpdateIn } from '../../shared/api/types';

type SectionKey = 'model' | 'approval' | 'appearance' | 'data' | 'about';

const SECTIONS: {
  group: string;
  items: { key: SectionKey; label: string; icon: typeof IconSparkle }[];
}[] = [
  {
    group: '功能',
    items: [{ key: 'model', label: '模型与运行', icon: IconSparkle }],
  },
  {
    group: '偏好',
    items: [{ key: 'appearance', label: '外观', icon: IconSun }],
  },
  {
    group: '数据与安全',
    items: [
      { key: 'data', label: '数据与路径', icon: IconFolder },
      { key: 'about', label: '关于', icon: IconInfo },
    ],
  },
];

const ENGINE_OPTIONS = [
  { value: 'real', label: '真实模型' },
  { value: 'mock', label: '演示模式（不联网）' },
  { value: 'deepagents', label: '规划模式（实验中）' },
];

const textInput =
  'h-8 w-full rounded-control border border-line bg-surface px-2.5 text-mini text-ink placeholder:text-faint focus:border-brand focus:outline-none';

/** 设置中心：模型与运行、外观、数据路径、关于。 */
export function SettingsPage() {
  const [settings, setSettings] = useState<SettingsOut | null>(null);
  const [models, setModels] = useState<ModelOut[]>([]);
  const [health, setHealth] = useState<HealthOut | null>(null);
  const [form, setForm] = useState<FormState | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [keyModalProvider, setKeyModalProvider] = useState<ModelOut | null>(null);
  const [keySaving, setKeySaving] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [keyNotice, setKeyNotice] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState<string | null>(null);
  // 接口地址是模型能否使用的另一半（WorkBuddy 没有公共默认地址）
  const [endpointModel, setEndpointModel] = useState<ModelOut | null>(null);
  const [endpointSaving, setEndpointSaving] = useState(false);
  const [endpointError, setEndpointError] = useState<string | null>(null);
  const [section, setSection] = useState<SectionKey>('model');
  const [storage, setStorage] = useState<StoragePathsOut | null>(null);
  const [revealing, setRevealing] = useState<StorageKind | null>(null);
  const [storageNotice, setStorageNotice] = useState<string | null>(null);
  // 目录可改：pickingDir 指向正在用选择器换位置的目录
  const [pickingDir, setPickingDir] = useState<StorageKind | null>(null);
  const [savingDir, setSavingDir] = useState(false);
  const theme = useTheme();
  const uiScale = useUiScale();
  const fontScale = useFontScale();
  const fontWeight = useFontWeight();
  const fontFamily = useFontFamily();
  const thinkingView = useThinkingView();

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    const [settingsResult, modelsResult, healthResult, storageResult] = await Promise.allSettled([
      settingsApi.getSettings(),
      settingsApi.listModels(),
      settingsApi.health(),
      settingsApi.getStoragePaths(),
    ]);
    if (settingsResult.status === 'rejected') {
      setLoadError(errorMessage(settingsResult.reason));
      setLoading(false);
      return;
    }
    setSettings(settingsResult.value.data);
    setForm(toSettingsForm(settingsResult.value.data));
    setModels(modelsResult.status === 'fulfilled' ? modelsResult.value.data.models : []);
    setHealth(healthResult.status === 'fulfilled' ? healthResult.value.data : null);
    setStorage(storageResult.status === 'fulfilled' ? storageResult.value.data : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(
    () => (settings && form ? isSettingsDirty(settings, form) : false),
    [form, settings],
  );

  // 保存的值 ≠ 实际生效的值：没配 Key、探测失败时后端会兜底到演示模式。
  // 这行说明就是为了让两处（这里和顶栏徽标）不再各说各话。
  const savedEngine = settings?.engine ?? null;
  const effectiveEngine = health?.engine_effective ?? null;
  const engineMismatch = Boolean(effectiveEngine && savedEngine && effectiveEngine !== savedEngine);
  const engineNote = engineSwitchNote({
    ready: Boolean(health),
    saved: savedEngine,
    effective: effectiveEngine,
    reason: health?.engine_reason ?? '',
    formEngine: form?.engine ?? null,
  });

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => {
      if (!current) return current;
      // 「执行引擎」和「演示模式」是同一个开关：改一个必须带上另一个，
      // 否则保存后 DB 里会留下 engine=real + mock_mode=true 这种矛盾组合。
      if (key === 'engine') return applyEngineSwitch(current, value as FormState['engine']);
      if (key === 'mockMode') return applyMockModeSwitch(current, Boolean(value));
      return { ...current, [key]: value };
    });
    setSaveError(null);
    setSavedAt(null);
  };

  /** 打开存储目录：后端会真的唤起系统文件管理器，失败时把原因显式告诉用户。 */
  const revealDir = async (kind: StorageKind) => {
    setRevealing(kind);
    setStorageNotice(null);
    try {
      const response = await settingsApi.revealStorage(kind);
      if (response.data.opened) {
        setStorageNotice(`已在文件管理器中打开：${response.data.path}`);
        setStorage((current) =>
          current
            ? { ...current, [kind]: { ...current[kind], path: response.data.path } }
            : current,
        );
      } else {
        setStorageNotice(
          `打开失败：${response.data.error ?? '未知原因'}（路径：${response.data.path}）`,
        );
      }
    } catch (error) {
      setStorageNotice(`打开目录失败：${errorMessage(error)}`);
    } finally {
      setRevealing(null);
    }
  };

  /** 保存新的存储目录：改完只影响之后写入的文件，已有文件不动。 */
  const saveDir = async (kind: StorageKind, next: string | null) => {
    setSavingDir(true);
    setStorageNotice(null);
    try {
      const response = await settingsApi.setStoragePath(kind, next || null);
      if (!response.data.ok) {
        setStorageNotice(`目录修改失败：${response.data.error ?? '未知原因'}`);
        return;
      }
      setStorage((current) =>
        current
          ? {
              ...current,
              [kind]: {
                path: response.data.path,
                exists: response.data.exists ?? true,
                files: response.data.files ?? 0,
              },
            }
          : current,
      );
      setPickingDir(null);
      setStorageNotice(
        `已保存目录：${response.data.path}（之后生成的文件会存到这里，已有文件不移动）`,
      );
    } catch (error) {
      setStorageNotice(`目录修改失败：${errorMessage(error)}`);
    } finally {
      setSavingDir(false);
    }
  };

  const save = async () => {
    if (!form) return;
    const errors = validateSettings(form);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;
    setSaving(true);
    setSaveError(null);
    setSavedAt(null);
    const patch: SettingsUpdateIn = {
      engine: form.engine,
      model_provider: form.provider,
      model_name: form.modelName,
      mock_mode: form.mockMode,
      model_timeout_seconds: Number(form.modelTimeout),
      approval_timeout_seconds: Number(form.approvalTimeout),
      approval_rules: form.approvalRules,
      max_upload_mb: Number(form.maxUploadMb),
      fallback_chain: form.fallbackChain
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
    };
    try {
      const response = await settingsApi.updateSettings(patch);
      setSettings(response.data);
      setForm(toSettingsForm(response.data));
      setSavedAt(new Date().toLocaleTimeString('zh-CN', { hour12: false }));
    } catch (error) {
      setSaveError(errorMessage(error));
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async (model: ModelOut) => {
    setTesting(model.id);
    const result = await settingsApi.testModel(model.id);
    setTestResult((current) => ({
      ...current,
      [model.id]: `${result.ok ? '✓ ' : result.unavailable ? 'ⓘ ' : '✗ '}${result.message}${
        result.latency_ms != null ? `（${result.latency_ms}ms）` : ''
      }`,
    }));
    setTesting(null);
    // 探测通过说明这套配置此刻真能用：顺手把 /health 的降级结论刷新掉。
    // 否则「测试连接」显示正常、上面那行却还写着「API Key 无效或已失效」，
    // 用户只会以为新 Key 又白换了（换 Key 后最常撞到的就是这个）。
    if (result.ok) {
      const [healthResult, modelsResult] = await Promise.allSettled([
        settingsApi.health(),
        settingsApi.listModels(),
      ]);
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value.data);
      if (modelsResult.status === 'fulfilled') setModels(modelsResult.value.data.models);
    }
  };

  /** 保存从供应商开放平台获取的 Key：落本地 .env，接口只回掩码。 */
  const saveKey = async (model: ModelOut, apiKey: string, envName: string) => {
    setKeySaving(true);
    setKeyError(null);
    try {
      await settingsApi.saveModelKey(model.id, { api_key: apiKey, env_name: envName });
      const [modelsResult, healthResult] = await Promise.allSettled([
        settingsApi.listModels(),
        settingsApi.health(),
      ]);
      if (modelsResult.status === 'fulfilled') setModels(modelsResult.value.data.models);
      // 后端保存 Key 时会把「上次探测失败」的降级结论作废，这里同步刷一次，
      // 免得上面那行还写着旧 Key 的「API Key 无效或已失效」。
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value.data);
      setKeyModalProvider(null);
      setKeyNotice(
        `已保存 ${providerLabel(model.provider)} Key（${maskedKey(apiKey)}），点「测试连接」确认一次就能用了`,
      );
    } catch (error) {
      setKeyError(errorMessage(error));
    } finally {
      setKeySaving(false);
    }
  };

  /**
   * 断开这家的 Key：进程 env、Settings、本地 .env 三处同清。
   * 项目要分享 / 部署给别人前用它止损——Key 留在 .env 里会跟着数据目录一起被拷走。
   */
  const disconnectKey = async (model: ModelOut) => {
    const label = providerLabel(model.provider);
    const active = (settings?.model_provider ?? '') === model.provider;
    if (
      !window.confirm(
        `断开 ${label} 的 Key？\n\n断开后本机（含 .env 文件）不再保存这把 Key，${label} 的模型立即不可用${
          active ? '，当前会话也将无法发送新任务' : ''
        }。接口地址与模型名会保留，重新粘贴 Key 即可再接上。`,
      )
    ) {
      return;
    }
    setDisconnecting(model.id);
    setKeyNotice(null);
    try {
      const response = await settingsApi.removeModelKey(model.id);
      const [modelsResult, healthResult, settingsResult] = await Promise.allSettled([
        settingsApi.listModels(),
        settingsApi.health(),
        settingsApi.getSettings(),
      ]);
      if (modelsResult.status === 'fulfilled') setModels(modelsResult.value.data.models);
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value.data);
      if (settingsResult.status === 'fulfilled') {
        setSettings(settingsResult.value.data);
        setForm(toSettingsForm(settingsResult.value.data));
      }
      setKeyNotice(
        response.data.persisted
          ? `已断开 ${label} 的 Key（本机 .env 已清除）`
          : `已断开 ${label} 的 Key，但 .env 删行失败：请手动打开 .env 删掉对应那一行，否则 Key 仍会随文件分发`,
      );
    } catch (error) {
      setKeyNotice(`断开失败：${errorMessage(error)}`);
    } finally {
      setDisconnecting(null);
    }
  };

  /**
   * 保存接口地址与模型名（只登记地址，不碰 Key）。
   * 存完立刻重拉列表：同一行的「已配置 / 未配置」与接口地址要马上跟着变。
   */
  const saveEndpoint = async (model: ModelOut, baseUrl: string, modelName: string) => {
    setEndpointSaving(true);
    setEndpointError(null);
    try {
      // 带上已登记的 id：改模型名时也更新同一条记录，而不是又建一条新的
      const registeredId =
        typeof model.extra?.registered_id === 'string' ? model.extra.registered_id : model.id;
      await settingsApi.upsertModel({
        id: registeredId,
        provider: model.provider,
        model: modelName || model.model,
        api_key_ref: model.api_key_ref,
        base_url: baseUrl,
      });
      const response = await settingsApi.listModels();
      setModels(response.data.models);
      setEndpointModel(null);
      setKeyNotice(`已保存 ${providerLabel(model.provider)} 的接口地址，先点「测试连接」验证一下`);
    } catch (error) {
      setEndpointError(errorMessage(error));
    } finally {
      setEndpointSaving(false);
    }
  };

  const providerOptions = [
    ...new Set([...models.map((model) => model.provider), form?.provider ?? 'mock']),
  ].map((provider) => ({ value: provider, label: providerLabel(provider) }));

  const statusBanner = (() => {
    if (saveError) {
      return (
        <div className="rounded-control border border-danger-line bg-danger-soft px-3 py-2 text-caption text-danger">
          {saveError}
        </div>
      );
    }
    if (savedAt) {
      return (
        <div className="rounded-control border border-ok-line bg-ok-soft px-3 py-2 text-caption text-ok">
          设置已保存并生效（{savedAt}）。新运行将使用最新配置。
        </div>
      );
    }
    if (dirty) {
      return (
        <div className="rounded-control border border-brand-line bg-brand-soft px-3 py-2 text-caption text-brand-strong">
          有未保存的修改：点右上角「保存设置」后生效。
        </div>
      );
    }
    return null;
  })();

  /** 一行存储目录：点路径直接在资源管理器里打开，右侧按钮开目录选择器，不用手打路径。 */
  const renderDirRow = (kind: StorageKind, title: string, description: string, current: string) => (
    <SettingRow title={title} description={description} stacked>
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => void revealDir(kind)}
          title="在资源管理器中打开这个文件夹"
          className="group flex min-w-0 flex-1 items-center gap-1.5 rounded-chip bg-surface-soft px-2 py-1 text-left transition-colors hover:bg-surface-hover"
        >
          <IconFolder size={12} className="shrink-0 text-muted group-hover:text-brand" />
          <span className="min-w-0 truncate font-mono text-mini text-ink-soft">{current}</span>
          <span className="ml-auto shrink-0 text-caption text-faint group-hover:text-brand">
            {revealing === kind ? '打开中…' : '打开文件夹'}
          </span>
        </button>
        <Button
          variant="secondary"
          size="sm"
          loading={savingDir && pickingDir === kind}
          onClick={() => setPickingDir(kind)}
          leading={<IconFolder size={13} />}
        >
          更改位置
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void saveDir(kind, null)}>
          恢复默认
        </Button>
      </div>
    </SettingRow>
  );

  return (
    <PageShell
      title="设置"
      description="模型与外观；保存后立即生效。"
      actions={
        <>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void load()}
            leading={<IconRefresh size={13} />}
          >
            刷新
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={() => void save()}
            disabled={!form || saving}
            loading={saving}
            leading={!saving ? <IconCheck size={13} /> : undefined}
          >
            保存设置
          </Button>
        </>
      }
    >
      {loading ? (
        <Card>
          <CardLoading label="正在读取设置…" rows={4} />
        </Card>
      ) : loadError ? (
        <Card>
          <CardError message={loadError} onRetry={() => void load()} />
        </Card>
      ) : !form ? null : (
        <div className="grid gap-6 lg:grid-cols-[12.5rem_minmax(0,1fr)]">
          {/* 左侧分区导航（桌面）；窄屏退化为一行可横滑的 pill */}
          <nav
            aria-label="设置分区"
            className="flex snap-x gap-1 overflow-x-auto pb-1 lg:sticky lg:top-0 lg:block lg:h-fit lg:space-y-4 lg:overflow-visible lg:pb-0"
          >
            {SECTIONS.map((group) => (
              <div key={group.group} className="contents lg:block lg:space-y-0.5">
                <div className="hidden px-3 pt-1 pb-1 text-caption font-semibold tracking-wide text-faint lg:block">
                  {group.group}
                </div>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = section === item.key;
                  return (
                    <button
                      key={item.key}
                      type="button"
                      aria-current={active ? 'page' : undefined}
                      onClick={() => setSection(item.key)}
                      className={`flex shrink-0 snap-start items-center gap-2 rounded-full px-3 py-2 text-regular transition-colors ${
                        active
                          ? 'bg-brand-soft font-medium text-brand-strong'
                          : 'text-muted hover:bg-surface-hover hover:text-ink'
                      }`}
                    >
                      <Icon size={15} />
                      {item.label}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="min-w-0 space-y-4">
            {statusBanner}

            {section === 'model' ? (
              <>
                <SettingSection
                  title="模型与运行"
                  description="决定下一次运行用哪个引擎与模型。"
                  action={
                    <Badge tone={form.mockMode ? 'warn' : 'ok'}>
                      {form.mockMode ? '演示模式' : '真实模型'}
                    </Badge>
                  }
                >
                  <SettingRow
                    title="执行引擎"
                    description="「真实」用你配置的模型；「演示」不联网，用预置数据跑一遍流程"
                    error={fieldErrors.engine}
                  >
                    <div className="w-full">
                      <Select
                        value={form.engine}
                        options={ENGINE_OPTIONS}
                        onChange={(next) => update('engine', next as FormState['engine'])}
                        ariaLabel="执行引擎"
                        className="w-full"
                      />
                      {/* 保存 ≠ 生效：没 Key、探测失败时后端会兜底到 mock。
                          不把这件事写在这儿，用户只能从顶栏徽标反推，还以为设置没生效。 */}
                      {engineNote ? (
                        <p
                          className={`mt-1 text-caption ${engineMismatch ? 'text-warn' : 'text-faint'}`}
                        >
                          {engineNote}
                        </p>
                      ) : null}
                    </div>
                  </SettingRow>

                  <SettingRow
                    title="模型供应商"
                    description="列出自带与已登记的供应商，未配置 Key 的会标出来"
                    error={fieldErrors.provider}
                  >
                    <Select
                      value={form.provider}
                      options={providerOptions}
                      onChange={(next) => update('provider', next)}
                      ariaLabel="模型供应商"
                      className="w-full"
                    />
                  </SettingRow>

                  <SettingRow
                    title="模型名"
                    description="供应商侧的模型标识，例如 deepseek-chat"
                    error={fieldErrors.modelName}
                  >
                    <input
                      value={form.modelName}
                      onChange={(event) => update('modelName', event.target.value)}
                      aria-label="模型名"
                      className={textInput}
                    />
                  </SettingRow>

                  <SettingRow
                    title="模型超时"
                    description="单次模型请求的等待上限（秒）"
                    error={fieldErrors.modelTimeout}
                  >
                    <div className="flex items-center gap-1.5">
                      <input
                        value={form.modelTimeout}
                        onChange={(event) => update('modelTimeout', event.target.value)}
                        aria-label="模型超时"
                        inputMode="decimal"
                        className={`${textInput} w-20 text-right`}
                      />
                      <span className="text-caption text-faint">秒</span>
                    </div>
                  </SettingRow>

                  <SettingRow
                    title="上传上限"
                    description="单个素材文件的大小上限"
                    error={fieldErrors.maxUploadMb}
                  >
                    <div className="flex items-center gap-1.5">
                      <input
                        value={form.maxUploadMb}
                        onChange={(event) => update('maxUploadMb', event.target.value)}
                        aria-label="上传上限"
                        inputMode="numeric"
                        className={`${textInput} w-20 text-right`}
                      />
                      <span className="text-caption text-faint">MB</span>
                    </div>
                  </SettingRow>

                  <SettingRow
                    title="模型降级链"
                    description="按优先级排列，用逗号分隔；前一个不可用时顺延"
                    error={fieldErrors.fallbackChain}
                    stacked
                  >
                    <input
                      value={form.fallbackChain}
                      onChange={(event) => update('fallbackChain', event.target.value)}
                      aria-label="模型降级链"
                      className={`${textInput} font-mono`}
                    />
                  </SettingRow>

                  <SettingRow
                    title="演示模式"
                    description="不调用真实模型，全程本地演示，不会产生任何费用"
                  >
                    <Toggle
                      checked={form.mockMode}
                      onChange={(next) => update('mockMode', next)}
                      label="演示模式"
                    />
                  </SettingRow>
                </SettingSection>

                <ModelListCard
                  models={models}
                  activeProvider={settings?.model_provider ?? null}
                  testing={testing}
                  testResult={testResult}
                  keyNotice={keyNotice}
                  onTest={(model) => void testConnection(model)}
                  onAddKey={setKeyModalProvider}
                  onDisconnect={(model) => void disconnectKey(model)}
                  disconnecting={disconnecting}
                  onEditEndpoint={(model) => {
                    setEndpointError(null);
                    setEndpointModel(model);
                  }}
                />

                <SettingSection title="安全提示">
                  <ul className="space-y-1.5 px-5 py-3.5 text-caption leading-relaxed text-muted">
                    <li>· 页面不会显示完整的 API Key，只告诉你「已配置 / 未配置」。</li>
                    <li>
                      · Key
                      只保存在这台电脑的服务配置里；测试连通性时不经过浏览器，页面也读不到密钥。
                    </li>
                    <li>· 保存后立即作用于下一次运行。</li>
                  </ul>
                </SettingSection>
              </>
            ) : null}

            {section === 'appearance' ? (
              <SettingSection title="外观" description="只影响这台电脑上的当前浏览器。">
                <SettingRow
                  title="思考过程"
                  description="选择想看到多少过程细节：完全显示会摊开决策行、计划与每一步工具调用；只看主要步骤留决策行和计划主线；不显示则对话里只剩回复和产物"
                  controlWidth="w-[13rem]"
                >
                  <Select
                    value={thinkingView}
                    options={THINKING_VIEW_OPTIONS.map((item) => ({
                      value: item.value,
                      label: item.label,
                      note: item.value === thinkingView ? '当前' : undefined,
                    }))}
                    onChange={(next) => setThinkingView(next)}
                    ariaLabel="思考过程显示"
                    className="w-full"
                    hint={THINKING_VIEW_OPTIONS.find((item) => item.value === thinkingView)?.note}
                  />
                </SettingRow>
                <SettingRow
                  title="主题"
                  description="默认深色（长时间盯屏更省眼），浅色适合投屏演示；改过之后按本地记忆走"
                >
                  <ThemeSwitch
                    value={theme}
                    onChange={(next) => setTheme(next)}
                    lightIcon={<IconSun size={13} />}
                    darkIcon={<IconMoon size={13} />}
                  />
                </SettingRow>

                <SettingRow
                  title="界面缩放"
                  description={`只放大/缩小间距、控件与栏宽，字号不变，当前 ${uiScale}%。想连字一起放大请用下一行的「字体大小」，两个互不影响`}
                  controlWidth="w-[16rem]"
                >
                  <ScaleSlider
                    value={uiScale}
                    min={UI_SCALE_MIN}
                    max={UI_SCALE_MAX}
                    step={1}
                    onChange={setUiScale}
                    label="界面缩放"
                    valueText={`${uiScale}%`}
                    ticks={[
                      { label: '紧凑', value: UI_SCALE_MIN },
                      { label: '默认', value: UI_SCALE_DEFAULT },
                      { label: '宽松', value: UI_SCALE_MAX },
                    ]}
                  />
                </SettingRow>

                <SettingRow
                  title="字体大小"
                  description={`只缩放文字，行高跟着按比例变，间距与控件尺寸不动，当前 ${fontScale}%。100% 是默认观感，130% 适合高分屏或投屏`}
                  controlWidth="w-[16rem]"
                >
                  <ScaleSlider
                    value={fontScale}
                    min={FONT_SCALE_MIN}
                    max={FONT_SCALE_MAX}
                    step={5}
                    onChange={setFontScale}
                    label="字体大小"
                    valueText={`${fontScale}%`}
                    ticks={[
                      { label: '小', value: FONT_SCALE_MIN },
                      { label: '默认', value: FONT_SCALE_DEFAULT },
                      { label: '大', value: FONT_SCALE_MAX },
                    ]}
                  />
                </SettingRow>

                <SettingRow
                  title="字体粗细"
                  description={`正文字重，当前 ${fontWeight}：调细看长文更清爽，调粗在投屏时更清楚；标题与按钮始终比正文重一档`}
                  controlWidth="w-[16rem]"
                >
                  <ScaleSlider
                    value={fontWeight}
                    min={WEIGHT_MIN}
                    max={WEIGHT_MAX}
                    step={50}
                    onChange={setFontWeight}
                    label="字体粗细"
                    valueText={
                      fontWeight <= 350
                        ? '细'
                        : fontWeight >= 550
                          ? '粗'
                          : fontWeight >= 450
                            ? '偏粗'
                            : '常规'
                    }
                    ticks={[
                      { label: '细', value: WEIGHT_MIN },
                      { label: '常规', value: WEIGHT_DEFAULT },
                      { label: '粗', value: WEIGHT_MAX },
                    ]}
                  />
                </SettingRow>

                <SettingRow
                  title="字体样式"
                  description="换一套字形：宋体适合长文，楷体、行楷偏手写感。系统里没装该字体会自动回退，不会变成乱码"
                  controlWidth="w-[15rem]"
                >
                  <Select
                    value={fontFamily}
                    options={FONT_FAMILIES.map((item) => ({
                      value: item.key,
                      // 选项按各自的字族渲染：不用选完才知道「行楷」长什么样
                      label: (
                        <span style={{ fontFamily: item.stack ?? undefined }}>{item.label}</span>
                      ),
                      note: item.key === fontFamily ? '当前' : undefined,
                    }))}
                    onChange={setFontFamily}
                    ariaLabel="字体样式"
                    className="w-full"
                    hint="只改这台电脑上的显示效果，不会影响导出文件里的字体"
                  />
                </SettingRow>

                <SettingRow
                  title="恢复默认外观"
                  description="主题、界面缩放、字体大小、字体粗细、字体样式、思考过程显示一并回到初始值"
                >
                  <Button variant="secondary" size="sm" onClick={resetAppearance}>
                    恢复默认
                  </Button>
                </SettingRow>
              </SettingSection>
            ) : null}

            {section === 'data' ? (
              <SettingSection
                title="数据与路径"
                description="全部落在本机文件系统；清理由你自行处理，界面不会自动删文件。"
              >
                {storageNotice ? (
                  <div className="border-b border-line px-4 py-2 text-caption text-muted">
                    {storageNotice}
                  </div>
                ) : null}
                {renderDirRow(
                  'uploads',
                  '上传目录',
                  '你拖进来的 PDF / Word / 表格，原件会先存到这个文件夹；想直接看原件或清理磁盘就点路径打开。存不下时可以改到 D 盘。',
                  storage?.uploads.path ?? settings?.upload_dir ?? '—',
                )}
                {renderDirRow(
                  'artifacts',
                  '产物目录',
                  'Agent 生成的 Word / PDF / 表格都写到这里；「产物 → 打开文件夹」打开的也是它。',
                  storage?.artifacts.path ?? settings?.artifact_dir ?? '—',
                )}
                <SettingRow title="运行环境" description="启动时的环境标识与日志级别">
                  <span className="font-mono text-caption text-ink-soft">
                    {settings?.environment ?? '—'} · {settings?.log_level ?? '—'}
                  </span>
                </SettingRow>
              </SettingSection>
            ) : null}

            {section === 'about' ? (
              <>
                <SettingSection title="关于" description="本机部署信息与引擎实际生效状态。">
                  <SettingRow title="版本" description="当前安装的版本与提交">
                    <span className="font-mono text-caption text-ink-soft">
                      {/* 打包版读不到 sha 时只显示版本号，别留一个孤零零的分隔点 */}
                      {health
                        ? [health.version, health.git_sha.slice(0, 7)].filter(Boolean).join(' · ')
                        : '—'}
                    </span>
                  </SettingRow>
                  <SettingRow title="引擎" description="配置值 / 实际生效值">
                    <span className="flex items-center gap-1.5 text-caption">
                      <span className="rounded-chip border border-line bg-surface-soft px-1.5 py-[1px] font-mono text-ink-soft">
                        {health?.engine ?? '—'}
                      </span>
                      <span className="text-faint">→</span>
                      <span
                        className={`rounded-chip border px-1.5 py-[1px] font-mono ${
                          health && health.engine_effective === health.engine
                            ? 'border-ok-line bg-ok-soft text-ok'
                            : 'border-warn-line bg-warn-soft text-warn'
                        }`}
                      >
                        {health?.engine_effective ?? '—'}
                      </span>
                    </span>
                  </SettingRow>
                  <SettingRow title="运行模式" description="当前供应商与模型">
                    <span className="truncate text-caption text-ink-soft">
                      {health ? `${health.mode} · ${health.provider}/${health.model}` : '—'}
                    </span>
                  </SettingRow>
                  <SettingRow title="能力" description="已注册的工具与子智能体数量">
                    <span className="text-caption text-ink-soft">
                      {health ? `${health.tools} 个工具 · ${health.subagents} 个子智能体` : '—'}
                    </span>
                  </SettingRow>
                </SettingSection>

                {/* 意见反馈卡片暂时下线（第六十一轮）：入口在这里，卡片见
                    components/FeedbackCard.tsx，功能与测试都还在，需要时把上面这行
                    的 import 与 <FeedbackCard /> 加回来即可。 */}
              </>
            ) : null}
          </div>
        </div>
      )}

      {keyModalProvider ? (
        <KeyRefModal
          model={keyModalProvider}
          saving={keySaving}
          error={keyError}
          onClose={() => {
            setKeyModalProvider(null);
            setKeyError(null);
          }}
          onSave={(apiKey, envName) => void saveKey(keyModalProvider, apiKey, envName)}
        />
      ) : null}

      {endpointModel ? (
        <EndpointModal
          model={endpointModel}
          saving={endpointSaving}
          error={endpointError}
          onClose={() => {
            setEndpointModel(null);
            setEndpointError(null);
          }}
          onSave={(baseUrl, modelName) => void saveEndpoint(endpointModel, baseUrl, modelName)}
        />
      ) : null}

      {pickingDir ? (
        <DirPickerModal
          title={pickingDir === 'uploads' ? '选择上传目录' : '选择产物目录'}
          initialPath={storage?.[pickingDir].path ?? ''}
          onClose={() => setPickingDir(null)}
          onPick={(path) => void saveDir(pickingDir, path)}
        />
      ) : null}
    </PageShell>
  );
}
