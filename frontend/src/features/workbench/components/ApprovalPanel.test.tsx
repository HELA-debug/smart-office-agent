import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApprovalPanel } from './ApprovalPanel';
import type { ApprovalItem } from '../../../shared/types/view';

function makeApproval(patch: Partial<ApprovalItem> = {}): ApprovalItem {
  return {
    approval_id: 'ap1',
    run_id: 'r1',
    tool: 'doc.generate',
    risk: 'high',
    message: '要把这份合同发到 external@acme.com',
    preview: { to: 'external@acme.com', subject: '合同确认', impact: '发出后无法撤回' },
    created_at: '2026-11-08T06:00:00Z',
    decision: null,
    submitting: false,
    error: null,
    ...patch,
  };
}

describe('ApprovalPanel', () => {
  it('没有审批就整块不渲染（不占位、不留空壳）', () => {
    const { container } = render(<ApprovalPanel approvals={[]} onSubmit={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('待确认的卡片里能看清「要干什么、影响什么」，再给按钮', () => {
    render(<ApprovalPanel approvals={[makeApproval()]} onSubmit={vi.fn()} />);

    expect(screen.getByText('需要你确认')).toBeInTheDocument();
    expect(screen.getByText('高风险')).toBeInTheDocument();
    expect(screen.getByText('要把这份合同发到 external@acme.com')).toBeInTheDocument();
    // 预览字段翻成人话，不是把 to/subject 原样吐出来
    expect(screen.getByText('收件人')).toBeInTheDocument();
    expect(screen.getByText('external@acme.com')).toBeInTheDocument();
    expect(screen.getByText('影响范围')).toBeInTheDocument();
  });

  it('点允许 / 拒绝各自带回对应的决定', () => {
    const onSubmit = vi.fn();
    render(<ApprovalPanel approvals={[makeApproval()]} onSubmit={onSubmit} />);

    fireEvent.click(screen.getByRole('button', { name: /允许/ }));
    expect(onSubmit).toHaveBeenCalledWith('ap1', 'approved');

    fireEvent.click(screen.getByRole('button', { name: /拒绝/ }));
    expect(onSubmit).toHaveBeenCalledWith('ap1', 'rejected');
  });

  it('提交中按钮禁用，避免连点两次', () => {
    render(<ApprovalPanel approvals={[makeApproval({ submitting: true })]} onSubmit={vi.fn()} />);
    expect(screen.getByRole('button', { name: /允许/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /拒绝/ })).toBeDisabled();
  });

  it('处理过的审批收成一行，仍能看出允许还是拒绝', () => {
    render(
      <ApprovalPanel
        approvals={[makeApproval({ decision: 'approved', decided_at: '2026-11-08T06:01:00Z' })]}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText(/已允许/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /允许/ })).not.toBeInTheDocument();
  });
});
