/** 技能接口（feature: skills，正式 /api/v1）：列表 + 启停 + 删除 + 导入。 */
import { API_V1_BASE } from '../../shared/config/runtime';
import { asRecord, encodeId, requestV1, requestWithBase } from '../../shared/lib/api';
import type { ApiResponse } from '../../shared/types/api';

export interface SkillItem {
  name: string;
  /** 展示名（SKILL.md frontmatter 的 title，缺省回落 name） */
  title: string;
  description: string;
  triggers: string[];
  enabled: boolean;
  /** 分类：技能页的分类筛选用它，空串归到「其他」 */
  category: string;
  /** 图标键（doc/sheet/minutes/retro/shield/book），前端映射成图标组件 */
  icon: string;
  /** 角标文案（必备精选 / 新功能推荐），空串表示没有 */
  badge: string;
  content_chars: number;
}

/** 技能库里「可以添加」的技能：已安装的不再重复出现在可添加列表里。 */
export interface CatalogSkill extends SkillItem {
  slug: string;
  installed: boolean;
}

export interface SkillList {
  skills: SkillItem[];
  prompt_chars: number;
}

export interface SkillCatalog {
  skills: CatalogSkill[];
  categories: string[];
}

function normalize(raw: unknown): SkillItem[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const record = asRecord(entry);
    if (!record || typeof record.name !== 'string') return [];
    return [
      {
        name: record.name,
        title: typeof record.title === 'string' && record.title ? record.title : record.name,
        description: typeof record.description === 'string' ? record.description : '',
        triggers: Array.isArray(record.triggers)
          ? record.triggers.filter((item): item is string => typeof item === 'string')
          : [],
        enabled: Boolean(record.enabled),
        category: typeof record.category === 'string' ? record.category : '',
        icon: typeof record.icon === 'string' ? record.icon : '',
        badge: typeof record.badge === 'string' ? record.badge : '',
        content_chars: typeof record.content_chars === 'number' ? record.content_chars : 0,
      },
    ];
  });
}

function normalizeCatalog(raw: unknown): CatalogSkill[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const item = normalize([entry])[0];
    const record = asRecord(entry);
    if (!item || !record) return [];
    return [
      {
        ...item,
        slug: typeof record.slug === 'string' ? record.slug : item.name,
        installed: Boolean(record.installed),
      },
    ];
  });
}

export const skillsApi = {
  async list(signal?: AbortSignal): Promise<ApiResponse<SkillList>> {
    const response = await requestV1<unknown>('/skills', 'GET', { signal });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        skills: normalize(record.skills),
        prompt_chars: typeof record.prompt_chars === 'number' ? record.prompt_chars : 0,
      },
      traceId: response.traceId,
    };
  },

  /** 删除技能目录（后端挪进 .trash，可人工恢复）；删除后列表与提示词一起刷新。 */
  async deleteSkill(skillId: string, signal?: AbortSignal): Promise<ApiResponse<unknown>> {
    return requestV1<unknown>(`/skills/${encodeId(skillId)}`, 'DELETE', { signal });
  },

  /** 导入一个 SKILL.md（multipart）：同名会 409，文件最大 200KB。 */
  async importSkill(file: File, signal?: AbortSignal): Promise<ApiResponse<ImportedSkill>> {
    const form = new FormData();
    form.append('file', file);
    const response = await requestWithBase<unknown>(API_V1_BASE, '/skills/import', 'POST', {
      body: form,
      signal,
    });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        name: typeof record.name === 'string' ? record.name : file.name,
        slug: typeof record.slug === 'string' ? record.slug : '',
        skill: normalize([record.skill])[0] ?? null,
      },
      traceId: response.traceId,
    };
  },

  /**
   * 让当前配置的模型把一句话需求写成一张 SKILL.md（后端负责清洗与补字段）。
   *
   * 返回的 markdown 不落盘：前端拿它当一份本地文件走 importSkill，
   * 所以「模型写的」和「手写的」走同一条入库路径，导入失败原因也一致。
   */
  async draft(idea: string, signal?: AbortSignal): Promise<ApiResponse<SkillDraft>> {
    const response = await requestV1<unknown>('/skills/draft', 'POST', {
      body: JSON.stringify({ idea }),
      signal,
    });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        markdown: typeof record.markdown === 'string' ? record.markdown : '',
        name: typeof record.name === 'string' ? record.name : 'my-skill',
        title: typeof record.title === 'string' ? record.title : '',
        description: typeof record.description === 'string' ? record.description : '',
        triggers: Array.isArray(record.triggers)
          ? record.triggers.filter((item): item is string => typeof item === 'string')
          : [],
        model: typeof record.model === 'string' ? record.model : '',
        source: record.source === 'model' ? 'model' : 'local',
        note: typeof record.note === 'string' ? record.note : '',
      },
      traceId: response.traceId,
    };
  },

  /** 技能库：可以一键添加的内置技能（未添加的不进提示词）。 */
  async catalog(signal?: AbortSignal): Promise<ApiResponse<SkillCatalog>> {
    const response = await requestV1<unknown>('/skills/catalog', 'GET', { signal });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        skills: normalizeCatalog(record.skills),
        categories: Array.isArray(record.categories)
          ? record.categories.filter((item): item is string => typeof item === 'string')
          : [],
      },
      traceId: response.traceId,
    };
  },

  /** 从技能库添加：后端复制目录并默认启用，添加后列表与提示词一起刷新。 */
  async install(skillId: string): Promise<ApiResponse<ImportedSkill>> {
    const response = await requestV1<unknown>(
      `/skills/catalog/${encodeId(skillId)}/install`,
      'POST',
    );
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        name: typeof record.name === 'string' ? record.name : skillId,
        slug: typeof record.slug === 'string' ? record.slug : '',
        skill: normalize([record.skill])[0] ?? null,
      },
      traceId: response.traceId,
    };
  },

  /** 启停只回单个技能的状态（后端立即重建运行时提示词），列表状态由界面本地更新。 */
  async setEnabled(
    skillId: string,
    enabled: boolean,
  ): Promise<ApiResponse<{ name: string; enabled: boolean; prompt_chars: number }>> {
    const response = await requestV1<unknown>(`/skills/${encodeId(skillId)}`, 'PATCH', {
      body: JSON.stringify({ enabled }),
    });
    const record = asRecord(response.data) ?? {};
    return {
      data: {
        name: typeof record.name === 'string' ? record.name : skillId,
        enabled: record.enabled !== false,
        prompt_chars: typeof record.prompt_chars === 'number' ? record.prompt_chars : 0,
      },
      traceId: response.traceId,
    };
  },
};

export interface ImportedSkill {
  name: string;
  slug: string;
  skill: SkillItem | null;
}

/** 模型（或本地骨架）写出来的一份技能草稿，还没落盘。 */
export interface SkillDraft {
  /** 完整的 SKILL.md 文本，可直接当文件导入 */
  markdown: string;
  name: string;
  title: string;
  description: string;
  triggers: string[];
  /** 生成用的模型名；本地骨架时为空串 */
  model: string;
  /** model = 模型写的；local = 没模型时的本地骨架 */
  source: 'model' | 'local';
  /** 给用户看的一句说明（要不要改、怎么改） */
  note: string;
}

export interface PromptPack {
  id: string;
  title: string;
  keywords: string[];
  chars: number;
  /** 规范原文（Markdown）：点开「内置规范包」时在弹窗里原样读，不用再请求一次。 */
  body: string;
}

/** 内置规范包：由后端按本轮需求自动挑 1–2 段注入，界面上只读展示。 */
export const promptPacksApi = {
  async list(signal?: AbortSignal): Promise<ApiResponse<PromptPack[]>> {
    const response = await requestV1<unknown>('/prompt-packs', 'GET', { signal });
    const record = asRecord(response.data) ?? {};
    const packs = Array.isArray(record.packs) ? record.packs : [];
    return {
      data: packs.flatMap((entry) => {
        const item = asRecord(entry);
        if (!item || typeof item.title !== 'string') return [];
        return [
          {
            id: typeof item.id === 'string' ? item.id : item.title,
            title: item.title,
            keywords: Array.isArray(item.keywords)
              ? item.keywords.filter((word): word is string => typeof word === 'string')
              : [],
            chars: typeof item.chars === 'number' ? item.chars : 0,
            body: typeof item.body === 'string' ? item.body : '',
          },
        ];
      }),
      traceId: response.traceId,
    };
  },
};
