/**
 * 知识库模块契约：当前只有类型与工具名，不含实现。
 *
 * 定位（与插件 / 技能划清边界）：
 * - 插件 = 随应用发布的工具能力，常驻，不能卸；
 * - 技能 = 少量「做法包」，添加后才写进系统提示词；
 * - 知识库 = 大规模外部语料，**不进提示词**，按查询召回片段，人和 Agent 共用一条检索链。
 *
 * 这层是给正式版预留的对接形状：灌入管道、索引服务、Agent 工具都按它实现，
 * 页面与工具层不再各写一套。
 *
 * 当前页面**不调用这里**：语料写死在 staticCorpus.ts，检索在前端本地完成，
 * 内容是给普通用户看的常识。后期接真实语料时，把 searchStatic 换成
 * api.ts 的 searchKnowledge，并按这里的形状映射字段即可。
 * 页面文案不要出现本文件里的技术词——第一读者是用户，不是开发。
 */

/** Agent 侧工具名；与 shared/lib/format.ts 已有的工具名映射保持一致。 */
export const KNOWLEDGE_SEARCH_TOOL = 'knowledge.search' as const;

/** 语料形态：正式版会持续扩充，这里只列首期纳入的几类。 */
export type KnowledgeSourceKind =
  'document' | 'spreadsheet' | 'webpage' | 'transcript' | 'structured';

/**
 * 一条可召回片段，对齐后端 domain/rag.py 的 Block 对外形状。
 * id 是引用编号（[S3]），成文时能回溯到原文，也是「检索不到就别编」的凭据。
 */
export interface KnowledgePassage {
  id: string;
  title: string;
  source: string;
  section: string;
  snippet: string;
  kind: KnowledgeSourceKind;
  tags: string[];
  score: number;
  updatedAt: string;
  /** 引用回溯定位：正式版由索引给出 */
  locator?: { file: string; block: number; start: number };
}

export interface KnowledgeSearchRequest {
  query: string;
  topK?: number;
  kinds?: KnowledgeSourceKind[];
  /** Agent 调用时带上 run_id，便于审计与用量归属 */
  runId?: string;
}

export interface KnowledgeSearchResponse {
  hits: KnowledgePassage[];
  /** 库内片段总量（海量），不等于本次返回条数 */
  total: number;
  /** browsing = 空查询时浏览书架；none = 检索不到，此时不许补编 */
  level: 'browsing' | 'strong' | 'weak' | 'none';
  tookMs: number;
  /** 给 Agent 注入的带编号片段文本；页面不用 */
  passages?: string;
}

/** 检索端口：正式版由 API / 索引服务实现，Agent 与页面共用它。 */
export type KnowledgeSearch = (request: KnowledgeSearchRequest) => Promise<KnowledgeSearchResponse>;
