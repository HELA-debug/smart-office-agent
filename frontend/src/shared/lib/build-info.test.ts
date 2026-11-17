/**
 * 构建指纹的判定规则：只在三个号都能确定时才说「不一致」，并分清是谁旧了。
 *
 * 误报比漏报更烦人——每次打开都弹一条「你看到的是旧界面」，用户很快就学会无视它。
 * 所以 `dev` / 老后端 / 后端 `mock` 一律不做判断。反过来，判断出来是**后端进程**旧了，
 * 就不能再让用户去 `npm run build`（干了也没用），得说「重启」。
 */
import { describe, expect, it, vi } from 'vitest';
import {
  BUILD_ID,
  BUILD_SHA,
  classifyBuildMismatch,
  onStaleBuild,
  probeBuildFreshness,
} from './build-info';

function mockHealth(payload: Record<string, unknown>, ok = true) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok,
      json: async () => payload,
    })),
  );
}

describe('classifyBuildMismatch', () => {
  it('测试环境下没有注入构建号，退回 dev，不做判断', () => {
    expect(BUILD_ID).toBe('dev');
    expect(BUILD_SHA).toBe('dev');
    expect(classifyBuildMismatch({ backend: '60a4d6a', live: '9b7f7a7' })).toBeNull();
  });

  it('后端 mock / 空值 / 老后端没有 live 且 sha 一致时都不提示', () => {
    expect(classifyBuildMismatch({ backend: 'mock', frontend: '60a4d6a' })).toBeNull();
    expect(classifyBuildMismatch({ backend: '', frontend: '60a4d6a' })).toBeNull();
    expect(classifyBuildMismatch({ backend: '60a4d6a', live: '', frontend: '60a4d6a' })).toBeNull();
  });

  it('仓库前进、后端进程也前进，但界面没重建 → 界面旧', () => {
    expect(
      classifyBuildMismatch({ backend: '9b7f7a7', live: '9b7f7a7', frontend: '60a4d6a' }),
    ).toEqual({ frontend: '60a4d6a', backend: '9b7f7a7', live: '9b7f7a7', kind: 'frontend' });
  });

  it('界面是最新构建，但后端是跨了提交还在跑的老进程 → 后端旧（该重启，不是重建）', () => {
    expect(
      classifyBuildMismatch({ backend: '1daa671', live: '8195a64', frontend: '8195a64' }),
    ).toEqual({ frontend: '8195a64', backend: '1daa671', live: '8195a64', kind: 'backend' });
  });

  it('两边都落后于仓库 → both', () => {
    expect(
      classifyBuildMismatch({ backend: '1daa671', live: '8195a64', frontend: '60a4d6a' }),
    ).toEqual({ frontend: '60a4d6a', backend: '1daa671', live: '8195a64', kind: 'both' });
  });

  it('三者一致 → 不提示', () => {
    expect(
      classifyBuildMismatch({ backend: '8195a64', live: '8195a64', frontend: '8195a64' }),
    ).toBeNull();
  });

  it('只比前 7 位：后端给的是长 sha 也能对上', () => {
    expect(
      classifyBuildMismatch({
        backend: '60a4d6a9f1c2b3d4e5f60718293a4b5c6d7e8f90',
        live: '60a4d6a',
        frontend: '60a4d6a',
      }),
    ).toBeNull();
  });

  it('老后端不报 live 时退回旧规则：两边 sha 不一致就算界面旧', () => {
    expect(classifyBuildMismatch({ backend: '9b7f7a7', live: '', frontend: '60a4d6a' })).toEqual({
      frontend: '60a4d6a',
      backend: '9b7f7a7',
      live: '',
      kind: 'frontend',
    });
  });
});

describe('probeBuildFreshness', () => {
  it('健康检查失败时静默返回 false', async () => {
    mockHealth({ git_sha: '60a4d6a' }, false);
    expect(await probeBuildFreshness()).toBe(false);
  });

  it('前端 dev 构建下即便 sha 不同也不提示（本地开发态本来就对不上）', async () => {
    mockHealth({ git_sha: '60a4d6a', git_sha_live: '9b7f7a7' });
    expect(await probeBuildFreshness()).toBe(false);
  });

  it('mock 模式不做判断', async () => {
    mockHealth({ git_sha: '60a4d6a', git_sha_live: '9b7f7a7', mock: true });
    expect(await probeBuildFreshness()).toBe(false);
  });
});

describe('广播', () => {
  it('广播接口能收到事件（供界面挂提示条）', () => {
    const received = Array<{ backend: string; kind: string }>();
    const stop = onStaleBuild((detail) => received.push(detail));
    window.dispatchEvent(
      new CustomEvent('office-agent:stale-build', {
        detail: { frontend: 'aaa1111', backend: 'bbb2222', live: 'ccc3333', kind: 'both' },
      }),
    );
    stop();
    expect(received).toEqual([
      { frontend: 'aaa1111', backend: 'bbb2222', live: 'ccc3333', kind: 'both' },
    ]);
  });
});
