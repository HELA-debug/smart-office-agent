import { useCallback, useEffect, useState } from 'react';
import { onBackendStatus, probeBackend } from '../lib/backend-status';
import { IconAlertTriangle, IconSpinner } from './Icons';

/**
 * 本机服务断开时的提示条（状态来源见 shared/lib/backend-status.ts）。
 *
 * 为什么需要它：桌面图标只是个浏览器窗口，黑窗口一关或电脑重启过，服务就没了。
 * 这时界面还能显示已经加载的内容，点任何按钮却只会弹一个「无法连接后端」，
 * 看起来像 bug。与其让用户猜，不如直接把「服务没在跑、去双击启动器」说出来。
 *
 * 只挡顶部一小条、不盖住内容：用户可能正看着上次的结果，不该被全屏遮罩打断。
 */
export function ServiceDownBanner() {
  const [offline, setOffline] = useState(false);
  const [checking, setChecking] = useState(false);

  useEffect(() => onBackendStatus((status) => setOffline(status === 'offline')), []);

  const retry = useCallback(async () => {
    setChecking(true);
    const alive = await probeBackend();
    setChecking(false);
    if (alive) setOffline(false);
  }, []);

  if (!offline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="service-down-banner"
      className="rise-in fixed left-1/2 z-40 w-[min(560px,calc(100vw-32px))] -translate-x-1/2 rounded-card border border-warn-line bg-warn-soft px-3.5 py-3 text-ink shadow-pop"
      style={{ top: 'calc(var(--titlebar-h, 0px) + 12px)' }}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-[1px] shrink-0 text-warn">
          <IconAlertTriangle size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-body font-medium">本机服务已断开，这个窗口暂时用不了</p>
          <p className="mt-1 text-caption leading-relaxed text-ink-soft">
            桌面图标只是个窗口，真正干活的服务要在后台跑。双击项目文件夹里的
            <span className="mx-1 whitespace-nowrap rounded-chip bg-surface-soft px-1 py-[1px] font-mono text-[calc(11px*var(--font-scale))] text-ink">
              启动 Office Agent.cmd
            </span>
            ，等窗口里出现「启动完成，可以用了」，再点右边重试。
          </p>
        </div>
        <button
          type="button"
          onClick={() => void retry()}
          disabled={checking}
          className="inline-flex shrink-0 items-center gap-1 rounded-full border border-warn-line bg-surface px-2.5 py-1 text-caption text-ink transition-colors hover:border-warn disabled:opacity-60"
        >
          {checking ? <IconSpinner size={12} /> : null}
          重试
        </button>
      </div>
    </div>
  );
}
