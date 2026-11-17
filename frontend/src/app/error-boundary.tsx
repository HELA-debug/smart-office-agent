import { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 顶层错误边界：渲染异常时给出可恢复页面，而不是整页空白。
 * 只捕获渲染/生命周期错误；事件回调与异步请求错误仍由各 feature 的 error 态处理。
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 统一出口，便于后续接 Sentry / 本地日志
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  private handleReload = (): void => {
    window.location.reload();
  };

  render(): ReactNode {
    if (!this.state.error) return this.props.children;

    return (
      <div className="flex min-h-dvh items-center justify-center bg-canvas p-6">
        <div className="w-full max-w-[520px] rounded-card border border-line bg-surface p-8 text-center shadow-card">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-danger-soft text-danger">
            !
          </div>
          <h1 className="mt-4 text-title font-semibold text-ink">页面渲染出错</h1>
          <p className="mt-2 text-mini text-muted">
            已捕获异常，已生成的内容不会丢失。可以刷新页面重试；若持续出现，请查看浏览器控制台。
          </p>
          <pre className="mt-3 max-h-32 overflow-auto rounded-control border border-line bg-surface-soft px-3 py-2 text-left font-mono text-caption text-danger">
            {this.state.error.message}
          </pre>
          <button
            type="button"
            onClick={this.handleReload}
            className="mt-5 inline-flex h-9 items-center justify-center rounded-control bg-brand-solid px-4 text-regular font-medium text-white shadow-card transition-colors hover:bg-brand-solid-hover"
          >
            刷新页面
          </button>
        </div>
      </div>
    );
  }
}
