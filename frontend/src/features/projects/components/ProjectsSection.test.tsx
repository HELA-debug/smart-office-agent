/**
 * 左栏「项目」区：文件数、失效目录提示、点选与添加入口。
 *
 * 这一块最容易出的回归是「点一下没反应」或「目录被删掉后整栏报错」，
 * 所以测试只锁这两条主路径 + 空状态提示。
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProjectsSection } from './ProjectsSection';
import type { ProjectSummary } from '../types';

const base: ProjectSummary = {
  id: 'p1',
  name: '合同库',
  path: 'D:/合同库',
  created_at: '2026-10-20T09:00:00Z',
  pinned: false,
  file_count: 12,
  missing: false,
  modified_at: '2026-10-24T09:00:00Z',
};

function renderSection(overrides: Partial<ProjectSummary>[] = []) {
  const projects = overrides.length > 0 ? (overrides as ProjectSummary[]) : [base];
  const onSelect = vi.fn();
  const onAdd = vi.fn(async () => null);
  render(
    <ProjectsSection
      projects={projects}
      status="ready"
      error={null}
      activeId={null}
      onSelect={onSelect}
      onOpenPage={vi.fn()}
      onAdd={onAdd}
      onRemove={vi.fn(async () => true)}
      onRename={vi.fn(async () => true)}
      onReveal={vi.fn(async () => ({ opened: true, error: null }))}
      onNotice={vi.fn()}
    />,
  );
  return { onSelect, onAdd };
}

describe('ProjectsSection', () => {
  it('显示项目名与文档数，点击后选中', () => {
    const { onSelect } = renderSection();
    expect(screen.getByText('合同库')).toBeInTheDocument();
    expect(screen.getByText('12 个文档')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /合同库/ }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'p1' }));
  });

  it('目录被移走时给出明确提示', () => {
    renderSection([{ ...base, missing: true, file_count: 0 }]);
    expect(screen.getByText('文件夹不在了')).toBeInTheDocument();
  });

  it('没有项目时给「添加文档文件夹」入口', () => {
    render(
      <ProjectsSection
        projects={[]}
        status="ready"
        error={null}
        activeId={null}
        onSelect={vi.fn()}
        onOpenPage={vi.fn()}
        onAdd={vi.fn(async () => null)}
        onRemove={vi.fn(async () => true)}
        onRename={vi.fn(async () => true)}
        onReveal={vi.fn(async () => ({ opened: true, error: null }))}
        onNotice={vi.fn()}
      />,
    );
    expect(screen.getByText('添加文档文件夹')).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* 折叠与高度分配（第五十五轮）                                        */
/* ------------------------------------------------------------------ */

describe('ProjectsSection 折叠', () => {
  const setHeight = (px: number) => {
    Object.defineProperty(window, 'innerHeight', { value: px, configurable: true, writable: true });
    fireEvent(window, new Event('resize'));
  };

  beforeEach(() => {
    window.localStorage.clear();
    setHeight(800);
  });

  afterEach(() => {
    window.localStorage.clear();
    setHeight(800);
  });

  it('窗口够高时默认展开，列表自己撑上限、内部滚动（项目再多也不裁）', () => {
    renderSection();
    expect(screen.getByRole('button', { name: /^项目\d*$/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
    expect(screen.getByRole('button', { name: /合同库/ })).toBeInTheDocument();

    const body = document.getElementById('rail-projects-body');
    expect(body).not.toHaveAttribute('aria-hidden');
    // 上限跟着窗口走，且 overflow-y-auto：行多了滚动，不会被裁掉
    const scroller = screen.getByText('合同库').closest('.overflow-y-auto');
    expect(scroller).not.toBeNull();
    expect(scroller?.className).toContain('max-h-[min(9.5rem,24vh)]');
  });

  it('窗口变矮自动收起：内容不可达，但「添加项目」还在标题行', () => {
    renderSection();
    setHeight(600);

    const toggle = screen.getByRole('button', { name: /^项目\d*$/ });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(document.getElementById('rail-projects-body')).toHaveAttribute('aria-hidden', 'true');
    // 折叠后项目行退出无障碍树，Tab 也进不去
    expect(screen.queryByRole('button', { name: /合同库/ })).toBeNull();
    // 功能不丢：添加入口常驻标题行
    expect(screen.getByRole('button', { name: '添加项目' })).toBeVisible();
  });

  it('手动点标题行可以收起 / 展开，并记住偏好', () => {
    renderSection();
    const toggle = screen.getByRole('button', { name: /^项目\d*$/ });

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(window.localStorage.getItem('oa:rail-projects-open')).toBe('0');

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    expect(window.localStorage.getItem('oa:rail-projects-open')).toBe('1');
  });

  it('用户展开过就听用户的：窗口变矮也不自动收起', () => {
    renderSection();
    fireEvent.click(screen.getByRole('button', { name: /^项目\d*$/ })); // 收起
    fireEvent.click(screen.getByRole('button', { name: /^项目\d*$/ })); // 再展开 = 明确表态
    setHeight(560);
    expect(screen.getByRole('button', { name: /^项目\d*$/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    );
  });
});
