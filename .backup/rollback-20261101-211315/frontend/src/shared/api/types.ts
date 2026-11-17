/**
 * 由后端 OpenAPI 生成的类型别名（唯一来源：src/shared/api/generated/schema.d.ts）。
 *
 * 用法：feature api / page 从这里拿类型，不直接 import generated 深路径。
 * 后端契约变更后执行 `npm run gen:api` 重新生成即可。
 */
import type { components } from './generated/schema';

type Schemas = components['schemas'];

/* 系统 / 设置 */
export type HealthOut = Schemas['HealthOut'];
export type SettingsOut = Schemas['SettingsOut'];
export type SettingsUpdateIn = Schemas['SettingsUpdateIn'];
export type ModelOut = Schemas['ModelOut'];
export type ModelCreateIn = Schemas['ModelCreateIn'];
export type ModelKeyOut = Schemas['ModelKeyOut'];
export type ModelTestOut = Schemas['ModelTestOut'];
export type ModelBalanceOut = Schemas['ModelBalanceOut'];
export type ToolOut = Schemas['ToolOut'];
export type SubagentOut = Schemas['SubagentOut'];
export type SkillOut = Schemas['SkillOut'];

/* 会话 / 消息 / 文件 */
export type ThreadOut = Schemas['ThreadOut'];
export type ThreadCreateIn = Schemas['ThreadCreateIn'];
export type ThreadCreateOut = Schemas['ThreadCreateOut'];
export type ThreadUpdateIn = Schemas['ThreadUpdateIn'];
export type ThreadBulkDeleteOut = Schemas['ThreadBulkDeleteOut'];
export type MessageOut = Schemas['MessageOut'];
export type ThreadDetailEnvelope = Schemas['ThreadDetailEnvelope'];
export type FileOut = Schemas['FileOut'];
export type FileListOut = Schemas['FileListOut'];
export type UploadResultOut = Schemas['UploadResultOut'];
export type UploadItemOut = Schemas['UploadItemOut'];

/* 运行 / 事件 / 审批 */
export type RunOut = Schemas['RunOut'];
export type RunEnvelope = Schemas['RunEnvelope'];
export type RunCancelOut = Schemas['RunCancelOut'];
export type RunRequestIn = Schemas['RunRequestIn'];
export type RunEventOut = Schemas['RunEventOut'];
export type RunEventsOut = Schemas['RunEventsOut'];
export type ApprovalOut = Schemas['ApprovalOut'];
export type ApprovalRequestIn = Schemas['ApprovalRequestIn'];
export type ApprovalDecisionOut = Schemas['ApprovalDecisionOut'];

/* 产物 / 审计 / 用量 */
export type ArtifactOut = Schemas['ArtifactOut'];
export type ArtifactEnvelope = Schemas['ArtifactEnvelope'];
export type DeleteOut = Schemas['DeleteOut'];
export type AuditOut = Schemas['AuditOut'];
export type AuditRunOut = Schemas['AuditRunOut'];
export type UsageOut = Schemas['UsageOut'];
export type UsageDayOut = Schemas['UsageDayOut'];
/* 官方控制台用量（对账参考）：需要浏览器登录态 token，不是 API Key */
export type ProviderUsageOut = Schemas['ProviderUsageOut'];
export type ProviderUsageDayOut = Schemas['ProviderUsageDayOut'];
export type ProviderTokenOut = Schemas['ProviderTokenOut'];

/* 包装响应（列表类） */
export type ThreadListOut = Schemas['ThreadListOut'];
export type RunListOut = Schemas['RunListOut'];
export type ArtifactListOut = Schemas['ArtifactListOut'];
export type ModelListOut = Schemas['ModelListOut'];
export type ToolListOut = Schemas['ToolListOut'];
export type SubagentListOut = Schemas['SubagentListOut'];
export type SkillListOut = Schemas['SkillListOut'];
