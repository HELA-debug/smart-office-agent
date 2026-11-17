/** 设置表单纯逻辑（无 React 依赖，便于单测）。 */
import { friendlyEngineReason } from '../../shared/lib/engine-reason';
import type { SettingsOut } from '../../shared/api/types';

export interface FormState {
  engine: 'mock' | 'real' | 'deepagents';
  provider: string;
  modelName: string;
  mockMode: boolean;
  modelTimeout: string;
  approvalTimeout: string;
  approvalRules: string[];
  maxUploadMb: string;
  fallbackChain: string;
}

export function toSettingsForm(settings: SettingsOut): FormState {
  return {
    engine:
      settings.engine === 'mock' || settings.engine === 'real' || settings.engine === 'deepagents'
        ? settings.engine
        : 'real',
    provider: settings.model_provider,
    modelName: settings.model_name,
    mockMode: settings.mock_mode,
    modelTimeout: String(settings.model_timeout_seconds),
    approvalTimeout: String(settings.approval_timeout_seconds),
    approvalRules: [...settings.approval_rules],
    maxUploadMb: String(settings.max_upload_mb ?? 20),
    fallbackChain: [...(settings.fallback_chain ?? [])].join(','),
  };
}

/**
 * 引擎的中文名；和设置页下拉共用同一套说法，避免两处叫法不同。
 * 注意：这是前端自己的文案，后端 registry.engine_capabilities() 里的 name
 * 不会通过接口传过来；要改界面上的叫法，改这里（以及 SettingsPage 的下拉标签）。
 */
export const ENGINE_TEXT: Record<string, string> = {
  real: '真实模型',
  mock: '演示模式',
  deepagents: '规划模式',
};

/**
 * 改「执行引擎」必须同时改「演示模式」。
 *
 * 这两个控件是同一个开关的两种写法。以前各自独立保存，于是出现过
 * engine=real + mock_mode=true：设置页写着「真实模型」，实际一直在跑 mock，
 * 重启后也不会变——用户只能怀疑「你根本没调大模型」。
 */
export function applyEngineSwitch(form: FormState, engine: FormState['engine']): FormState {
  return { ...form, engine, mockMode: engine === 'mock' };
}

export function applyMockModeSwitch(form: FormState, mockMode: boolean): FormState {
  return { ...form, mockMode, engine: mockMode ? 'mock' : 'real' };
}

/**
 * 「执行引擎」下面那行说明：保存的值、实际生效的值、以及为什么不一样。
 *
 * 保存 ≠ 生效：没配 Key、探测失败时后端会兜底到演示模式。不写清楚，
 * 用户看到顶栏徽标写 mock 只会以为设置没保存成功。
 */
export function engineSwitchNote(input: {
  ready: boolean;
  saved: string | null;
  effective: string | null;
  reason?: string | null;
  formEngine: string | null;
}): string {
  if (!input.ready) return '';
  if (input.saved && input.formEngine && input.formEngine !== input.saved) {
    return '改动还没保存，保存后才会切换';
  }
  const effective = input.effective;
  if (!effective) return '';
  const label = ENGINE_TEXT[effective] ?? effective;
  if (input.saved && effective !== input.saved) {
    const reason = friendlyEngineReason(input.reason);
    return `当前实际生效：${label}${reason ? ` · 原因：${reason}` : ''}`;
  }
  return `当前实际生效：${label}`;
}

export function validateSettings(form: FormState): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!['mock', 'real', 'deepagents'].includes(form.engine)) errors.engine = '请选择有效引擎';
  if (!form.provider.trim()) errors.provider = '请选择模型供应商';
  if (!form.modelName.trim()) errors.modelName = '模型名不能为空';
  const modelTimeout = Number(form.modelTimeout);
  if (!Number.isFinite(modelTimeout) || modelTimeout <= 0 || modelTimeout > 300) {
    errors.modelTimeout = '超时需在 1–300 秒之间';
  }
  const approvalTimeout = Number(form.approvalTimeout);
  if (!Number.isFinite(approvalTimeout) || approvalTimeout < 10 || approvalTimeout > 3600) {
    errors.approvalTimeout = '审批超时需在 10–3600 秒之间';
  }
  if (form.approvalRules.length === 0) errors.approvalRules = '至少选择一个需要审批的工具';
  const maxUploadMb = Number(form.maxUploadMb);
  if (!Number.isFinite(maxUploadMb) || maxUploadMb < 1 || maxUploadMb > 200) {
    errors.maxUploadMb = '上传上限需在 1–200 MB 之间';
  }
  const chain = form.fallbackChain
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (chain.length > 8) errors.fallbackChain = '降级链最多 8 项';
  return errors;
}

/** 表单是否与后端配置一致（保存按钮可用性）。 */
export function isSettingsDirty(settings: SettingsOut, form: FormState): boolean {
  const base = toSettingsForm(settings);
  return (
    base.engine !== form.engine ||
    base.provider !== form.provider ||
    base.modelName !== form.modelName ||
    base.mockMode !== form.mockMode ||
    base.modelTimeout !== form.modelTimeout ||
    base.approvalTimeout !== form.approvalTimeout ||
    base.maxUploadMb !== form.maxUploadMb ||
    base.fallbackChain !== form.fallbackChain ||
    base.approvalRules.slice().sort().join(',') !== form.approvalRules.slice().sort().join(',')
  );
}
