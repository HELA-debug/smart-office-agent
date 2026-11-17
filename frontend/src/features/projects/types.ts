/** 项目（用户自己的文档文件夹）类型：与后端 /api/v1/projects 对应。 */

export interface ProjectSummary {
  id: string;
  name: string;
  path: string;
  created_at: string;
  pinned: boolean;
  /** 扫描到的文档数（后端按深度 3、最多 400 个统计） */
  file_count: number;
  /** 目录被移动/删除时为 true：界面要提示重新指定 */
  missing: boolean;
  modified_at?: string | null;
}

export interface ProjectFile {
  name: string;
  rel_path: string;
  ext: string;
  size: number;
  modified_at: string;
  /** 绝对路径（只在项目页展示与「打开文件夹」时用） */
  path?: string;
}
