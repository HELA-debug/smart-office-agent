/**
 * 右栏（RightPanel）单元测试。
 *
 * 守护的产品约束：
 * 1. 右栏是「产物仓库」：一行一个产物，可查看全部；
 * 2. 「本次素材」已撤掉（素材在输入框和对话里都看得见，这里再列一遍只是重复）；
 * 3. 「本次运行」的耗时/用量/花费、审批区都不在右栏（那是审计页和对话流的活儿）；
 * 4. 「审计用量」只给一个入口，无运行记录时禁用。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RightPanel } from './RightPanel';
import type { ArtifactItem } from '../state/workbench';

vi.mock('../../artifacts', () => ({
  ArtifactCard: ({ artifact }: { artifact: ArtifactItem }) => (
    <div data-testid="artifact-card">{artifact.filename}</div>
  ),
}));

function makeArtifact(overrides: Partial<ArtifactItem> = {}): ArtifactItem {
  return {
    artifact_id: 'ar_1',
    type: 'docx',
    filename: '本周周报.docx',
    size: 2048,
    download_url: '/api/v1/artifacts/ar_1/download',
    preview_url: '/api/v1/artifacts/ar_1/preview',
    created_at: '2026-10-24T10:00:00Z',
    meta_status: 'idle',
    meta_error: null,
    meta: null,
    ...overrides,
  };
}

function renderPanel(
  props: Partial<React.ComponentProps<typeof RightPanel>> = {},
): ReturnType<typeof render> {
  return render(
    <RightPanel
      artifacts={[]}
      canAudit={false}
      onOpenAudit={() => {}}
      onOpenAllArtifacts={() => {}}
      {...props}
    />,
  );
}

describe('RightPanel', () => {
  it('只渲染产物仓库一块，素材区与审批区都不在', () => {
    renderPanel();

    expect(screen.getByText('产物仓库')).toBeTruthy();
    expect(screen.queryByLabelText('本次素材')).toBeNull();
    expect(screen.queryByLabelText('本次运行')).toBeNull();
    expect(screen.queryByText('审批')).toBeNull();
    expect(screen.queryByText('当前无待审批动作')).toBeNull();
  });

  it('无产物时只留一行灰字，不再挂起步示例（示例属于输入框的活儿）', () => {
    renderPanel();
    const empty = screen.getByText(/这个会话还没有文件/);
    expect(empty.tagName).toBe('P');
    expect(empty.className).toContain('text-faint');
    expect(screen.queryByText(/border-dashed/)).toBeNull();
    expect(screen.queryByText('可以先让我做这些')).toBeNull();
    expect(screen.queryByRole('button', { name: /整理成 600 字周报/ })).toBeNull();
  });

  it('有产物时渲染卡片与计数徽标，并给「查看本会话全部产物」入口', () => {
    const onOpenAllArtifacts = vi.fn();
    renderPanel({ artifacts: [makeArtifact()], onOpenAllArtifacts });

    expect(screen.getByTestId('artifact-card')).toBeTruthy();
    expect(screen.getByText('1')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /查看本会话全部产物/ }));
    expect(onOpenAllArtifacts).toHaveBeenCalledTimes(1);
  });

  it('「查看本会话全部产物」的悬停提示走统一气泡（圆角），不用系统 title 方框', async () => {
    renderPanel({ artifacts: [makeArtifact()] });
    const button = screen.getByRole('button', { name: /查看本会话全部产物/ });
    // 原生 title 会蹦出方角白框，跟这一栏的圆角卡片不是一个体系
    expect(button.getAttribute('title')).toBeNull();

    fireEvent.mouseEnter(button.parentElement as HTMLElement);
    // 整行按钮的提示有 200ms 迟疑（鼠标划过时不至于一路弹气泡）
    const tip = await screen.findByRole('tooltip');
    expect(tip.className).toContain('rounded-full');
    expect(tip.textContent).toContain('定位到本会话');
  });

  it('可审计时点「审计用量」触发回调，无运行记录时禁用', () => {
    const onOpenAudit = vi.fn();
    const { unmount } = renderPanel({ canAudit: false, onOpenAudit });
    const disabledButton = screen.getByRole('button', { name: '打开审计用量' });
    expect((disabledButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(disabledButton);
    expect(onOpenAudit).not.toHaveBeenCalled();
    unmount();

    renderPanel({ canAudit: true, onOpenAudit });
    fireEvent.click(screen.getByRole('button', { name: '打开审计用量' }));
    expect(onOpenAudit).toHaveBeenCalledTimes(1);
  });
});
