import { describe, expect, it } from 'vitest';
import {
  applyEngineSwitch,
  applyMockModeSwitch,
  engineSwitchNote,
  validateSettings,
  toSettingsForm,
} from './form';
import type { FormState } from './form';

const base: FormState = {
  engine: 'real',
  provider: 'deepseek',
  modelName: 'deepseek-chat',
  mockMode: true,
  modelTimeout: '20',
  approvalTimeout: '180',
  approvalRules: ['doc.generate_report', 'file.delete'],
  maxUploadMb: '20',
  fallbackChain: 'deepseek,qwen,glm,mock',
};

describe('settings form', () => {
  it('合法表单无错误', () => {
    expect(validateSettings(base)).toEqual({});
  });

  it('非法 engine 给出字段错误', () => {
    const errors = validateSettings({ ...base, engine: 'unknown' as FormState['engine'] });
    expect(errors.engine).toBeTruthy();
  });

  it('超时/审批工具/上传上限非法时给出字段错误', () => {
    const errors = validateSettings({
      ...base,
      modelTimeout: '0',
      approvalTimeout: '5',
      approvalRules: [],
      maxUploadMb: '0',
    });
    expect(errors.modelTimeout).toBeTruthy();
    expect(errors.approvalTimeout).toBeTruthy();
    expect(errors.approvalRules).toBeTruthy();
    expect(errors.maxUploadMb).toBeTruthy();
  });

  it('toForm 把后端配置转成表单值', () => {
    const form = toSettingsForm({
      trace_id: 't',
      engine: 'real',
      approval_rules: ['doc.generate_report', 'file.delete'],
      mock_mode: false,
      model_provider: 'glm',
      model_name: 'glm-4',
      model_timeout_seconds: 30,
      approval_timeout_seconds: 120,
      fallback_chain: [],
      database_url: '',
      upload_dir: '',
      artifact_dir: '',
      max_upload_mb: 20,
      feature_flags: {},
      sources: {},
      env_hints: {},
      secrets: {},
      log_level: 'INFO',
      environment: 'test',
    });
    expect(form).toMatchObject({
      engine: 'real',
      provider: 'glm',
      modelName: 'glm-4',
      mockMode: false,
      modelTimeout: '30',
      approvalTimeout: '120',
    });
    expect(form.approvalRules).toEqual(['doc.generate_report', 'file.delete']);
  });
});

describe('执行引擎与演示模式是同一个开关', () => {
  const base = toSettingsForm({
    trace_id: 't',
    engine: 'real',
    approval_rules: [],
    mock_mode: false,
    model_provider: 'deepseek',
    model_name: 'deepseek-flash',
    model_timeout_seconds: 60,
    approval_timeout_seconds: 180,
    fallback_chain: [],
    database_url: '',
    upload_dir: '',
    artifact_dir: '',
    max_upload_mb: 20,
    feature_flags: {},
    sources: {},
    env_hints: {},
    secrets: {},
    log_level: 'INFO',
    environment: 'test',
  });

  it('选「演示模式」时把 mock 开关一起打开', () => {
    const next = applyEngineSwitch(base, 'mock');
    expect(next.engine).toBe('mock');
    expect(next.mockMode).toBe(true);
  });

  it('选「真实模型」时把 mock 开关关掉（否则重启后永远生效不了）', () => {
    const next = applyEngineSwitch({ ...base, engine: 'mock', mockMode: true }, 'real');
    expect(next.engine).toBe('real');
    expect(next.mockMode).toBe(false);
  });

  it('反过来拨演示开关也会改引擎', () => {
    expect(applyMockModeSwitch(base, true)).toMatchObject({ engine: 'mock', mockMode: true });
    expect(applyMockModeSwitch({ ...base, engine: 'mock' }, false)).toMatchObject({
      engine: 'real',
      mockMode: false,
    });
  });

  it('保存值和实际生效值不一样时，说明里带上原因', () => {
    const note = engineSwitchNote({
      ready: true,
      saved: 'real',
      effective: 'mock',
      reason: 'MOCK_MODE=true 还开着',
      formEngine: 'real',
    });
    expect(note).toContain('当前实际生效：演示模式');
    expect(note).toContain('MOCK_MODE=true');
  });

  it('还没保存时只提示「保存后才会切换」，不吓人', () => {
    const note = engineSwitchNote({
      ready: true,
      saved: 'mock',
      effective: 'mock',
      reason: '',
      formEngine: 'real',
    });
    expect(note).toBe('改动还没保存，保存后才会切换');
  });

  it('一致时只写一句生效值，不啰嗦', () => {
    expect(
      engineSwitchNote({
        ready: true,
        saved: 'real',
        effective: 'real',
        reason: '',
        formEngine: 'real',
      }),
    ).toBe('当前实际生效：真实模型');
  });
});
