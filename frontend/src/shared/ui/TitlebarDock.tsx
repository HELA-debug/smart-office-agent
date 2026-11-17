import { useEffect } from 'react';
import { applyTitlebarInset } from '../lib/titlebar';

/**
 * 桌面端窗口标题栏的「让位」层（见 shared/lib/titlebar.ts 的说明）。
 *
 * 只做两件事：
 *   1. 量出标题栏高度写进 `--titlebar-h`，各页面外壳据此下移；
 *   2. 在顶部留一条透明拖拽区——原生标题栏没了，不补这条窗口就拖不动。
 *
 * 网页态（未安装）高度是 0，这条层不占位、不挡点击。
 */
export function TitlebarDock() {
  useEffect(() => applyTitlebarInset(), []);
  return <div className="titlebar-drag-band" data-testid="titlebar-drag-band" aria-hidden="true" />;
}
