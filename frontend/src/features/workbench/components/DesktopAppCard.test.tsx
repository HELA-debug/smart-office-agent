/**
 * 桌面端入口（DesktopAppCard）单元测试。
 *
 * 守护第五十九轮的产品约束——「下载完要能找回文件」：
 *   1. 从没下载过：不显示路径块，只有安装引导；
 *   2. 下载过且文件还在：完整路径 + 复制路径 + 在文件管理器中打开 + 打开安装包；
 *   3. 文件被删/被移走：明确说「不在了」，并给「重新下载」；
 *   4. 下载成功那一刻就把路径摆出来，不用刷新。
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { DesktopAppCard } from './DesktopAppCard';
import type { DesktopSavedOut } from '../api/desktop-package';

const statusMock = vi.fn();
const downloadMock = vi.fn();
const revealMock = vi.fn();
const openMock = vi.fn();

vi.mock('../api/desktop-package', () => ({
  desktopPackageApi: {
    status: (...args: unknown[]) => statusMock(...args),
    download: (...args: unknown[]) => downloadMock(...args),
    reveal: (...args: unknown[]) => revealMock(...args),
    open: (...args: unknown[]) => openMock(...args),
  },
}));

const SAVED: DesktopSavedOut = {
  path: 'C:\\Users\\demo\\Downloads\\Office Agent.exe',
  filename: 'Office Agent.exe',
  size: 38_398_060,
  saved_at: '2026-10-29T23:00:00+08:00',
  exists: true,
  dir_exists: true,
  error: null,
};

function statusResponse(saved: DesktopSavedOut | null) {
  return {
    data: {
      trace_id: 't',
      available: true,
      filename: 'Office Agent.exe',
      size: 38_398_060,
      platform: 'windows',
      default_dir: 'C:\\Users\\demo\\Downloads',
      saved,
    },
    traceId: 't',
  };
}

async function openDialog() {
  render(<DesktopAppCard />);
  fireEvent.click(await screen.findByRole('button', { name: /安装桌面端|桌面端已就绪/ }));
  return screen.findByRole('dialog');
}

describe('桌面端入口', () => {
  beforeEach(() => {
    statusMock.mockReset();
    downloadMock.mockReset();
    revealMock.mockReset();
    openMock.mockReset();
    statusMock.mockResolvedValue(statusResponse(null));
  });

  it('从没下载过时不显示路径块', async () => {
    await openDialog();

    expect(screen.queryByTestId('desktop-package-path')).toBeNull();
    expect(screen.queryByRole('button', { name: '复制路径' })).toBeNull();
    // 平台文案跟着 UA 走（jsdom 认不出系统），只断言「能下载」
    expect(screen.getByRole('button', { name: /下载.*安装包/ })).toBeInTheDocument();
  });

  it('下载成功后立刻展示完整保存路径', async () => {
    downloadMock.mockResolvedValue({
      data: { trace_id: 't', ok: true, path: SAVED.path, saved: SAVED, error: null },
      traceId: 't',
    });
    await openDialog();

    fireEvent.click(screen.getByRole('button', { name: /下载.*安装包/ }));

    expect(await screen.findByTestId('desktop-package-path')).toHaveTextContent(
      'C:\\Users\\demo\\Downloads\\Office Agent.exe',
    );
    expect(screen.getByText('安装包已存到本机')).toBeInTheDocument();
  });

  it('有记录时给出复制路径与在文件管理器中打开', async () => {
    statusMock.mockResolvedValue(statusResponse(SAVED));
    revealMock.mockResolvedValue({
      data: { trace_id: 't', ok: true, path: SAVED.path, exists: true, error: null },
      traceId: 't',
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    await openDialog();

    expect(await screen.findByTestId('desktop-package-path')).toHaveTextContent(SAVED.path);

    fireEvent.click(screen.getByRole('button', { name: '复制路径' }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(SAVED.path));

    fireEvent.click(screen.getByRole('button', { name: '在文件管理器中打开' }));
    await waitFor(() => expect(revealMock).toHaveBeenCalled());
  });

  it('路径失效时明确提示，并引导重新下载', async () => {
    const missing: DesktopSavedOut = {
      ...SAVED,
      exists: false,
      error: '文件已经不在这个位置了（可能被删除或移动）',
    };
    statusMock.mockResolvedValue(statusResponse(missing));
    downloadMock.mockResolvedValue({
      data: { trace_id: 't', ok: true, path: SAVED.path, saved: SAVED, error: null },
      traceId: 't',
    });

    const dialog = await openDialog();

    expect(await screen.findByText('这个安装包已经不在了')).toBeInTheDocument();
    expect(screen.getByText(/可能被删除或移动/)).toBeInTheDocument();
    // 路径仍然显示：用户要知道「原来在哪」，才可能自己去翻
    expect(screen.getByTestId('desktop-package-path')).toHaveTextContent(SAVED.path);
    expect(within(dialog).queryByRole('button', { name: '打开安装包' })).toBeNull();

    // 侧栏那行小字里也有「重新下载」，只在弹窗里点
    fireEvent.click(within(dialog).getByRole('button', { name: /重新下载/ }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalled());
    expect(await screen.findByText('安装包已存到本机')).toBeInTheDocument();
  });

  it('文件还在时可以从原入口重新打开安装包', async () => {
    statusMock.mockResolvedValue(statusResponse(SAVED));
    openMock.mockResolvedValue({
      data: { trace_id: 't', ok: true, path: SAVED.path, exists: true, error: null },
      traceId: 't',
    });

    await openDialog();
    fireEvent.click(await screen.findByRole('button', { name: '打开安装包' }));

    await waitFor(() => expect(openMock).toHaveBeenCalled());
  });

  it('保存失败时给出原因，且不留下假路径', async () => {
    downloadMock.mockResolvedValue({
      data: { trace_id: 't', ok: false, path: null, saved: null, error: '这个目录没有写入权限' },
      traceId: 't',
    });
    await openDialog();

    fireEvent.click(screen.getByRole('button', { name: /下载.*安装包/ }));

    expect(await screen.findByRole('alert')).toHaveTextContent('这个目录没有写入权限');
    expect(screen.queryByTestId('desktop-package-path')).toBeNull();
  });
});
