/**
 * 从后端 OpenAPI 生成前端类型（禁止手改 generated 目录）。
 *
 * 优先级：
 *   1. OPENAPI_URL 环境变量；
 *   2. 仓库内契约快照 contracts/openapi.v1.json（CI 校验过的唯一真源，
 *      不依赖后端进程是否在跑，也不会读到旧进程的过期 schema）；
 *   3. /api/v1/openapi.json（B1 之后的新契约）；
 *   4. /openapi.json（兼容旧契约）。
 *
 * 后端未就绪且无快照时给出明确提示并以非 0 退出，不产生半成品文件。
 */
import { writeFileSync, mkdirSync, readFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import openapiTS, { astToString } from 'openapi-typescript';

const OUT_DIR = path.resolve('src/shared/api/generated');
const OUT_FILE = path.join(OUT_DIR, 'schema.d.ts');
const CONTRACT_FILE = path.resolve('../contracts/openapi.v1.json');

const urls = [
  process.env.OPENAPI_URL,
  'http://127.0.0.1:8000/api/v1/openapi.json',
  'http://127.0.0.1:8000/openapi.json',
].filter(Boolean);

function isSpec(payload) {
  return Boolean(payload) && typeof payload === 'object' && 'openapi' in payload;
}

async function findSpec() {
  // 先读契约快照：CI 已验证它与后端代码一致，且无需启动服务
  if (process.env.OPENAPI_URL ? false : existsSync(CONTRACT_FILE)) {
    try {
      const payload = JSON.parse(readFileSync(CONTRACT_FILE, 'utf8'));
      if (isSpec(payload)) {
        return { url: path.relative(process.cwd(), CONTRACT_FILE), spec: payload };
      }
    } catch {
      // 快照损坏时退回 HTTP 探测
    }
  }
  for (const url of urls) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(4000) });
      if (!response.ok) continue;
      const payload = await response.json();
      if (isSpec(payload)) {
        return { url, spec: payload };
      }
    } catch {
      // 试下一个候选
    }
  }
  return null;
}

const found = await findSpec();
if (!found) {
  console.error(
    [
      '',
      '✗ 未找到可用的 OpenAPI 文档。',
      '  请先启动后端（默认 http://127.0.0.1:8000），或指定：',
      '    OPENAPI_URL=http://127.0.0.1:8000/openapi.json npm run gen:api',
      '',
    ].join('\n'),
  );
  process.exit(1);
}

console.log(`→ 生成类型 ← ${found.url}（OpenAPI ${found.spec.openapi}）`);

const ast = await openapiTS(found.spec);
const output = astToString(ast);

if (!output.trim()) {
  console.error('✗ 生成结果为空，未写入文件');
  process.exit(1);
}

mkdirSync(OUT_DIR, { recursive: true });
writeFileSync(OUT_FILE, output, 'utf8');
console.log(`✓ 已生成 ${path.relative(process.cwd(), OUT_FILE)}（请勿手改）`);
