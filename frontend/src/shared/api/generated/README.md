# generated/（自动生成，禁止手改）

由 `npm run gen:api` 通过 openapi-typescript 从后端 OpenAPI 文档生成：

- 契约来源：`OPENAPI_URL` 或 `http://127.0.0.1:8000/api/v1/openapi.json` / `/openapi.json`
- 输出：`schema.d.ts`
- 生成物不提交审查意见；契约变更（B1 后端分层完成后）只需重跑脚本。

使用方式（B3 接入）：

```ts
import type { paths } from '../../../shared/api/generated/schema';
type RunRequest = paths['/api/v1/threads/{thread_id}/runs/stream']['post']['requestBody'];
```

> 注意：当前仓库中的 `schema.d.ts`（若存在）来自 v0 后端快照，B1 的 `/api/v1`
> 与 OpenAPI 快照就绪后需要重新生成；旧的手写类型 `shared/types/*` 保留作为兼容层。
