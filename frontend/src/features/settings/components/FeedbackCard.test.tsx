/**
 * 意见反馈卡片：不能让人点了「发送」却什么都没发生。
 * 这里锁三件事：空内容点不动、发送带上类型与内容、没配邮箱时给「复制内容」兜底。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { settingsApi } from '../api';
import { FeedbackCard } from './FeedbackCard';

const BASE_RESULT = {
  trace_id: 't',
  id: 'fb_1',
  kind: 'bug',
  saved: true,
  saved_path: 'data/feedback/feedback.jsonl',
  target: '',
  subject: '[Office Agent] 问题反馈',
  body: '类型：问题反馈\n\n导出后标题是空的',
  mailto: '',
  truncated: false,
};

beforeEach(() => {
  vi.spyOn(settingsApi, 'sendFeedback');
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('FeedbackCard', () => {
  it('没写字时发送是禁用的，也没法凭空提交', () => {
    render(<FeedbackCard />);
    const send = screen.getByRole('button', { name: '发送反馈' }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);

    fireEvent.click(send);
    expect(settingsApi.sendFeedback).not.toHaveBeenCalled();
  });

  it('发送时带上类型、内容与环境信息，并显示存档位置', async () => {
    vi.mocked(settingsApi.sendFeedback).mockResolvedValue({
      data: { ...BASE_RESULT },
      traceId: 't',
    });

    render(<FeedbackCard />);
    fireEvent.click(screen.getByRole('button', { name: '想要新功能' }));
    fireEvent.change(screen.getByLabelText('反馈内容'), {
      target: { value: '  希望周报能带上去周对比  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送反馈' }));

    await waitFor(() => expect(settingsApi.sendFeedback).toHaveBeenCalledTimes(1));
    const payload = vi.mocked(settingsApi.sendFeedback).mock.calls[0]?.[0];
    expect(payload?.kind).toBe('idea');
    // 首尾空格去掉再发，别把空行也一起发过去
    expect(payload?.message).toBe('希望周报能带上去周对比');
    expect(payload?.include_diagnostics).toBe(true);
    // 环境信息只给展示用的几项，不塞 UA / 文档内容
    expect(Object.keys(payload?.client ?? {})).toEqual(['window', 'platform', 'screen', 'theme']);

    await waitFor(() =>
      expect(screen.getByText(/已存到本机：data\/feedback\/feedback\.jsonl/)).toBeTruthy(),
    );
    // 邮箱没配：明确告诉用户「只在这台电脑上」，并给出复制入口
    expect(screen.getByRole('button', { name: '复制内容' })).toBeTruthy();
  });

  it('勾掉环境信息后不再附带', async () => {
    vi.mocked(settingsApi.sendFeedback).mockResolvedValue({
      data: { ...BASE_RESULT },
      traceId: 't',
    });

    render(<FeedbackCard />);
    fireEvent.change(screen.getByLabelText('反馈内容'), { target: { value: '随便说说' } });
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: '发送反馈' }));

    await waitFor(() => expect(settingsApi.sendFeedback).toHaveBeenCalledTimes(1));
    expect(vi.mocked(settingsApi.sendFeedback).mock.calls[0]?.[0].include_diagnostics).toBe(false);
  });

  it('配了开发者邮箱时给出收件人，并把标题+正文复制到剪贴板', async () => {
    vi.mocked(settingsApi.sendFeedback).mockResolvedValue({
      data: {
        ...BASE_RESULT,
        target: 'dev@example.com',
        mailto: 'mailto:dev@example.com?subject=x&body=y',
      },
      traceId: 't',
    });

    render(<FeedbackCard />);
    fireEvent.change(screen.getByLabelText('反馈内容'), { target: { value: '导出的标题空了' } });
    fireEvent.click(screen.getByRole('button', { name: '发送反馈' }));

    await waitFor(() => expect(screen.getByText(/收件人是 dev@example\.com/)).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '复制内容' }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledTimes(1));
    const copied = vi.mocked(navigator.clipboard.writeText).mock.calls[0]?.[0] ?? '';
    expect(copied).toContain('主题：[Office Agent] 问题反馈');
    expect(copied).toContain('导出后标题是空的');
  });

  it('后端报错时把原因显示出来，而不是静默失败', async () => {
    vi.mocked(settingsApi.sendFeedback).mockRejectedValue(new Error('后端未就绪'));

    render(<FeedbackCard />);
    fireEvent.change(screen.getByLabelText('反馈内容'), { target: { value: '测试' } });
    fireEvent.click(screen.getByRole('button', { name: '发送反馈' }));

    await waitFor(() => expect(screen.getByText(/后端未就绪/)).toBeTruthy());
  });
});
