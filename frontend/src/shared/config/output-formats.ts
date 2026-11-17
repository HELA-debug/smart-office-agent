/**
 * 产物格式（output format）：前端「产物格式」选择器的唯一事实来源。
 *
 * 与后端 `backend/app/services/formats.py` 的 `FORMATS` 表一一对应：
 * - 产物菜单只列 `can_output` 的格式，顺序跟表里一致（常用的在前）；
 * - 上传 accept 只认 `can_upload` 的格式（csv 能传不能产，md 只读）；
 * - 列表第一项默认与首个上传素材同格式（defaultFormatForUploads）；
 * - 无上传素材时默认 docx。
 *
 * 加一种格式要做三件事：后端表里加一行 → 这里的两个数组各加一项 →
 * 图标与标签补齐（type-style / Icons）。漏了哪一步，类型检查会当场报出来。
 */

/** 可产出的格式。 */
export const OUTPUT_FORMATS = ['docx', 'pdf', 'xlsx', 'pptx', 'txt'] as const;

export type OutputFormat = (typeof OUTPUT_FORMATS)[number];

/** 可上传的格式。md / csv 能当素材读，但都不作为产物（与后端 can_upload / can_output 对齐）。 */
export const UPLOAD_FORMATS = ['docx', 'pdf', 'xlsx', 'pptx', 'txt', 'md', 'csv'] as const;

/**
 * 媒体素材（图片 / 会议录音 / 会议视频）—— 与后端 `domain/media.py` 一一对应。
 *
 * 为什么不塞进 `UPLOAD_FORMATS`：那个数组的口径是「能当文档解析的格式」，
 * 而图片和录音要过识别引擎，上传后是异步出文字的。两者混在一起，界面就没法说明
 * 「这一项要等一会儿」。
 */
export const MEDIA_UPLOAD_EXTENSIONS = {
  image: ['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'],
  transcript: ['.srt', '.vtt'],
  audio: ['.mp3', '.m4a', '.wav', '.amr', '.aac', '.ogg', '.flac'],
  video: ['.mp4', '.mov', '.m4v', '.avi', '.mkv', '.3gp'],
} as const;

export const DEFAULT_OUTPUT_FORMAT: OutputFormat = 'docx';

/** `<input type="file" accept>` 的值。手写两份早晚会分叉，所以只留这一份。 */
export const UPLOAD_ACCEPT = Array.from(
  new Set([
    ...UPLOAD_FORMATS.map((format) => `.${format}`),
    ...Object.values(MEDIA_UPLOAD_EXTENSIONS).flat(),
  ]),
).join(',');

/** 所有可上传后缀（含媒体），拖拽时用来快速判断「这个文件能不能收」。 */
export const UPLOADABLE_EXTENSIONS: readonly string[] = UPLOAD_ACCEPT.split(',');

/** 后缀 → 媒体类别；不是媒体返回 null（按文档处理）。 */
export function mediaKindOf(filename: string): 'image' | 'transcript' | 'audio' | 'video' | null {
  const ext = `.${extOfFilename(filename)}`;
  for (const [kind, exts] of Object.entries(MEDIA_UPLOAD_EXTENSIONS)) {
    if ((exts as readonly string[]).includes(ext)) {
      return kind as 'image' | 'transcript' | 'audio' | 'video';
    }
  }
  return null;
}

/** 媒体类别在界面上叫什么（徽标 / 提示用）；文档返回空串。 */
export const MEDIA_KIND_LABELS: Record<string, string> = {
  image: '图片',
  transcript: '会议记录',
  audio: '会议录音',
  video: '会议视频',
};

/** 这个文件的单文件上限（MB）：图片和音视频放宽到 200，其余 20。 */
export function maxUploadMbForFile(filename: string): number {
  const kind = mediaKindOf(filename);
  // 与后端 max_media_mb 对齐：手机录一场会就有几十上百兆，按文档那档拦等于永远传不进来
  return kind && kind !== 'transcript' ? 200 : 20;
}

export const OUTPUT_FORMAT_LABELS: Record<OutputFormat, string> = {
  docx: 'Word 文档（docx）',
  pdf: 'PDF 文档（pdf）',
  xlsx: 'Excel 表格（xlsx）',
  pptx: 'PPT 演示文稿（pptx）',
  txt: '纯文本（txt）',
};

/** 简短标签（下拉按钮 / 徽标用）。 */
export const OUTPUT_FORMAT_SHORT: Record<OutputFormat, string> = {
  docx: 'docx',
  pdf: 'pdf',
  xlsx: 'xlsx',
  pptx: 'pptx',
  txt: 'txt',
};

/**
 * 中等长度标签：去掉后缀括号，只留看得懂的名字。
 * 给「产物格式」这种折叠行的右侧当前值用——那一行宽度有限，
 * 完整标签（Word 文档（docx））会把左侧的分组名挤成省略号。
 */
export const OUTPUT_FORMAT_COMPACT: Record<OutputFormat, string> = {
  docx: 'Word 文档',
  pdf: 'PDF 文档',
  xlsx: 'Excel 表格',
  pptx: 'PPT 演示文稿',
  txt: '纯文本',
};

export function isOutputFormat(value: string): value is OutputFormat {
  return (OUTPUT_FORMATS as readonly string[]).includes(value);
}

/** 取文件名后缀（不含点，小写）；无后缀返回空串。 */
export function extOfFilename(filename: string): string {
  const match = /\.([a-z0-9]+)$/i.exec(filename.trim());
  return match?.[1] ? match[1].toLowerCase() : '';
}

/**
 * 默认产物格式：与首个上传素材同格式；素材格式不在可选范围时回退 docx。
 */
export function defaultFormatForUploads(uploads: readonly { filename: string }[]): OutputFormat {
  for (const upload of uploads) {
    const ext = extOfFilename(upload.filename);
    if (isOutputFormat(ext)) return ext;
  }
  return DEFAULT_OUTPUT_FORMAT;
}

/**
 * 下拉列表顺序：base 排第一位（通常=素材格式），其余为「除 base 以外」的格式。
 */
export function orderedFormats(base: OutputFormat): OutputFormat[] {
  const rest = OUTPUT_FORMATS.filter((format) => format !== base);
  return [base, ...rest];
}
