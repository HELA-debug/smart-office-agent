/**
 * 前端构建指纹：让「本地看到的是旧界面」这件事自己说出来。
 *
 * 背景（真实的排错经历）：`frontend/dist` 和打包好的 exe 都在 .gitignore 里，
 * `git pull` 只更新源码。没有重新 `npm run build`（或没重打 exe）时，本地跑起来的
 * 还是上一版界面——底部还挂着早就删掉的卡片、项目区没有折叠箭头，看起来就像
 * 「样式/清晰度坏了」，但代码其实是对的，只是跑的不是这份代码。
 *
 * 所以这里做两件事：
 * 1. 首屏在控制台打一行构建号（`<git sha>-<构建时间>`），肉眼可对；
 * 2. 拉一次 `/api/v1/health`，把三个编号摆在一起判断是谁旧了：
 *    - 前端构建号（本文件里的 `BUILD_SHA`，构建时注入）
 *    - 后端进程载入的版本（`git_sha`，进程启动那一刻的快照）
 *    - 仓库当前 HEAD（`git_sha_live`，每次现读）
 *
 * 第三个字段是第五十七轮补的：之前的判断只看「前端 sha ≠ 后端 sha」，于是当后端是
 * 一个跨了提交还在跑的老进程（开发时太常见了）时，提示会反过来怪前端「没重新构建」，
 * 让人去 `npm run build` 也没用——该做的是重启。有了 live，才能分清是谁落后。
 */
import { API_V1_BASE } from '../config/runtime';

declare const __BUILD_ID__: string;

/** 形如 `60a4d6a-202610292215`；开发态或拿不到 git 时退回 `dev`。 */
export const BUILD_ID: string =
  typeof __BUILD_ID__ === 'string' && __BUILD_ID__.length > 0 ? __BUILD_ID__ : 'dev';

/** 构建时所在的 git 提交（短 sha）。 */
export const BUILD_SHA: string = BUILD_ID.split('-')[0] || 'dev';

export const STALE_BUILD_EVENT = 'office-agent:stale-build';

/** 谁旧了：界面（产物没重建）/ 后端进程（老进程跨了提交还在跑）/ 两边都旧。 */
export type BuildMismatchKind = 'frontend' | 'backend' | 'both';

export interface BuildMismatch {
  /** 界面产物构建时的提交。 */
  frontend: string;
  /** 后端进程启动时载入的提交。 */
  backend: string;
  /** 仓库当前 HEAD；老后端不报这个字段时为空串。 */
  live: string;
  kind: BuildMismatchKind;
}

const short = (value: string | null | undefined): string => (value ?? '').trim().slice(0, 7);

/**
 * 判断「跑起来的这一套」跟仓库对不对得上，对不上就说清是谁旧了。
 *
 * 只在三个号都能确定时才判定：开发态（`dev`）、拿不到 git 的老后端、后端 mock
 * 一律返回 null——宁可少提示，也不要天天误报。
 */
export function classifyBuildMismatch(input: {
  backend?: string | null;
  live?: string | null;
  frontend?: string;
}): BuildMismatch | null {
  const frontend = short(input.frontend ?? BUILD_SHA);
  // 开发态（vite dev）没有构建产物，SHA 对不上属于正常
  if (!frontend || frontend === 'dev' || frontend === 'nogit') return null;

  const backend = short(input.backend);
  if (!backend || backend === 'mock') return null;

  const live = short(input.live);
  // 老后端（还不报 git_sha_live）：只能沿用「两边 sha 不一致 = 界面旧」的保守判断
  if (!live || live === 'mock') {
    return backend === frontend ? null : { frontend, backend, live: '', kind: 'frontend' };
  }

  const frontendStale = frontend !== live;
  const backendStale = backend !== live;
  if (frontendStale && backendStale) return { frontend, backend, live, kind: 'both' };
  if (frontendStale) return { frontend, backend, live, kind: 'frontend' };
  if (backendStale) return { frontend, backend, live, kind: 'backend' };
  return null;
}

/** 首屏在控制台留一行构建号：排查「这是哪一版」时不用猜。 */
export function logBuildInfo(): void {
  if (typeof console === 'undefined') return;
  // eslint-disable-next-line no-console -- 这行就是要给人看见的，不是调试残留
  console.info(
    `%c OA 前端构建 ${BUILD_ID} `,
    'background:#0e7a4a;color:#fff;border-radius:3px;padding:2px 4px;font-size:11px',
  );
}

/** 广播「跑的不是仓库这份代码」，由界面决定怎么提示。 */
export function emitStaleBuild(detail: BuildMismatch): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(STALE_BUILD_EVENT, { detail }));
}

/** 订阅落后提示，返回退订函数（React effect 直接 return 它）。 */
export function onStaleBuild(handler: (detail: BuildMismatch) => void): () => void {
  if (typeof window === 'undefined') return () => {};
  const listener = (event: Event) => {
    const detail = (event as CustomEvent<BuildMismatch>).detail;
    if (detail?.backend && detail?.kind) handler(detail);
  };
  window.addEventListener(STALE_BUILD_EVENT, listener);
  return () => window.removeEventListener(STALE_BUILD_EVENT, listener);
}

/**
 * 拉一次健康检查，比对三边的版本号。失败静默：服务没起来时另有 ServiceDownBanner
 * 负责，这里再报一遍只会变成噪声。
 *
 * 返回「是否仍不一致」，让提示条上的「重新检查」能自己收敛。
 */
export async function probeBuildFreshness(timeoutMs = 4000): Promise<boolean> {
  if (typeof fetch !== 'function') return false;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_V1_BASE}/health`, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
      cache: 'no-store',
    });
    if (!response.ok) return false;
    const payload = (await response.json()) as {
      git_sha?: string;
      git_sha_live?: string;
      mock?: boolean;
    };
    if (payload.mock) return false;
    const mismatch = classifyBuildMismatch({
      backend: payload.git_sha,
      live: payload.git_sha_live,
    });
    if (!mismatch) return false;
    emitStaleBuild(mismatch);
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
