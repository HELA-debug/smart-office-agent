/**
 * 知识库的**写死内容**：给普通用户看的知识片段，不是项目内部技术文档。
 *
 * 范围（用户 2026-11-10 定的暂时口径）：**只放文档办公 + 写论文**这两摊——
 * Word / Excel / PPT / PDF、公文与汇报、校对规范，以及论文格式、模板、
 * 参考文献与查重。报销、合同、法务、时间管理这些暂时不收。
 *
 * 原则：
 * - 一条 = 一个普通人能用上的常识，说人话，不出现接口名 / 参数 / 代码术语；
 * - 来源写成书名、章节写成目录，像在图书馆里翻到的一页；
 * - 纯静态、不联网、不读后端、不会自动更新；
 * - 浏览态有硬上限：一批固定几条，翻完就换一批，不无限往下滚。
 *
 * 后期要接真实语料时，把 KnowledgePage 里的 searchStatic 换成
 * features/knowledge/api.ts 的 searchKnowledge，并按 contracts.ts 的形状映射字段。
 */

/** 一次「随便翻翻」最多铺几条：一屏放得下，翻页靠「换一批」，不做框内滚动。 */
export const BROWSE_PAGE_SIZE = 5;
/** 一次检索最多返回几条，命中再多也只给前几条。 */
export const SEARCH_LIMIT = 8;

export interface StaticPassage {
  /** 引用编号，成文时可回溯到这一条 */
  id: string;
  /** 一句话说清这条讲什么 */
  title: string;
  /** 书名式的出处 */
  source: string;
  section: string;
  /** 正文：普通人读得懂的两三句话 */
  snippet: string;
  /** 中文领域名，页面上的分类标签 */
  category: string;
  tags: string[];
}

export interface StaticHit extends StaticPassage {
  /** 浏览态为 null：没有检索词，就不显示相关度 */
  score: number | null;
}

export interface StaticSearchResult {
  hits: StaticHit[];
  /** 库内片段总量，不等于本次返回条数 */
  total: number;
  level: 'browsing' | 'strong' | 'weak' | 'none';
  /** 本次口径下共有多少条（浏览态=该范围总量，检索态=命中总量） */
  matched: number;
  /** 浏览态分页 */
  page: number;
  pageCount: number;
}

/** 检索词建议：写用户真会搜的词，围绕文档办公和论文。 */
export const SUGGESTED_QUERIES = [
  '论文格式',
  '模板',
  '参考文献',
  '摘要',
  '页眉',
  '目录',
  'Excel',
  'PPT',
  'PDF',
  '行距',
];

export const STATIC_PASSAGES: readonly StaticPassage[] = [
  // ── Word 排版 ──────────────────────────────────────────────
  {
    id: 'K001',
    title: '标题和正文怎么分开',
    source: '《Word 排版入门》',
    section: '第 1 章 先把层次排清楚',
    snippet:
      '标题用大一号字并加粗，正文用统一的字号。同一份文件里，同级标题的字号和间距必须完全一致，不要一页一个样子。',
    category: 'Word 排版',
    tags: ['入门', '字号'],
  },
  {
    id: 'K002',
    title: '段首空两格要用缩进，不要敲空格',
    source: '《Word 排版入门》',
    section: '第 1 章 先把层次排清楚',
    snippet:
      '中文段落习惯开头空两个字，在段落设置里选「首行缩进 2 字符」。用空格敲出来，换台电脑或改个字体就全乱了。',
    category: 'Word 排版',
    tags: ['缩进', '常见错误'],
  },
  {
    id: 'K003',
    title: '正文两端对齐，标题别拉满',
    source: '《Word 排版入门》',
    section: '第 2 章 对齐、行距与页面',
    snippet:
      '正文用两端对齐，右边缘是齐的，看着整齐。大标题居中，小标题靠左顶格；把大字也拉成两端对齐，字距会被撑得很难看。',
    category: 'Word 排版',
    tags: ['对齐'],
  },
  {
    id: 'K004',
    title: '行距怎么选才耐看',
    source: '《Word 排版入门》',
    section: '第 2 章 对齐、行距与页面',
    snippet:
      '正文用 1.5 倍行距最耐看；表格、脚注可以收紧到单倍。论文和公文若学校或单位给了具体倍数，以要求为准。',
    category: 'Word 排版',
    tags: ['行距'],
  },
  {
    id: 'K005',
    title: '页边距别贴着纸边',
    source: '《Word 排版入门》',
    section: '第 2 章 对齐、行距与页面',
    snippet:
      '上下左右各留两厘米左右，打印和装订才不会吃掉字。需要装订的文件，靠装订那一侧再多留一点。',
    category: 'Word 排版',
    tags: ['页边距'],
  },
  {
    id: 'K006',
    title: '另起一页要插分页符',
    source: '《Word 排版入门》',
    section: '第 3 章 别让版面跑位',
    snippet:
      '需要换页时插入分页符，不要连按十几个回车。前面一改内容，靠回车顶出来的「分页」会全部跑位。',
    category: 'Word 排版',
    tags: ['分页', '常见错误'],
  },
  {
    id: 'K007',
    title: '用样式比手动刷格式稳',
    source: '《Word 排版入门》',
    section: '第 3 章 别让版面跑位',
    snippet:
      '把标题、正文、引用分别存成样式，改一次全篇跟着变。逐段手动改格式，改到后面一定会漏掉几段。',
    category: 'Word 排版',
    tags: ['样式', '效率'],
  },
  {
    id: 'K008',
    title: '目录让软件自动生成',
    source: '《Word 排版入门》',
    section: '第 4 章 长文档',
    snippet: '先给各级标题套上标题样式，再插入自动目录。手打出来的目录，内容一改页码就全错。',
    category: 'Word 排版',
    tags: ['目录', '长文档'],
  },
  {
    id: 'K009',
    title: '页眉页脚和页码',
    source: '《Word 排版入门》',
    section: '第 4 章 长文档',
    snippet:
      '书名或章节名放页眉，页码放页脚。封面一般不要页码，用「首页不同」单独设一下，别在封面手打一个 1。',
    category: 'Word 排版',
    tags: ['页眉', '页码'],
  },
  {
    id: 'K010',
    title: '长表格跨页要重复表头',
    source: '《Word 排版入门》',
    section: '第 4 章 长文档',
    snippet:
      '表格超过一页时，设成「在各页顶端重复标题行」。不然翻到第二页，读者不知道每一列是什么。',
    category: 'Word 排版',
    tags: ['表格'],
  },

  // ── Excel 表格 ─────────────────────────────────────────────
  {
    id: 'K011',
    title: '一列数字求和用 SUM',
    source: '《Excel 常用功能手册》',
    section: '第 1 章 最常用的几个公式',
    snippet:
      '选中要求和的一列，用 SUM 把范围框起来即可。范围写成整列或一段区域，比一个个单元格相加更不容易漏。',
    category: 'Excel 表格',
    tags: ['公式', '入门'],
  },
  {
    id: 'K012',
    title: '公式往下拖时，别让参照跟着跑',
    source: '《Excel 常用功能手册》',
    section: '第 1 章 最常用的几个公式',
    snippet:
      '如果某个单元格（比如单价、税率）要一直固定，在行列号前加 $ 锁住。不加的话，公式一往下拖，参照就跟着挪，结果全错。',
    category: 'Excel 表格',
    tags: ['公式', '常见错误'],
  },
  {
    id: 'K013',
    title: '按名字查另一张表里的值',
    source: '《Excel 常用功能手册》',
    section: '第 2 章 把两张表对起来',
    snippet:
      '用查找类函数按编号或姓名，把另一张表里的价格、部门带过来。关键是两边用来匹配的那一列，写法必须完全一致。',
    category: 'Excel 表格',
    tags: ['查找', '多表'],
  },
  {
    id: 'K014',
    title: '数据表里不要合并单元格',
    source: '《Excel 常用功能手册》',
    section: '第 3 章 好表格的样子',
    snippet:
      '合并过的单元格没法正常筛选、排序和做透视。需要看起来分组，用缩进或底色，别动单元格本身。',
    category: 'Excel 表格',
    tags: ['规范', '常见错误'],
  },
  {
    id: 'K015',
    title: '日期要存成真日期',
    source: '《Excel 常用功能手册》',
    section: '第 3 章 好表格的样子',
    snippet:
      '输入 2026-10-01 这样的真日期，才能排序、算间隔、按月汇总。写成「10 月初」这类文字，软件只当它是普通文本。',
    category: 'Excel 表格',
    tags: ['日期', '规范'],
  },
  {
    id: 'K016',
    title: '筛选之前先做好表头',
    source: '《Excel 常用功能手册》',
    section: '第 3 章 好表格的样子',
    snippet: '第一行只放列名，不写大标题、不放说明、不要空行。这样一点筛选，整张表都能被正确框住。',
    category: 'Excel 表格',
    tags: ['筛选', '规范'],
  },
  {
    id: 'K017',
    title: '用 IF 让表格自己判断',
    source: '《Excel 常用功能手册》',
    section: '第 4 章 条件判断',
    snippet:
      'IF 就是「如果……就……否则……」。比如超过预算显示「超了」，没超过显示「正常」，一眼就能扫出异常行。',
    category: 'Excel 表格',
    tags: ['公式', '入门'],
  },
  {
    id: 'K018',
    title: '表往下滚时把首行钉住',
    source: '《Excel 常用功能手册》',
    section: '第 4 章 条件判断',
    snippet: '冻结首行后，滚到几百行也能看见每列叫什么。做长表第一步就该设这个。',
    category: 'Excel 表格',
    tags: ['冻结', '效率'],
  },
  {
    id: 'K019',
    title: '数字别存成文本',
    source: '《Excel 常用功能手册》',
    section: '第 3 章 好表格的样子',
    snippet:
      '单元格左上角带小绿三角、数字靠左站，往往说明它被当成文本。求和会把它漏掉，先统一转成数字格式。',
    category: 'Excel 表格',
    tags: ['数字', '常见错误'],
  },
  {
    id: 'K020',
    title: '打印前设好打印区域',
    source: '《Excel 常用功能手册》',
    section: '第 5 章 打印与导出',
    snippet:
      '框住要打的那块，设成一页宽，并让表头每页重复。不然一张表会被切成好几页，第二页没有列名。',
    category: 'Excel 表格',
    tags: ['打印'],
  },

  // ── PPT 演示 ───────────────────────────────────────────────
  {
    id: 'K021',
    title: '一页只讲一件事',
    source: '《演示文稿制作指南》',
    section: '第 1 章 先想清楚再动手',
    snippet: '一页塞三个观点，听众一个也记不住。讲不完就拆成两页，页数多一点没关系。',
    category: 'PPT 演示',
    tags: ['结构'],
  },
  {
    id: 'K022',
    title: '标题写结论，不写章节名',
    source: '《演示文稿制作指南》',
    section: '第 1 章 先想清楚再动手',
    snippet:
      '把「三季度情况」改成「三季度收入增长 12%」，听众扫一眼就知道这页要说什么。章节名留给目录页。',
    category: 'PPT 演示',
    tags: ['标题'],
  },
  {
    id: 'K023',
    title: '投影上的字别太小',
    source: '《演示文稿制作指南》',
    section: '第 2 章 让后排也看得清',
    snippet: '正文一般不小于 24 号，标题更大。字小说明内容太多，该删的不是字号问题。',
    category: 'PPT 演示',
    tags: ['字号'],
  },
  {
    id: 'K024',
    title: '能用图说清的，就别写一段字',
    source: '《演示文稿制作指南》',
    section: '第 2 章 让后排也看得清',
    snippet: '趋势用线、比较用柱、流程用箭头。整页密密麻麻的文字，听众只会低头读字，没人听你讲。',
    category: 'PPT 演示',
    tags: ['图示'],
  },
  {
    id: 'K025',
    title: '配色不超过三种',
    source: '《演示文稿制作指南》',
    section: '第 3 章 统一观感',
    snippet: '定一个主色、一个强调色，其余用黑白灰。颜色一多，重点反而没了。',
    category: 'PPT 演示',
    tags: ['配色'],
  },
  {
    id: 'K026',
    title: '讲稿放备注，不要放幻灯片',
    source: '《演示文稿制作指南》',
    section: '第 3 章 统一观感',
    snippet: '要说的细节写进备注区，投屏时只留要点。这样既不会忘词，也不会把页面撑满。',
    category: 'PPT 演示',
    tags: ['讲稿'],
  },
  {
    id: 'K027',
    title: '用母版统一每页的位置',
    source: '《演示文稿制作指南》',
    section: '第 3 章 统一观感',
    snippet:
      '标题、页脚、校徽放在母版里定一次，全篇自动一致。逐页拖来拖去，投影上一眼就能看出歪了。',
    category: 'PPT 演示',
    tags: ['母版'],
  },

  // ── PDF 与扫描 ─────────────────────────────────────────────
  {
    id: 'K028',
    title: '定稿分发用 PDF',
    source: '《PDF 与扫描件处理》',
    section: '第 1 章 什么时候用 PDF',
    snippet:
      'PDF 在别人电脑上不会跑版，适合定稿、盖章件和对外发送。交论文、交材料前，先确认对方要 PDF 还是 Word。',
    category: 'PDF 与扫描',
    tags: ['格式'],
  },
  {
    id: 'K029',
    title: '可编辑的原文件一定留一份',
    source: '《PDF 与扫描件处理》',
    section: '第 1 章 什么时候用 PDF',
    snippet:
      '转成 PDF 就不好改字了。发出去之后再要改动，全靠那份原始 Word / Excel，别只留导出的那一份。',
    category: 'PDF 与扫描',
    tags: ['留档'],
  },
  {
    id: 'K030',
    title: '扫描歪了先转正再识别',
    source: '《PDF 与扫描件处理》',
    section: '第 2 章 识别前的准备',
    snippet: '把歪斜、倒置的页面转正，去掉黑边，识别出来的字才准。原图歪着直接识别，容易整行串行。',
    category: 'PDF 与扫描',
    tags: ['扫描'],
  },
  {
    id: 'K031',
    title: '识别出来的文字要人工过一遍',
    source: '《PDF 与扫描件处理》',
    section: '第 2 章 识别前的准备',
    snippet:
      '形状相近的字、数字和标点最容易错。金额、日期、人名和参考文献这些地方，务必对着原图核一次。',
    category: 'PDF 与扫描',
    tags: ['核对'],
  },
  {
    id: 'K032',
    title: '盖了章的页面别压太狠',
    source: '《PDF 与扫描件处理》',
    section: '第 3 章 压缩与合并',
    snippet: '为了发邮件把文件压得过小，红章和手写签名会糊成一片。有章的页保留清晰度，其余页再压。',
    category: 'PDF 与扫描',
    tags: ['压缩'],
  },
  {
    id: 'K033',
    title: '合并前先检查页序',
    source: '《PDF 与扫描件处理》',
    section: '第 3 章 压缩与合并',
    snippet: '几份文件合成一份后，从头翻一遍顺序和缺页。交上去再发现少一页，就得整份重交。',
    category: 'PDF 与扫描',
    tags: ['合并'],
  },
  {
    id: 'K034',
    title: '对外发之前看一眼权限',
    source: '《PDF 与扫描件处理》',
    section: '第 3 章 压缩与合并',
    snippet:
      '含个人信息或内部内容的 PDF，确认收件人再发，必要时加打开密码。发出去的链接很难收回来。',
    category: 'PDF 与扫描',
    tags: ['权限'],
  },

  // ── 公文与汇报 ─────────────────────────────────────────────
  {
    id: 'K035',
    title: '通知、通报、报告别混用',
    source: '《公文写作一本通》',
    section: '第 1 章 先选对文种',
    snippet:
      '通知是「要你去做某事」，通报是「告诉你发生了什么事」，报告是「向上级说明情况」。选错文种，收件人不知道该不该行动。',
    category: '公文与汇报',
    tags: ['文种', '入门'],
  },
  {
    id: 'K036',
    title: '请示一份只说一件事',
    source: '《公文写作一本通》',
    section: '第 1 章 先选对文种',
    snippet:
      '一份请示只请一件事，方便对方批复。把几件不相干的事捆在一起，任何一件卡住，整份都批不下来。',
    category: '公文与汇报',
    tags: ['请示'],
  },
  {
    id: 'K037',
    title: '层次序号按规矩排',
    source: '《公文写作一本通》',
    section: '第 2 章 正文怎么展开',
    snippet: '常用顺序是「一、」「（一）」「1.」「（1）」，一层套一层，不要跳级，也不要混着用。',
    category: '公文与汇报',
    tags: ['编号', '规范'],
  },
  {
    id: 'K038',
    title: '附件要在正文里点名',
    source: '《公文写作一本通》',
    section: '第 3 章 落款与附件',
    snippet:
      '正文末尾写清「附件：1. ……」，并和后面实际附上的文件对得上。只把文件丢在后面不提，很容易被漏看。',
    category: '公文与汇报',
    tags: ['附件'],
  },
  {
    id: 'K039',
    title: '落款和日期别漏',
    source: '《公文写作一本通》',
    section: '第 3 章 落款与附件',
    snippet: '末尾写清发文单位与成文日期。日期一般写全年月日，别只写「十月」或「近日」。',
    category: '公文与汇报',
    tags: ['落款'],
  },
  {
    id: 'K040',
    title: '纪要写结论，不写流水账',
    source: '《会议与纪要实务》',
    section: '第 1 章 纪要记什么',
    snippet: '谁先发言、谁插了句话，都不用记。要记的是定了什么、谁去做、什么时候完成。',
    category: '公文与汇报',
    tags: ['会议'],
  },
  {
    id: 'K041',
    title: '每条待办都要带人和时间',
    source: '《会议与纪要实务》',
    section: '第 1 章 纪要记什么',
    snippet:
      '写「张三 10 月 15 日前提交预算表」，别写「尽快落实」。没有人和日期的事项，基本不会有人认领。',
    category: '公文与汇报',
    tags: ['待办'],
  },
  {
    id: 'K042',
    title: '有分歧就如实记下来',
    source: '《会议与纪要实务》',
    section: '第 2 章 有争议时怎么记',
    snippet:
      '没达成一致的事项，写清各方意见和暂缓原因，不要硬写成「一致同意」。下次开会全靠这一笔。',
    category: '公文与汇报',
    tags: ['分歧'],
  },
  {
    id: 'K043',
    title: '汇报先说结果，再说过程',
    source: '《工作汇报与周报》',
    section: '第 1 章 让人一眼看懂',
    snippet:
      '开头一句给结论：「本周三项任务，两项完成，一项延后」。细节往后放，忙的人只看前三行也够。',
    category: '公文与汇报',
    tags: ['周报'],
  },
  {
    id: 'K044',
    title: '用数字代替形容词',
    source: '《工作汇报与周报》',
    section: '第 1 章 让人一眼看懂',
    snippet:
      '写「处理 32 单，平均 1.5 小时」，别写「进展顺利、效率提升」。形容词没法核对，数字可以。',
    category: '公文与汇报',
    tags: ['周报'],
  },

  // ── 校对与规范 ─────────────────────────────────────────────
  {
    id: 'K045',
    title: '数字和单位之间留个空格',
    source: '《校对与错别字防范》',
    section: '第 1 章 容易忽略的小地方',
    snippet: '写「5 万元」「3 小时」，别连成一坨。中文和英文、数字混排时，两边各留一个空格更好读。',
    category: '校对与规范',
    tags: ['排版'],
  },
  {
    id: 'K046',
    title: '中文正文用中文标点',
    source: '《校对与错别字防范》',
    section: '第 1 章 容易忽略的小地方',
    snippet: '逗号、句号、括号用全角，整段里别中英标点混着来。引号也一样，前后要配对。',
    category: '校对与规范',
    tags: ['标点'],
  },
  {
    id: 'K047',
    title: '同音字要看上下文，别整篇替换',
    source: '《校对与错别字防范》',
    section: '第 2 章 改错别改出新错',
    snippet:
      '「制定」和「制订」、「权利」和「权力」意思不同。按词全篇替换，往往把本来对的地方也改坏了。',
    category: '校对与规范',
    tags: ['错别字'],
  },
  {
    id: 'K048',
    title: '金额、日期、人名重点核',
    source: '《校对与错别字防范》',
    section: '第 2 章 改错别改出新错',
    snippet: '这几类错一个字，后果比错别字大得多。定稿前单独把它们从头到尾对一遍原文。',
    category: '校对与规范',
    tags: ['核对'],
  },
  {
    id: 'K049',
    title: '出声读一遍最容易发现病句',
    source: '《校对与错别字防范》',
    section: '第 3 章 定稿前',
    snippet: '眼睛会自动补上漏掉的字，嘴不会。读着别扭、喘不过气的地方，多半就是长句或缺字。',
    category: '校对与规范',
    tags: ['通读'],
  },
  {
    id: 'K050',
    title: '文件名带上日期和版本',
    source: '《文档管理与归档》',
    section: '第 1 章 起个好名字',
    snippet:
      '比如「论文初稿_2026-10_v2」。别用「最终版」「最终版2」「真的最终版」，过两周自己都分不清。',
    category: '校对与规范',
    tags: ['命名'],
  },
  {
    id: 'K051',
    title: '定稿单独标出来',
    source: '《文档管理与归档》',
    section: '第 2 章 版本',
    snippet: '过程稿留在子文件夹，主目录只放一份明确的定稿。交材料时不用猜哪一份能对上。',
    category: '校对与规范',
    tags: ['归档'],
  },

  // ── 论文格式 ───────────────────────────────────────────────
  {
    id: 'K052',
    title: '动笔前先拿到学校的格式要求',
    source: '《论文格式与排版手册》',
    section: '第 1 章 先定规矩',
    snippet:
      '字体字号、行距、页边距、封面、装订顺序，各学校要求不一样。先找学院发的那份要求或模板，别照着网上的通用版排。',
    category: '论文格式',
    tags: ['总纲', '入门'],
  },
  {
    id: 'K053',
    title: '封面按模板逐项填',
    source: '《论文格式与排版手册》',
    section: '第 2 章 封面与前置页',
    snippet:
      '题目、姓名、学号、导师、学院、日期，一项项对着模板填。别自己调封面字号或换行，模板的位置通常是定死的。',
    category: '论文格式',
    tags: ['封面'],
  },
  {
    id: 'K054',
    title: '摘要写什么',
    source: '《论文格式与排版手册》',
    section: '第 2 章 封面与前置页',
    snippet:
      '几句话交代研究什么、怎么做的、得到什么结论，别写成章节介绍。摘要要能单独读，不依赖正文。',
    category: '论文格式',
    tags: ['摘要'],
  },
  {
    id: 'K055',
    title: '关键词别当成标题堆',
    source: '《论文格式与排版手册》',
    section: '第 2 章 封面与前置页',
    snippet:
      '挑三到五个真正能概括研究内容的词，用分号隔开。别把「研究」「分析」这种放之四海皆准的词放进去。',
    category: '论文格式',
    tags: ['关键词'],
  },
  {
    id: 'K056',
    title: '目录自动生成，别手打',
    source: '《论文格式与排版手册》',
    section: '第 2 章 封面与前置页',
    snippet: '给各级标题套上标题样式，再插入自动目录。正文一改就更新一次，页码永远对得上。',
    category: '论文格式',
    tags: ['目录'],
  },
  {
    id: 'K057',
    title: '正文字体字号全篇统一',
    source: '《论文格式与排版手册》',
    section: '第 3 章 正文版式',
    snippet:
      '中文正文、英文、数字各用哪一种字体，按学校要求一次设好并存在样式里。最忌讳的是从别处复制粘贴，把三四套字体混进同一篇。',
    category: '论文格式',
    tags: ['字体'],
  },
  {
    id: 'K058',
    title: '行距与段距按要求一次设好',
    source: '《论文格式与排版手册》',
    section: '第 3 章 正文版式',
    snippet:
      '常见的是固定行距或 1.5 倍，段前段后留多少也有规定。用段落设置统一改，别靠敲空行把版面撑开。',
    category: '论文格式',
    tags: ['行距'],
  },
  {
    id: 'K059',
    title: '页边距和装订线',
    source: '《论文格式与排版手册》',
    section: '第 3 章 正文版式',
    snippet:
      '需要打印装订的论文，靠书脊那一侧要多留一点。只按屏幕好看来设，装订后靠里的字会被吃掉。',
    category: '论文格式',
    tags: ['页边距'],
  },
  {
    id: 'K060',
    title: '页码从哪一页开始',
    source: '《论文格式与排版手册》',
    section: '第 3 章 正文版式',
    snippet:
      '封面、声明、目录常常用罗马数字或不编页，正文从第一页起用阿拉伯数字。用分节符分开设，别在封面手打页码。',
    category: '论文格式',
    tags: ['页码', '分节'],
  },
  {
    id: 'K061',
    title: '章节编号一层套一层',
    source: '《论文格式与排版手册》',
    section: '第 4 章 编号与图表',
    snippet:
      '常用的写法是「第 1 章」「1.1」「1.1.1」，同级保持一致。用自动编号，插入或删掉一节时后面会跟着改。',
    category: '论文格式',
    tags: ['编号'],
  },
  {
    id: 'K062',
    title: '图题在下、表题在上',
    source: '《论文格式与排版手册》',
    section: '第 4 章 编号与图表',
    snippet:
      '图片说明写在图下面，表格名称写在表上面，编号按章排（图 2-1、表 3-2）。正文里要提到「如图 2-1 所示」。',
    category: '论文格式',
    tags: ['图表'],
  },
  {
    id: 'K063',
    title: '公式居中、编号靠右',
    source: '《论文格式与排版手册》',
    section: '第 4 章 编号与图表',
    snippet:
      '单独成行的公式居中，编号放右端并加括号，按章编号。正文里引用编号要写全，别只写「上式」。',
    category: '论文格式',
    tags: ['公式'],
  },
  {
    id: 'K064',
    title: '量和单位用标准写法',
    source: '《论文格式与排版手册》',
    section: '第 4 章 编号与图表',
    snippet:
      '单位符号用国标写法，大小写别混（kg 不是 KG）；数值和单位之间留空格。全篇保持一致，别一会儿中文一会儿符号。',
    category: '论文格式',
    tags: ['单位'],
  },
  {
    id: 'K065',
    title: '附录放什么',
    source: '《论文格式与排版手册》',
    section: '第 5 章 结尾部分',
    snippet:
      '问卷、原始数据、大段代码、补充图表放附录，正文只留必要的说明。附录也要编号，并在正文里提到它。',
    category: '论文格式',
    tags: ['附录'],
  },

  // ── 论文模板与参考文献 ─────────────────────────────────────
  {
    id: 'K066',
    title: '学校模板优先，别自己另起一套',
    source: '《论文模板与参考文献》',
    section: '第 1 章 模板怎么用',
    snippet:
      '交上去的是按学校模板排的版，不是你自己觉得好看的版。哪怕网上模板更漂亮，也以学院发的那份为准。',
    category: '论文模板',
    tags: ['模板', '总纲'],
  },
  {
    id: 'K067',
    title: '套模板时别改结构',
    source: '《论文模板与参考文献》',
    section: '第 1 章 模板怎么用',
    snippet:
      '把内容填进模板已有的位置，不要删掉声明页、不要挪封面、不要改章节顺序。缺哪一块先问清楚，别自己删。',
    category: '论文模板',
    tags: ['模板'],
  },
  {
    id: 'K068',
    title: '用样式套模板最省事',
    source: '《论文模板与参考文献》',
    section: '第 1 章 模板怎么用',
    snippet:
      '把正文粘进来后，统一套用模板里的「正文」「标题 1」「标题 2」样式。逐段刷格式，改到后面必然漏。',
    category: '论文模板',
    tags: ['样式'],
  },
  {
    id: 'K069',
    title: '开题报告写清要做什么、怎么做',
    source: '《论文模板与参考文献》',
    section: '第 2 章 过程中要交的材料',
    snippet:
      '背景和意义点到为止，重点写研究问题、方法、进度安排和已读的文献。让老师看完知道你打算怎么做完。',
    category: '论文模板',
    tags: ['开题'],
  },
  {
    id: 'K070',
    title: '参考文献按学校要求的格式排',
    source: '《论文模板与参考文献》',
    section: '第 3 章 参考文献',
    snippet:
      '常见的是国标 GB/T 7714，作者、题名、刊物、年份、卷期页码的顺序和标点都有规定。先确认学校要哪种，再逐条对齐。',
    category: '论文模板',
    tags: ['参考文献'],
  },
  {
    id: 'K071',
    title: '文中引用和文末列表要对得上',
    source: '《论文模板与参考文献》',
    section: '第 3 章 参考文献',
    snippet:
      '正文里标过的每一条，文末都要有；文末列着的，正文里也要真的引过。定稿前顺着编号核一遍。',
    category: '论文模板',
    tags: ['引用'],
  },
  {
    id: 'K072',
    title: '直接引用要写页码',
    source: '《论文模板与参考文献》',
    section: '第 3 章 参考文献',
    snippet:
      '照抄原话必须加引号并给出出处页码，转述别人的观点也要标明来源。只列在文末不注明位置，容易被判引用不清。',
    category: '论文模板',
    tags: ['引用'],
  },
  {
    id: 'K073',
    title: '文献别凑数',
    source: '《论文模板与参考文献》',
    section: '第 3 章 参考文献',
    snippet: '挑真正读过、和题目相关的，近几年的新成果也要有。堆一堆没看过的文献，答辩一问就露馅。',
    category: '论文模板',
    tags: ['参考文献'],
  },
  {
    id: 'K074',
    title: '查重前先自查一遍',
    source: '《论文模板与参考文献》',
    section: '第 4 章 定稿与答辩',
    snippet:
      '大段照搬、自己以前交过的作业、没标出处的图表最容易出问题。提交前先把这些地方改成规范引用。',
    category: '论文模板',
    tags: ['查重'],
  },
  {
    id: 'K075',
    title: '降重不是换同义词',
    source: '《论文模板与参考文献》',
    section: '第 4 章 定稿与答辩',
    snippet:
      '把每个词换成近义词，句子还是别人的，读起来还别扭。真正该做的是用自己的话重述，并老实标出来源。',
    category: '论文模板',
    tags: ['降重'],
  },
  {
    id: 'K076',
    title: '答辩 PPT 讲结论，别念论文',
    source: '《论文模板与参考文献》',
    section: '第 4 章 定稿与答辩',
    snippet:
      '十几页讲清为什么做、怎么做的、得到什么、还有什么不足。把论文原文整段贴上去，台下没人看得完。',
    category: '论文模板',
    tags: ['答辩'],
  },
  {
    id: 'K077',
    title: '终稿导出 PDF，也留可编辑版',
    source: '《论文模板与参考文献》',
    section: '第 4 章 定稿与答辩',
    snippet:
      '提交前导出 PDF 检查有没有跑版、缺字、目录页码错位；同时留一份 Word 原稿，答辩后要改才来得及。',
    category: '论文模板',
    tags: ['终稿'],
  },
];

/** 领域 → 条数，页面右侧「按领域翻」用。 */
export const CATEGORY_STATS: readonly { name: string; count: number }[] = (() => {
  const counts = new Map<string, number>();
  for (const item of STATIC_PASSAGES) {
    counts.set(item.category, (counts.get(item.category) ?? 0) + 1);
  }
  return [...counts].map(([name, count]) => ({ name, count }));
})();

export const TOTAL_PASSAGES = STATIC_PASSAGES.length;

function countOccurrences(haystack: string, needle: string): number {
  let count = 0;
  let from = 0;
  while (count < 8) {
    const at = haystack.indexOf(needle, from);
    if (at < 0) break;
    count += 1;
    from = at + needle.length;
  }
  return count;
}

/** 浏览顺序：每个领域轮着取一条，一批里能同时看到好几个领域。 */
function browseOrder(): StaticHit[] {
  const groups = new Map<string, StaticPassage[]>();
  for (const item of STATIC_PASSAGES) {
    const list = groups.get(item.category) ?? [];
    list.push(item);
    groups.set(item.category, list);
  }
  const buckets = [...groups.values()];
  const ordered: StaticHit[] = [];
  const longest = Math.max(...buckets.map((bucket) => bucket.length));
  for (let row = 0; row < longest; row += 1) {
    for (const bucket of buckets) {
      const item = bucket[row];
      if (item) ordered.push({ ...item, score: null });
    }
  }
  return ordered;
}

const BROWSE_ORDER = browseOrder();

/**
 * 纯本地检索：不联网、不读后端、不写状态。
 *
 * 三条硬规则：
 * - 浏览态一批只给 BROWSE_PAGE_SIZE 条，靠 page 换批，不无限往下铺；
 * - 检索态最多给 SEARCH_LIMIT 条，命中再多也只显示前几条；
 * - 传 category 时只在该领域里找，不做跨领域模糊匹配。
 *
 * 返回形状和正式接口一致，后期换成远端检索时页面不用重写。
 */
export function searchStatic(
  query: string,
  category: string | null = null,
  page = 0,
): StaticSearchResult {
  const pool = category
    ? STATIC_PASSAGES.filter((item) => item.category === category)
    : STATIC_PASSAGES;
  const q = query.trim().toLowerCase();

  if (!q) {
    const all = category ? pool.map((item) => ({ ...item, score: null })) : BROWSE_ORDER;
    const pageCount = Math.max(1, Math.ceil(all.length / BROWSE_PAGE_SIZE));
    const safePage = ((page % pageCount) + pageCount) % pageCount;
    return {
      hits: all.slice(safePage * BROWSE_PAGE_SIZE, (safePage + 1) * BROWSE_PAGE_SIZE),
      total: TOTAL_PASSAGES,
      level: 'browsing',
      matched: all.length,
      page: safePage,
      pageCount,
    };
  }

  const terms = q.split(/\s+/).filter(Boolean);
  const scored: StaticHit[] = [];
  for (const item of pool) {
    const haystack = [
      item.title,
      item.source,
      item.section,
      item.snippet,
      item.category,
      item.tags.join(' '),
    ]
      .join(' ')
      .toLowerCase();
    let matched = 0;
    let occurrences = 0;
    for (const term of terms) {
      const n = countOccurrences(haystack, term);
      if (n > 0) matched += 1;
      occurrences += n;
    }
    if (matched === 0) continue;
    const coverage = matched / terms.length;
    const density = Math.min(1, occurrences / 8);
    scored.push({ ...item, score: Math.round((0.65 * coverage + 0.35 * density) * 100) / 100 });
  }

  scored.sort((a, b) => (b.score ?? 0) - (a.score ?? 0) || a.id.localeCompare(b.id));
  const level = scored.length >= 3 ? 'strong' : scored.length > 0 ? 'weak' : 'none';
  return {
    hits: scored.slice(0, SEARCH_LIMIT),
    total: TOTAL_PASSAGES,
    level,
    matched: scored.length,
    page: 0,
    pageCount: 1,
  };
}
