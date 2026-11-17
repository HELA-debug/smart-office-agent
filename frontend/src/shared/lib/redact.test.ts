/**
 * 展示层脱敏单测。
 *
 * 后端已脱敏，这里是「最后一道兜底」：工具卡入参/出参会原样渲染到界面，
 * 一旦密钥或完整邮箱泄漏，属于安全事故，所以按模式逐条断言。
 */
import { describe, expect, it } from 'vitest';
import { redactValue } from './redact';

describe('redactValue 密钥字段', () => {
  it.each([
    'token',
    'api_key',
    'apiKey',
    'API-KEY',
    'secret',
    'client_secret',
    'password',
    'passwd',
    'authorization',
    'cookie',
    'session',
    'credential',
  ])('把 %s 字段整值打码', (key) => {
    expect(redactValue({ [key]: 'super-secret-value' })).toEqual({ [key]: '••••••' });
  });

  it('普通字段原样保留', () => {
    expect(redactValue({ filename: 'a.docx', size: 12 })).toEqual({
      filename: 'a.docx',
      size: 12,
    });
  });

  it('递归处理嵌套对象，只打码命中的那一层', () => {
    expect(redactValue({ outer: { api_key: 'k', inner: { token: 't', name: 'n' } } })).toEqual({
      outer: { api_key: '••••••', inner: { token: '••••••', name: 'n' } },
    });
  });

  it('数组逐元素递归', () => {
    expect(redactValue([{ token: 'a' }, { name: 'b' }, 'plain'])).toEqual([
      { token: '••••••' },
      { name: 'b' },
      'plain',
    ]);
  });
});

describe('redactValue 邮箱脱敏', () => {
  it('保留首字母与域名，中间打码', () => {
    expect(redactValue('zhangsan@example.com')).toBe('z***@example.com');
  });

  it('一段文本中的多个邮箱都被处理', () => {
    expect(redactValue('发给 a1@x.com 和 b2@y.org')).toBe('发给 a***@x.com 和 b***@y.org');
  });

  it('非邮箱文本原样返回', () => {
    expect(redactValue('这是一段普通中文')).toBe('这是一段普通中文');
    expect(redactValue('not-an-email')).toBe('not-an-email');
  });

  it('对象内的字符串值也会被脱敏', () => {
    expect(redactValue({ to: 'lisi@corp.cn' })).toEqual({ to: 'l***@corp.cn' });
  });
});

describe('redactValue 其他类型', () => {
  it('数字/布尔/null/undefined 原样返回', () => {
    expect(redactValue(42)).toBe(42);
    expect(redactValue(true)).toBe(true);
    expect(redactValue(null)).toBeNull();
    expect(redactValue(undefined)).toBeUndefined();
    expect(redactValue(0)).toBe(0);
  });
});
