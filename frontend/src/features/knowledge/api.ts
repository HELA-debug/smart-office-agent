/**
 * 知识库接口：**后期接入用，当前页面不调用**。
 *
 * 现在页面读的是 staticCorpus.ts 的写死内容和本地检索，不联网、不依赖后端。
 * 等要接真实语料时，把 KnowledgePage 里的 searchStatic 换成这里的 searchKnowledge，
 * 并按 contracts.ts 的形状映射字段；页面骨架与文案不用改。
 */
import { requestV1 } from '../../shared/lib/api';
import type { KnowledgeSearchResponse } from './contracts';

export interface KnowledgeStats {
  blocks: number;
  documents: number;
  kinds: string[];
  tags: string[];
}

export async function searchKnowledge(query: string, topK = 20): Promise<KnowledgeSearchResponse> {
  const path = `/knowledge/search?q=${encodeURIComponent(query)}&top_k=${topK}`;
  const response = await requestV1<KnowledgeSearchResponse>(path, 'GET');
  return response.data;
}

export async function knowledgeStats(): Promise<KnowledgeStats> {
  const response = await requestV1<KnowledgeStats>('/knowledge/stats', 'GET');
  return response.data;
}
