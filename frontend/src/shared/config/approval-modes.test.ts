import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  APPROVAL_MODES,
  APPROVAL_MODE_HINTS,
  APPROVAL_MODE_LABELS,
  APPROVAL_MODE_STORAGE_KEY,
  DEFAULT_APPROVAL_MODE,
  isApprovalMode,
  readApprovalMode,
  writeApprovalMode,
} from './approval-modes';

describe('approval-modes', () => {
  afterEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
  });

  it('三档都有标签与说明，默认是按需确认', () => {
    expect([...APPROVAL_MODES]).toEqual(['always_ask', 'risky', 'all_allow']);
    for (const mode of APPROVAL_MODES) {
      expect(APPROVAL_MODE_LABELS[mode]).toBeTruthy();
      expect(APPROVAL_MODE_HINTS[mode]).toBeTruthy();
    }
    expect(DEFAULT_APPROVAL_MODE).toBe('risky');
  });

  it('isApprovalMode 只认三档，拒绝大写与未知值', () => {
    expect(isApprovalMode('all_allow')).toBe(true);
    expect(isApprovalMode('ALL_ALLOW')).toBe(false);
    expect(isApprovalMode('allow')).toBe(false);
    expect(isApprovalMode(null)).toBe(false);
  });

  it('写入后能读回，脏数据回退默认档', () => {
    expect(readApprovalMode()).toBe(DEFAULT_APPROVAL_MODE);

    writeApprovalMode('all_allow');
    expect(window.localStorage.getItem(APPROVAL_MODE_STORAGE_KEY)).toBe('all_allow');
    expect(readApprovalMode()).toBe('all_allow');

    window.localStorage.setItem(APPROVAL_MODE_STORAGE_KEY, '随便写的');
    expect(readApprovalMode()).toBe(DEFAULT_APPROVAL_MODE);
  });

  it('localStorage 不可写时不抛错（隐私模式）', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('quota');
    });
    expect(() => writeApprovalMode('always_ask')).not.toThrow();
  });
});
