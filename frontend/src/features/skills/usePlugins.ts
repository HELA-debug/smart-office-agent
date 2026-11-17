/**
 * 插件（工具能力）目录：扩展页「插件」tab 的数据源。
 *
 * 这里的「插件」不是第三方 SaaS 连接器，而是真正常驻在运行时里的工具：
 * 后端 `GET /api/v1/tools` 一次返回全部已注册工具（含 JSON Schema 与风险等级），
 * 前端按前缀把它们归成 5 个能看懂的插件——文档生成 / 脚本加工 / 素材读取 /
 * 产物清理 / 任务计划。以后后端加了新工具，这里不用改代码也会多出一个分组，
 * 只会在标题上退化成工具前缀。
 *
 * 只读：插件随应用发布，全部启用；高风险工具动手前会过门控，所以卡片上直接把
 * 风险写出来，用户不用去审计页猜。
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { asRecord, errorMessage, requestV1 } from '../../shared/lib/api';

export interface ToolInfo {
  name: string;
  description: string;
  /** high = 调用前要用户确认 */
  risk: string;
}

export interface PluginInfo {
  /** 稳定的 key（分组 id） */
  id: string;
  title: string;
  summary: string;
  /** 图标键：doc / terminal / folder / trash / list，页面映射成图标组件 */
  icon: string;
  /** 配色键：沿用技能的分类色，一列插件扫下来颜色不打架 */
  tone: string;
  /** 这个插件包含的工具名（后端原名，如 `doc.generate_report`） */
  tools: string[];
  /** 是否含高风险工具 */
  highRisk: boolean;
}

export interface PluginsState {
  plugins: PluginInfo[];
  toolCount: number;
  status: 'loading' | 'ready' | 'error';
  error: string | null;
  reload: () => void;
}

interface GroupSpec {
  id: string;
  title: string;
  summary: string;
  icon: string;
  tone: string;
  tools: string[];
}

/** 已知分组：顺序就是页面上的顺序（常用的、能力最强的排前面）。 */
const GROUPS: GroupSpec[] = [
  {
    id: 'doc',
    title: '文档生成',
    summary: '脚本解析素材结构，再按模板写成 DOCX / PDF / XLSX / MD，生成完自动登记成产物',
    icon: 'doc',
    tone: '办公文档',
    tools: ['doc.analyze_material', 'doc.generate_report'],
  },
  {
    id: 'code',
    title: '脚本加工',
    summary: '在本机受控目录跑 Python，做批量改写、合并拆分、格式转换这类细活',
    icon: 'terminal',
    tone: '表格数据',
    tools: ['code.run_python'],
  },
  {
    id: 'material',
    title: '素材读取',
    summary: '读取本次会话上传的素材正文，列出文件名、字数与解析状态',
    icon: 'folder',
    tone: '会议协作',
    tools: ['file.read', 'file.list'],
  },
  {
    id: 'cleanup',
    title: '产物清理',
    summary: '把不要的产物移进回收站（软删，记录留在审计里可查）',
    icon: 'trash',
    tone: '内容写作',
    tools: ['file.delete'],
  },
  {
    id: 'plan',
    title: '任务计划',
    summary: '多步任务先写一份待办清单，边做边勾，长任务不会跑偏',
    icon: 'list',
    tone: '文件处理',
    tools: ['todo.write', 'todo.list'],
  },
];

/** 未知工具的前缀兜底：`web.fetch` 这种就归到「web」。 */
const PREFIX_ICONS: Record<string, string> = {
  web: 'folder',
  mail: 'doc',
  search: 'folder',
};

function trimDescription(text: string): string {
  const first = text.split('。')[0] ?? text;
  return first.length > 80 ? `${first.slice(0, 79)}…` : first;
}

function group(tools: ToolInfo[]): PluginInfo[] {
  const byName = new Map(tools.map((tool) => [tool.name, tool]));
  const plugins: PluginInfo[] = [];

  for (const spec of GROUPS) {
    const hit = spec.tools.filter((name) => byName.has(name));
    if (hit.length === 0) continue;
    plugins.push({
      id: spec.id,
      title: spec.title,
      summary: spec.summary,
      icon: spec.icon,
      tone: spec.tone,
      tools: hit,
      highRisk: hit.some((name) => byName.get(name)?.risk === 'high'),
    });
  }

  const covered = new Set(GROUPS.flatMap((spec) => spec.tools));
  const rest = tools.filter((tool) => !covered.has(tool.name));
  for (const tool of rest) {
    const prefix = tool.name.split('.')[0] || tool.name;
    const existing = plugins.find((plugin) => plugin.id === `prefix-${prefix}`);
    if (existing) {
      existing.tools.push(tool.name);
      existing.highRisk = existing.highRisk || tool.risk === 'high';
      continue;
    }
    plugins.push({
      id: `prefix-${prefix}`,
      title: prefix,
      summary: trimDescription(tool.description),
      icon: PREFIX_ICONS[prefix] ?? 'list',
      tone: '文件处理',
      tools: [tool.name],
      highRisk: tool.risk === 'high',
    });
  }

  return plugins;
}

function normalizeTools(raw: unknown): ToolInfo[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((entry) => {
    const record = asRecord(entry);
    if (!record || typeof record.name !== 'string') return [];
    return [
      {
        name: record.name,
        description: typeof record.description === 'string' ? record.description : '',
        risk: typeof record.risk === 'string' ? record.risk : 'low',
      },
    ];
  });
}

export function usePlugins(): PluginsState {
  const [tools, setTools] = useState<ToolInfo[]>([]);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus((current) => (current === 'ready' ? current : 'loading'));
    void (async () => {
      try {
        const response = await requestV1<unknown>('/tools', 'GET', { signal: controller.signal });
        const record = asRecord(response.data) ?? {};
        setTools(normalizeTools(record.tools));
        setError(null);
        setStatus('ready');
      } catch (cause) {
        if (controller.signal.aborted) return;
        setError(errorMessage(cause));
        setStatus('error');
      }
    })();
    return () => controller.abort();
  }, [nonce]);

  const plugins = useMemo(() => group(tools), [tools]);
  const reload = useCallback(() => setNonce((value) => value + 1), []);

  return { plugins, toolCount: tools.length, status, error, reload };
}
