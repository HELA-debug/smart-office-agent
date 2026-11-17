/**
 * 目录选择器：设置页不该再让用户手打绝对路径。
 * 这里锁住三件事：进来先列子目录、能一层层点进去、点「就选这个文件夹」把路径交回去。
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DirPickerModal } from './DirPickerModal';

const browseDir = vi.fn();
const makeDir = vi.fn();

vi.mock('../api', () => ({
  settingsApi: {
    browseDir: (...args: unknown[]) => browseDir(...args),
    makeDir: (...args: unknown[]) => makeDir(...args),
  },
}));

beforeEach(() => {
  browseDir.mockReset();
  makeDir.mockReset();
  browseDir.mockImplementation(async (path: string | null) => ({
    data: {
      path: path ?? 'C:/Users/demo',
      parent: 'C:/Users',
      dirs:
        path === 'C:/Users/demo/Documents'
          ? [{ name: '周报', path: 'C:/Users/demo/Documents/周报' }]
          : [{ name: 'Documents', path: 'C:/Users/demo/Documents' }],
      roots: [{ name: 'C:', path: 'C:/' }],
      error: null,
    },
    traceId: 't',
  }));
});

function renderPicker(onPick = vi.fn()) {
  render(
    <DirPickerModal
      title="选择上传目录"
      initialPath="C:/Users/demo"
      onClose={() => undefined}
      onPick={onPick}
    />,
  );
  return onPick;
}

describe('DirPickerModal', () => {
  it('打开就列当前目录的子文件夹，并显示当前路径', async () => {
    renderPicker();

    expect(await screen.findByText('Documents')).toBeInTheDocument();
    expect(browseDir).toHaveBeenCalledWith('C:/Users/demo');
    expect(screen.getAllByText('C:/Users/demo').length).toBeGreaterThan(0);
  });

  it('点文件夹进入下一层', async () => {
    renderPicker();

    fireEvent.click(await screen.findByText('Documents'));

    await waitFor(() => expect(browseDir).toHaveBeenLastCalledWith('C:/Users/demo/Documents'));
    expect(await screen.findByText('周报')).toBeInTheDocument();
  });

  it('选中当前目录时把路径交回调用方', async () => {
    const onPick = renderPicker();
    await screen.findByText('Documents');

    fireEvent.click(screen.getByRole('button', { name: '就选这个文件夹' }));

    expect(onPick).toHaveBeenCalledWith('C:/Users/demo');
  });

  it('可以就地新建文件夹，建完直接跳进去', async () => {
    makeDir.mockResolvedValue({
      data: { ok: true, path: 'C:/Users/demo/新产物', error: null },
      traceId: 't',
    });
    renderPicker();
    await screen.findByText('Documents');

    fireEvent.click(screen.getByRole('button', { name: /新建文件夹/ }));
    fireEvent.change(screen.getByLabelText('新文件夹名称'), { target: { value: '新产物' } });
    fireEvent.click(screen.getByRole('button', { name: '创建' }));

    await waitFor(() => expect(makeDir).toHaveBeenCalledWith('C:/Users/demo', '新产物'));
    await waitFor(() => expect(browseDir).toHaveBeenLastCalledWith('C:/Users/demo/新产物'));
  });

  it('目录读不了时给出提示，而不是白屏', async () => {
    browseDir.mockResolvedValue({
      data: {
        path: 'C:/Windows/System32',
        parent: null,
        dirs: [],
        roots: [],
        error: '这个文件夹打不开',
      },
      traceId: 't',
    });
    renderPicker();

    expect(await screen.findByText('这个文件夹打不开')).toBeInTheDocument();
  });
});
