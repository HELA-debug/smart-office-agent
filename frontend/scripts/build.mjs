/**
 * 构建入口：`npm run build` 的实际执行体。
 *
 * 背景：部分 Windows 环境的全局 %TEMP% 会被安全软件/EDR 锁住，esbuild 在
 * vite build 期间无法删除自己的临时文件（"Access is denied"）。
 * 这里把 TEMP/TMP 指到仓库内的 .tmp/，再执行 `tsc -b` + `vite build`，
 * 保证本机与 CI 行为一致，同时不依赖 shell 语法。
 */
import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import path from 'node:path';

const projectRoot = path.resolve(import.meta.dirname, '..');
const tmpDir = path.join(projectRoot, '.tmp');
mkdirSync(tmpDir, { recursive: true });

const env = { ...process.env, TEMP: tmpDir, TMP: tmpDir };
// 当前进程也要覆盖：vite/esbuild service 会继承 process.env
process.env.TEMP = tmpDir;
process.env.TMP = tmpDir;

const tsc = spawnSync(
  process.execPath,
  [path.join(projectRoot, 'node_modules', 'typescript', 'bin', 'tsc'), '-b'],
  { stdio: 'inherit', cwd: projectRoot, env },
);
if (tsc.status !== 0) {
  process.exit(tsc.status ?? 1);
}

const { build } = await import('vite');
await build({ root: projectRoot, mode: 'production' });
