import { useCallback, useEffect, useState } from 'react';
import { errorMessage } from '../../../shared/lib/api';
import {
  canInstall,
  desktopDownloadUrl,
  detectPlatform,
  isStandalone,
  PLATFORM_LABEL,
  promptInstall,
  subscribeInstall,
} from '../../../shared/lib/desktop';
import { formatBytes, timeAgo } from '../../../shared/lib/format';
import { copyText } from '../../../shared/lib/share';
import {
  IconCopy,
  IconDownload,
  IconFolder,
  IconMonitor,
  IconPlay,
  IconRefresh,
} from '../../../shared/ui/Icons';
import { Button, Modal } from '../../../shared/ui/primitives';
import { useToast } from '../../../shared/ui/toast-context';
import { desktopPackageApi } from '../api/desktop-package';
import type { DesktopPackageOut, DesktopSavedOut } from '../api/desktop-package';

/**
 * 右栏底部的「桌面端」入口。
 *
 * 这是真的安装，不是演示：index.html 挂了 manifest、public/sw.js 注册了 Service Worker，
 * 浏览器判定这个站可安装之后才会抛 `beforeinstallprompt`，这时点「一键安装」
 * 走的就是浏览器原生安装流程——装完在开始菜单/启动台有图标，打开是独立窗口，
 * 不占浏览器标签，断网也能开外壳（SW 缓存）。
 *
 * 只在电脑上出现：这个产品要读写本机文件夹，手机/平板上的浏览器拿不到这些能力，
 * 硬给一份「添加到主屏幕」的步骤只会让人装上一个用不了的壳子，所以移动端整块不渲染。
 *
 * 三种落地方式，按浏览器能力自动选：
 *   1. 支持 `beforeinstallprompt` → 一键安装（Windows / macOS 的 Edge、Chrome）
 *   2. 已经以独立窗口打开 → 显示「桌面端已就绪」
 *   3. 不支持（Firefox、Safari 旧版本、部分内嵌浏览器）→ 给出电脑端手动添加的步骤
 * 部署时配了真实安装包地址（VITE_DESKTOP_DOWNLOAD_URL）就再补一个下载按钮。
 *
 * 第五十九轮补的那一段：下载完要能找回文件。浏览器自己的下载只把文件丢进「下载」目录、
 * 页面拿不到路径，所以改由本机后端落盘并记下绝对路径（见 backend/api/v1/desktop.py），
 * 这里把路径、复制、定位、重新安装都摆出来；路径失效时明确说清楚并给「重新下载」。
 */

/** 去掉尾部分隔符后取最后一段，用来在侧栏小字里说「存在哪个文件夹」。 */
function dirName(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  return (parts.length > 1 ? parts[parts.length - 2] : path) ?? path;
}

export function DesktopAppCard() {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [installable, setInstallable] = useState(() => canInstall());
  const [installed, setInstalled] = useState(() => isStandalone());
  const [pkg, setPkg] = useState<DesktopPackageOut | null>(null);
  const [busy, setBusy] = useState<'download' | 'reveal' | 'open' | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // 安装事件在模块层就监听好了，这里只跟着更新状态
    return subscribeInstall(() => {
      setInstallable(canInstall());
      setInstalled(isStandalone());
    });
  }, []);

  /** 读一次状态：进来时读一次，打开弹窗时再读一次（期间文件可能被删/被移走）。 */
  const refresh = useCallback(async () => {
    try {
      const { data } = await desktopPackageApi.status();
      setPkg(data);
    } catch {
      // 后端没这个接口（老版本）时静默降级成纯浏览器安装引导，不打扰用户
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const platform = detectPlatform();
  const packageUrl = desktopDownloadUrl();
  // 手机 / 平板没有本机文件夹可写，装上去也是个用不了的壳子——整块不渲染
  const isMobile = platform === 'ios' || platform === 'android';
  /** 装完之后去哪儿找图标：Windows 是开始菜单，macOS 是启动台 */
  const launchSpot =
    platform === 'macos' ? '启动台' : platform === 'linux' ? '应用菜单' : '开始菜单';
  const saved = pkg?.saved ?? null;
  /** 后端手里有安装包才走「存到本机」；没有就退回浏览器下载链接 */
  const canDeliver = pkg?.available ?? false;

  const install = async () => {
    const outcome = await promptInstall();
    if (outcome === 'accepted') {
      setInstallable(false);
      setInstalled(true);
      setOpen(false);
    }
  };

  /** 保存安装包到本机（后端复制并记下路径）；没后端能力时退回打开下载链接。 */
  const download = async () => {
    setError(null);
    if (!canDeliver) {
      if (packageUrl) window.open(packageUrl, '_blank', 'noopener,noreferrer');
      return;
    }
    setBusy('download');
    try {
      const { data } = await desktopPackageApi.download();
      if (data.ok && data.saved) {
        const record = data.saved;
        setPkg((prev) => ({
          available: true,
          filename: record.filename,
          size: record.size,
          platform: prev?.platform ?? platform,
          default_dir: prev?.default_dir ?? '',
          saved: record,
        }));
        toast.show('安装包已存到本机，路径记下来了', { tone: 'ok' });
      } else {
        // 没存成：后端也把旧记录清空了，界面同步成「没有」
        setPkg((prev) => (prev ? { ...prev, saved: null } : prev));
        setError(data.error ?? '没能保存到本机');
      }
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const reveal = async () => {
    setBusy('reveal');
    try {
      const { data } = await desktopPackageApi.reveal();
      if (!data.ok) {
        toast.show(data.error ?? '打不开文件管理器', { tone: 'warn' });
        // 文件被删掉时顺手刷新，界面立刻变成「不在了」的状态
        await refresh();
      }
    } catch (err) {
      toast.show(errorMessage(err), { tone: 'danger' });
    } finally {
      setBusy(null);
    }
  };

  const launchPackage = async () => {
    setBusy('open');
    try {
      const { data } = await desktopPackageApi.open();
      if (data.ok) {
        toast.show(installed ? '正在打开桌面端…' : '正在打开安装包…', { tone: 'ok' });
      } else {
        toast.show(data.error ?? '打不开这个文件', { tone: 'warn' });
        await refresh();
      }
    } catch (err) {
      toast.show(errorMessage(err), { tone: 'danger' });
    } finally {
      setBusy(null);
    }
  };

  const copyPath = async () => {
    if (!saved) return;
    const ok = await copyText(saved.path);
    toast.show(ok ? '路径已复制' : '复制失败，请手动选中路径', { tone: ok ? 'ok' : 'warn' });
  };

  if (isMobile) return null;

  /** 侧栏那行小字：把「文件在哪」直接摆出来，不用点开弹窗才知道。 */
  const subtitle = saved
    ? saved.exists
      ? `安装包在「${dirName(saved.path)}」文件夹`
      : '安装包已被移动或删除，点开可重新下载'
    : installed
      ? '当前就是独立窗口，可直接读写本地文件夹'
      : `装到本机，从${launchSpot}直接打开`;

  return (
    <>
      <section className="shrink-0 border-t border-line" aria-label="桌面端">
        <button
          type="button"
          onClick={() => {
            setOpen(true);
            void refresh();
          }}
          className="group flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-surface-hover"
        >
          <span className="grid h-6 w-6 shrink-0 place-items-center rounded-control bg-surface-sunken text-muted group-hover:bg-brand-soft group-hover:text-brand">
            <IconMonitor size={13} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-caption font-medium text-ink">
              {installed ? '桌面端已就绪' : '安装桌面端'}
            </span>
            <span className="block truncate text-[calc(11px*var(--font-scale))] text-faint">
              {subtitle}
            </span>
          </span>
          <IconDownload size={13} className="shrink-0 text-faint group-hover:text-ink" />
        </button>
      </section>

      {open ? (
        <Modal
          title={installed ? '桌面端已安装' : '安装 Office Agent 桌面版'}
          size="md"
          onClose={() => setOpen(false)}
          footer={
            <>
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                关闭
              </Button>
              {saved?.exists ? (
                <Button
                  variant="primary"
                  size="sm"
                  loading={busy === 'open'}
                  leading={<IconPlay size={12} />}
                  onClick={() => void launchPackage()}
                >
                  {installed ? '打开桌面端' : '打开安装包'}
                </Button>
              ) : null}
              {installable ? (
                <Button variant="primary" size="sm" onClick={() => void install()}>
                  一键安装
                </Button>
              ) : null}
              {!saved && (canDeliver || packageUrl) ? (
                <Button
                  variant="secondary"
                  size="sm"
                  loading={busy === 'download'}
                  leading={<IconDownload size={12} />}
                  onClick={() => void download()}
                >
                  下载 {PLATFORM_LABEL[platform]} 安装包
                </Button>
              ) : null}
            </>
          }
        >
          {installed ? (
            <p className="text-caption leading-relaxed text-ink-soft">
              你现在就在桌面端里运行，文件夹和窗口都归本机管。想再装一份到别的电脑，按下面的步骤来。
            </p>
          ) : installable ? (
            <p className="text-caption leading-relaxed text-ink-soft">
              这个浏览器可以直接安装：点「一键安装」走系统原生流程，装好后{launchSpot} /
              桌面上会有图标， 打开是独立窗口，不占浏览器标签；断网也能打开界面。
            </p>
          ) : (
            <p className="text-caption leading-relaxed text-ink-soft">
              当前浏览器没给出安装入口（Firefox、旧版 Safari 或应用内浏览器常见）， 换成 Chrome /
              Edge 打开就能直接装，或者照下面手动添加：
            </p>
          )}

          {saved ? <SavedPackageBlock saved={saved} /> : null}

          {saved ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Button
                size="sm"
                variant="secondary"
                leading={<IconCopy size={12} />}
                onClick={() => void copyPath()}
              >
                复制路径
              </Button>
              <Button
                size="sm"
                variant="secondary"
                loading={busy === 'reveal'}
                leading={<IconFolder size={12} />}
                onClick={() => void reveal()}
              >
                在文件管理器中打开
              </Button>
              {!saved.exists ? (
                <Button
                  size="sm"
                  variant="primary"
                  loading={busy === 'download'}
                  leading={<IconRefresh size={12} />}
                  onClick={() => void download()}
                >
                  重新下载
                </Button>
              ) : null}
            </div>
          ) : null}

          {error ? (
            <p
              className="mt-2 text-[calc(11px*var(--font-scale))] leading-relaxed text-danger"
              role="alert"
            >
              {error}
            </p>
          ) : null}

          <ul className="mt-3 space-y-2">
            <InstallStep
              title="Chrome / Edge（Windows、macOS）"
              body="地址栏右侧的「安装」图标，或菜单 →「安装应用 / 创建快捷方式」。"
            />
            <InstallStep
              title="Safari（macOS 14 及以上）"
              body="菜单栏「文件」→「添加到程序坞」。"
            />
          </ul>

          <p className="mt-3 text-[calc(11px*var(--font-scale))] leading-relaxed text-faint">
            桌面端与本机文件打交道：产物直接写进你选的目录，不上传云端。
          </p>
        </Modal>
      ) : null}
    </>
  );
}

/** 已保存的安装包：路径 + 状态。文件不在了要说清楚原因，别让人对着空路径发呆。 */
function SavedPackageBlock({ saved }: { saved: DesktopSavedOut }) {
  return (
    <section
      className={`mt-3 rounded-control border p-2.5 ${
        saved.exists ? 'border-line bg-surface-sunken/50' : 'border-warn-line bg-warn-soft/60'
      }`}
      aria-label="安装包位置"
    >
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-caption font-medium text-ink-soft">
          {saved.exists ? '安装包已存到本机' : '这个安装包已经不在了'}
        </span>
        <span className="shrink-0 text-[calc(11px*var(--font-scale))] text-faint">
          {formatBytes(saved.size)} · {timeAgo(saved.saved_at)}
        </span>
      </div>
      <code
        data-testid="desktop-package-path"
        title={saved.path}
        className="mt-1.5 block select-all break-all rounded-chip bg-surface px-2 py-1 font-mono text-[calc(11px*var(--font-scale))] leading-relaxed text-ink-soft"
      >
        {saved.path}
      </code>
      {saved.exists ? null : (
        <p className="mt-1.5 text-[calc(11px*var(--font-scale))] leading-relaxed text-warn">
          {saved.error ?? '文件可能被删除或移动了'}，重新下载一份就能继续用。
        </p>
      )}
    </section>
  );
}

function InstallStep({ title, body }: { title: string; body: string }) {
  return (
    <li className="rounded-control border border-line bg-surface-sunken/50 px-2.5 py-1.5">
      <div className="text-caption font-medium text-ink-soft">{title}</div>
      <div className="mt-0.5 text-caption leading-relaxed text-muted">{body}</div>
    </li>
  );
}
