import { ToastProvider } from '../shared/ui/Toast';
import { ErrorBoundary } from './error-boundary';
import type { ReactNode } from 'react';

/**
 * 全局 provider 组合点。
 * 目前是错误边界 + 轻提示宿主；后续新增主题/鉴权/查询缓存时都在这里挂载，App 不改。
 */
export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ErrorBoundary>
      <ToastProvider>{children}</ToastProvider>
    </ErrorBoundary>
  );
}
