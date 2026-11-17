/**
 * 左栏「最近会话」的交互约束：
 * 1. Ctrl+D 直接删（菜单里标了快捷键，按了就该立刻生效，不再插一道「删除？✓✕」）；
 * 2. 鼠标走 ⋮ →「删除」仍要确认（防误点）；
 * 3. ⋮ 菜单渲染到 body，不被列表容器裁切。
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SessionList } from './SessionList';
import type { SessionListProps } from './SessionList';
import type { ThreadSummary } from '../../../shared/types/api';

function session(patch: Partial<ThreadSummary> = {}): ThreadSummary {
  return {
    thread_id: 't1',
    title: '把这份材料整理成 600 字周报',
    created_at: '2026-10-25T08:00:00Z',
    updated_at: '2026-10-25T09:00:00Z',
    message_count: 3,
    artifact_count: 2,
    pinned: false,
    ...patch,
  };
}

function renderList(patch: Partial<SessionListProps> = {}) {
  const props: SessionListProps = {
    sessions: [session()],
    sessionsStatus: 'ready',
    sessionsError: null,
    activeThreadId: 't1',
    total: 1,
    page: 1,
    pageSize: 20,
    collapsed: false,
    onToggleCollapsed: vi.fn(),
    onNew: vi.fn(),
    onSelect: vi.fn(),
    onRetry: vi.fn(),
    onRename: vi.fn(),
    onTogglePin: vi.fn(),
    onDelete: vi.fn(),
    onPage: vi.fn(),
    onBulkDelete: vi.fn().mockResolvedValue(true),
    onLoadAllIds: vi.fn().mockResolvedValue(['t1']),
    onReorder: vi.fn(),
    ...patch,
  };
  const view = render(
    <MemoryRouter>
      <SessionList {...props} />
    </MemoryRouter>,
  );
  return { props, ...view };
}

describe('最近会话：快捷键与菜单', () => {
  it('Ctrl+D 直接删除，不再弹确认条', () => {
    const { props } = renderList();

    fireEvent.keyDown(window, { key: 'd', ctrlKey: true });

    expect(props.onDelete).toHaveBeenCalledWith('t1');
    expect(props.onDelete).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: '确认删除会话' })).toBeNull();
  });

  it('鼠标走菜单「删除」仍要确认一次（确认态只有 ✓ / ✕ 两个图标）', () => {
    const { props } = renderList();

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    fireEvent.click(screen.getByRole('menuitem', { name: /删除/ }));

    expect(props.onDelete).not.toHaveBeenCalled();
    // 不再有「删除？」红字：确认含义交给图标的 tooltip
    expect(screen.queryByText('删除？')).toBeNull();
    expect(screen.getByRole('button', { name: '确认删除会话' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '取消删除' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: '确认删除会话' }));
    expect(props.onDelete).toHaveBeenCalledWith('t1');
  });

  it('⋮ 菜单挂在 body 上，不被列表容器裁掉', () => {
    renderList();

    fireEvent.click(screen.getByRole('button', { name: '更多操作' }));
    const menu = screen.getByRole('menu', { name: '会话操作' });

    expect(menu.parentElement).toBe(document.body);
    expect(menu.className).toContain('fixed');
    // 四个动作都要在，缺一个就是又被裁了
    expect(screen.getByRole('menuitem', { name: /置顶/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /重命名/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /复制标题/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /删除/ })).toBeInTheDocument();
  });

  it('焦点在输入框里时不抢 Ctrl+D', () => {
    const { props } = renderList();
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();

    fireEvent.keyDown(input, { key: 'd', ctrlKey: true });

    expect(props.onDelete).not.toHaveBeenCalled();
    input.remove();
  });
});

describe('最近会话：批量清理', () => {
  const many = [
    session(),
    session({ thread_id: 't2', title: '第二份材料' }),
    session({ thread_id: 't3', title: '第三份材料' }),
  ];

  it('点「批量清理会话」进选择模式：整行变复选框，点行不切会话', () => {
    const { props } = renderList({ sessions: many, total: many.length });

    fireEvent.click(screen.getByRole('button', { name: '批量清理会话' }));

    const boxes = screen.getAllByRole('checkbox');
    expect(boxes).toHaveLength(3);
    expect(boxes.every((box) => box.getAttribute('aria-checked') === 'false')).toBe(true);

    const firstBox = boxes.at(0);
    if (!firstBox) throw new Error('没有渲染出会话复选框');
    fireEvent.click(firstBox);
    expect(firstBox.getAttribute('aria-checked')).toBe('true');
    // 选择模式下点行是「勾选」，不能顺手把会话切走
    expect(props.onSelect).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: /删除选中（1）/ })).toBeInTheDocument();
  });

  it('全选本页 → 第一次点只进确认态，第二次才真删，成功后退出选择模式', async () => {
    const onBulkDelete = vi.fn().mockResolvedValue(true);
    renderList({ sessions: many, total: many.length, onBulkDelete });

    fireEvent.click(screen.getByRole('button', { name: '批量清理会话' }));
    fireEvent.click(screen.getByRole('button', { name: '全选本页' }));
    expect(screen.getByRole('button', { name: /删除选中（3）/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /删除选中（3）/ }));
    expect(onBulkDelete).not.toHaveBeenCalled();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /确认删除 3 个/ }));
    });
    expect(onBulkDelete).toHaveBeenCalledWith(['t1', 't2', 't3']);
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '批量清理会话' })).toBeInTheDocument(),
    );
  });

  it('「选中全部 N 个」走跨页取 ID：分页只有一页 3 条也能选中全部 26 条', async () => {
    const onLoadAllIds = vi.fn().mockResolvedValue(['t1', 't2', 't3', 't9', 't10']);
    const onBulkDelete = vi.fn().mockResolvedValue(true);
    renderList({ sessions: many, total: 26, onLoadAllIds, onBulkDelete });

    fireEvent.click(screen.getByRole('button', { name: '批量清理会话' }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /选中全部 26 个/ }));
    });

    expect(onLoadAllIds).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /删除选中（5）/ }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /确认删除 5 个/ }));
    });
    expect(onBulkDelete).toHaveBeenCalledWith(['t1', 't2', 't3', 't9', 't10']);
  });

  it('没勾任何会话时删除按钮不可用；Esc 退出选择模式', () => {
    renderList({ sessions: many, total: many.length });

    fireEvent.click(screen.getByRole('button', { name: '批量清理会话' }));
    expect(screen.getByRole('button', { name: /删除选中（0）/ })).toBeDisabled();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0);
  });
});

/* 模板区已整体下线（改由输入框的空状态/技能入口承担），相关用例随之移除。 */

/* ------------------------------------------------------------------ */
/* 高度分配（第五十五轮）：会话列占满剩余空间                          */
/* ------------------------------------------------------------------ */

describe('左栏高度分配', () => {
  it('会话列是唯一的弹性块：flex-1 + 明确最小高度，列表自己滚', () => {
    renderList();
    const list = screen.getByTestId('session-list');
    expect(list).toHaveClass('overflow-y-auto');

    const column = list.parentElement as HTMLElement;
    // flex-1 吃掉项目区之上的所有剩余高度；min-h 保证窗口再矮也留得住几行
    expect(column).toHaveClass('flex-1');
    expect(column.className).toContain('min-h-[7rem]');
    // 项目区在它前面且不参与增长，所以「剩余空间」只会给会话列
    expect(screen.getByRole('navigation', { name: '功能导航' })).toBeInTheDocument();
  });

  it('导航行压到 32px：6 项省下的高度留给会话列表', () => {
    renderList();
    const nav = screen.getByRole('navigation', { name: '功能导航' });
    const first = nav.querySelector('a') as HTMLElement;
    expect(first).toHaveClass('h-8');
  });
});

/* ------------------------------------------------------------------ */
/* 收起态（第五十七轮）：会话条目不给窄条留任何痕迹                    */
/* ------------------------------------------------------------------ */

describe('左栏收起态', () => {
  it('收起时完全不渲染会话条目：没有列表、没有标题文本、没有滚动容器', () => {
    renderList({ collapsed: true });

    // 会话列整块不渲染：连滚动条都不会冒出来（截图里那条灰色竖条就是它）
    expect(screen.queryByTestId('session-list')).toBeNull();
    expect(screen.queryByText('把这份材料整理成 600 字周报')).toBeNull();
    // 收起态该有的还在：展开入口 + 导航图标（功能一个不少）
    expect(screen.getByRole('button', { name: '展开侧边栏' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '产物中心' })).toBeInTheDocument();
  });

  it('展开后会话列表照旧出现在列表区', () => {
    renderList();

    expect(screen.getByTestId('session-list')).toBeInTheDocument();
    expect(screen.getByText('把这份材料整理成 600 字周报')).toBeInTheDocument();
  });
});

/* ------------------------------------------------------------------ */
/* 拖动排序：拖动会话行换位置，顺序交给上层落库                        */
/* ------------------------------------------------------------------ */

describe('拖动排序', () => {
  const dataTransfer = () => ({
    setData: vi.fn(),
    getData: vi.fn(),
    effectAllowed: 'move',
    dropEffect: 'move',
  });

  it('把第一条拖到第二条后面，回传新顺序', () => {
    const { props } = renderList({
      sessions: [
        session({ thread_id: 'a' }),
        session({ thread_id: 'b' }),
        session({ thread_id: 'c' }),
      ],
    });
    const rows = screen.getByTestId('session-list').querySelectorAll('li');

    fireEvent.dragStart(rows.item(0), { dataTransfer: dataTransfer() });
    fireEvent.dragOver(rows.item(1), { dataTransfer: dataTransfer(), clientY: 0 });
    fireEvent.drop(rows.item(1), { dataTransfer: dataTransfer() });

    expect(props.onReorder).toHaveBeenCalledWith(['b', 'a', 'c']);
  });

  it('置顶的会话不参与拖动（拖了也会被排回顶部）', () => {
    const { props } = renderList({
      sessions: [session({ thread_id: 'p', pinned: true }), session({ thread_id: 'b' })],
    });
    const rows = screen.getByTestId('session-list').querySelectorAll('li');

    expect(rows.item(0)).toHaveAttribute('draggable', 'false');
    fireEvent.dragStart(rows.item(0), { dataTransfer: dataTransfer() });
    fireEvent.dragOver(rows.item(1), { dataTransfer: dataTransfer(), clientY: 0 });
    fireEvent.drop(rows.item(1), { dataTransfer: dataTransfer() });

    expect(props.onReorder).not.toHaveBeenCalled();
  });

  it('批量清理模式下整行是复选框，不再响应拖动', () => {
    renderList();
    fireEvent.click(screen.getByRole('button', { name: '批量清理会话' }));
    const row = screen.getByTestId('session-list').querySelector('li');
    expect(row).toHaveAttribute('draggable', 'false');
  });
});
