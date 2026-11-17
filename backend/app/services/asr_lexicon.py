"""asr_lexicon.py —— 会议转写的热词表（唯一真相）。

**为什么需要一份词表。** `base` 档 whisper 听得清「yen shou」，但「验收 / 厌收 /
验受」里落哪个字，靠的是它那点浅薄的中文语言模型。把「这些词在这个人的工作里
天天出现」提前告诉解码器，模型在选字时就会往这些写法上偏 —— 这是官方推荐的做法
（`initial_prompt` 热词），也是**真正按语境判断同音字**的地方：判断由模型在解码
时完成，不是事后拿规则硬改。

**排序按用户自己的材料。** 通用表只解决冷启动。做交付的人天天说「回款、验收、
里程碑」，做研发的人天天说「迭代、联调、灰度」——`rank()` 拿用户已有素材统计每个
词的出现次数，出现得多的排到最前面（也就是 prompt 里最靠前的位置）。用 `str.count`
就够了，不需要分词，也不需要新依赖。

**只放词，不放规则。** 这里不写「见到 X 就改成 Y」这种替换规则：中文没有词边界，
「讨厌收到」里就含着「厌收」，按规则改必然误伤。同音字的最终取舍交给解码期的
语言模型；事后纠错只在有把握的场合做（见 `media_service._proofread`）。

**怎么加词（维护指南）。**

- 只收**名词性、领域性**的词（「验收」「回款」「里程碑」）。「这个」「然后」这类
  口语词进了 prompt 只会挤占预算，对选字没有帮助。
- 一个词只在表里出现一次；同一概念的不同写法（「交付」/「交付物」）可以都收，
  它们是不同的词，统计时各算各的。
- 新增按「用户会怎么说」来写，不按行业分类写：`HOTWORDS` 的顺序就是没有用户
  语料时的默认优先级，越靠前越通用。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence

#: 会议 / 办公场景的高频词。顺序即默认优先级（没有用户语料时按这个顺序取）。
HOTWORDS: tuple[str, ...] = (
    # ---- 项目与交付 ----
    "交付",
    "验收",
    "里程碑",
    "排期",
    "立项",
    "复盘",
    "对齐",
    "推进",
    "落地",
    "闭环",
    "迭代",
    "联调",
    "灰度",
    "上线",
    "回滚",
    "需求",
    "评审",
    "方案",
    "节点",
    "进度",
    "风险",
    "阻塞",
    "依赖",
    "范围",
    "变更",
    "延期",
    "交付物",
    # ---- 财务与合同 ----
    "回款",
    "合同",
    "报价",
    "预算",
    "成本",
    "毛利",
    "结算",
    "对账",
    "台账",
    "开票",
    "发票",
    "尾款",
    "付款",
    "履约",
    "违约",
    "应收账款",
    "现金流",
    "核算",
    "报销",
    "报价单",
    # ---- 客户与销售 ----
    "客户",
    "线索",
    "商机",
    "转化率",
    "留存",
    "拉新",
    "复购",
    "续费",
    "签约",
    "拜访",
    "投标",
    "中标",
    "竞标",
    "客单价",
    "渠道",
    "代理商",
    "续约",
    "满意度",
    # ---- 数据与指标 ----
    "同比",
    "环比",
    "达成率",
    "完成率",
    "渗透率",
    "留存率",
    "活跃度",
    "目标值",
    "基线",
    "口径",
    "漏斗",
    "增量",
    "存量",
    # ---- 组织与协作 ----
    "汇报",
    "周报",
    "月报",
    "述职",
    "晋升",
    "招聘",
    "面试",
    "编制",
    "绩效",
    "培训",
    "协同",
    "跨部门",
    "负责人",
    "对接人",
    "排班",
    "交接",
    # ---- 技术与运维 ----
    "接口",
    "埋点",
    "压测",
    "预警",
    "监控",
    "故障",
    "运维",
    "扩容",
    "回归",
    "测试用例",
    "缺陷",
    "版本",
    "发版",
    # ---- 会议本身 ----
    "议题",
    "结论",
    "待办",
    "跟进",
    "同步",
    "确认",
    "共识",
    "决议",
)

#: 每个词在 `HOTWORDS` 里的位置，排序时用来打破平局（不重复算 index）。
_ORDER: dict[str, int] = {word: index for index, word in enumerate(HOTWORDS)}

#: prompt 里热词部分的总长上限（字符）。
#:
#: whisper 的 prompt 预算只有 224 token，且它把 prompt 当「前文」续写 ——
#: 塞得越长，第一段把词表复读出来的概率越高。一百字左右能放十二三个词，
#: 足够覆盖一场会议的主题，又不至于喧宾夺主。
MAX_PROMPT_CHARS = 110

#: 专名（产品名 / 型号 / 内部编号）的识别式。
#:
#: 只认「英数混排」：`DHT22`、`SSD1306`、`ESP32-DevKit`、`OPS-20261109-0731`。
#: 中文专名认不出来 —— 没有分词就分不清「温湿度采集」和「项目进度」哪个是名字，
#: 硬猜只会把普通词塞进 prompt 挤掉预算，所以中文的留给 `ASR_HOTWORDS` 手填。
_PROPER_NOUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-+.][A-Za-z0-9]+)*")

#: 抓到这些后缀说明匹配的是文件名（`W45.txt`），不是产品名。
_FILE_SUFFIXES = frozenset(
    {
        "txt",
        "md",
        "doc",
        "docx",
        "pdf",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "csv",
        "json",
        "html",
        "png",
        "jpg",
        "jpeg",
        "wav",
        "mp3",
        "mp4",
        "mov",
    }
)

#: 英文里的功能词。它们也「含大写」（句首）或反复出现，但对选字毫无帮助。
_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "these",
        "those",
        "you",
        "your",
        "are",
        "was",
        "were",
        "will",
        "would",
        "shall",
        "should",
        "have",
        "has",
        "had",
        "not",
        "but",
        "all",
        "any",
        "can",
        "could",
        "may",
        "might",
        "must",
        "our",
        "their",
        "its",
        "it",
        "is",
        "be",
        "been",
        "being",
        "of",
        "to",
        "in",
        "on",
        "at",
        "as",
        "by",
        "or",
        "if",
        "then",
        "than",
        "so",
        "we",
        "they",
        "he",
        "she",
        "use",
        "used",
        "using",
        "make",
        "made",
        "get",
        "got",
        "new",
        "old",
        "see",
        "also",
        "more",
        "most",
        "other",
        "some",
        "such",
    }
)

#: 专名里单个词的长度上限。再长基本是路径或一长串编号，念都念不出来。
_MAX_PROPER_LEN = 20

#: 会议纪要里明确列名字的字段。这类字段的格式在同一个人的文档里很稳定，
#: 是「这场会谁在场」最可靠的来源 —— 比统计「XX：」靠谱得多（后者会把
#: 「来源：」「说明：」也算进去）。
_ATTENDEE_LABELS = (
    "参会人员",
    "参会人",
    "参会",
    "参加人员",
    "参加人",
    "出席人员",
    "出席人",
    "出席",
    "与会人员",
    "与会",
    "列席人员",
    "列席",
    "记录人",
    "主持人",
    "汇报人",
)
#: 长词优先，否则 `参会` 会先把 `参会人员` 吃掉一半
_LABEL_PATTERN = "|".join(sorted(_ATTENDEE_LABELS, key=len, reverse=True))
_ATTENDEE_FIELD = re.compile(
    # 捕获到「下一个字段名 + 冒号」为止：纪要常写成
    # `记录人：王芳参会：张伟、李娜`，中间连空格都没有
    rf"(?:{_LABEL_PATTERN})[：:]\s*([^\n]*?)(?=\s*(?:{_LABEL_PATTERN})[：:]|$)",
    re.MULTILINE,
)

#: 转写稿里的说话人：`[00:12] 张伟：……`。有时间戳这个上下文，误判很少。
_SPEAKER_LINE = re.compile(r"(?m)^\[\d{1,2}:\d{2}(?::\d{2})?\]\s*([\u4e00-\u9fff]{2,4})[：:]")

#: 字段里的多个名字：顿号、逗号、分号、空格、残留的冒号都可能用。
_NAME_SPLIT = re.compile(r"[、,，;；/|\s：:]+")

#: 常见中文姓氏。**这一条是必须的**：不按姓氏筛，「参会：销售部、财务部」会把
#: 部门名当成人名塞进 prompt。宁可漏（少见姓），也不要错到把「研发」当人。
_SURNAMES = frozenset(
    "王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董"
    "袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟"
    "熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施文"
    "牛樊葛邢安齐易乔伍庞颜倪庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符"
    "舒阮柯纪梅童凌毕单季裴霍涂成苗谷盛曲翁冉骆蓝路游辛靳管柴蒙鲍华喻祁蒲房"
    "滕屈饶解牟艾尤阳时穆农司卓古吉缪简车项连芦麦褚娄窦戚岑景党宫费卜冷晏席"
    "卫米柏宗瞿桂全佟应臧闵苟邬边卞姬师和仇栾隋商刁沙荣巫寇桑郎甄丛仲虞敖巩"
    "明佘池查麻苑迟邝"
)

#: 姓氏对得上、但显然不是人的词（「时间」「地点」这类字段名最容易撞车）。
_NOT_NAMES = frozenset(
    {
        "时间",
        "地点",
        "议题",
        "主题",
        "会议",
        "部门",
        "全体",
        "全员",
        "各位",
        "人员",
        "同事",
        "大家",
        "客户",
        "领导",
        "高层",
        "团队",
        "项目",
        "费用",
        "金额",
        "问题",
        "结果",
        "内容",
        "备注",
        "附件",
        "纪要",
        "议程",
        "名单",
        "单位",
        "组织",
        "集团",
        "公司",
        "中心",
        "方案",
        "计划",
        "进度",
        "风险",
        "需求",
        "质量",
        "流程",
        "制度",
        "规则",
        "标准",
        "数据",
        "报表",
        "指标",
        "目标",
        "任务",
        "上午",
        "下午",
        "晚上",
        "今天",
        "明天",
        "本周",
        "下周",
        "上月",
        "本月",
        "季度",
        "年度",
    }
)


def custom_words(raw: str) -> list[str]:
    """解析设置里的自定义热词（英文逗号 / 中文逗号 / 顿号 / 空白都当分隔符）。"""
    for separator in ("，", "、", "；", ";", "\n", "\t", " "):
        raw = raw.replace(separator, ",")
    words: list[str] = []
    for item in raw.split(","):
        word = item.strip()
        if word and word not in words:
            words.append(word)
    return words


def proper_nouns(corpus: str, limit: int = 6, *, max_chars: int = 40) -> list[str]:
    """从用户素材里捞出产品名 / 型号 / 内部编号。

    这一类词是转写错得最离谱的：`DHT22` 会被写成「DHT 二二」「D H T 二十二」，
    `OPS-20261109-0731` 干脆变成一串中文。它们**不能靠手填维护**——型号和编号
    一直在变，靠人记一定会漏。所以从素材里统计：出现过两次以上的英数串才算数，
    一次的多半是笔误或路径碎片。

    **为什么只认英数。** 中文没有词边界，「温湿度采集」和「项目进度」在字面上
    是同一种东西，抽出来就是普通词，塞进 prompt 只会挤掉真正有用的预算。
    中文人名、内部简称留给设置里的手填词。

    返回按出现次数降序；同一写法的大小写变体（`Dht22` / `DHT22`）合并，取出现
    最多的那个写法 —— whisper 会照着 prompt 里的样子输出，写对一次能省掉一整篇
    的错字。
    """
    if limit <= 0 or not corpus:
        return []

    spelled: Counter[str] = Counter()
    for match in _PROPER_NOUN_RE.finditer(corpus):
        word = match.group(0).rstrip(".")
        # 长度门槛顺带滤掉 `MB`、`NC`、`V3` 这类两字母缩写：会议里没人念，占位置
        if len(word) < 3 or len(word) > _MAX_PROPER_LEN:
            continue
        if word.rsplit(".", 1)[-1].lower() in _FILE_SUFFIXES:
            continue  # `W45.txt` 是文件名
        if word.lower() in _STOPWORDS:
            continue
        # 纯数字开头的不可能（正则要求字母开头）；剩下要求「有大写或数字」，
        # 否则 hello / project 这种人人在用的英文词也会进来
        if not any(char.isdigit() or char.isupper() for char in word):
            continue
        spelled[word] += 1

    # 大小写归一：`Esp32` 5 次 + `ESP32` 3 次 → `Esp32` 记 8 次（取出现最多的写法）
    merged: dict[str, tuple[int, str]] = {}
    for word, count in spelled.items():
        key = word.casefold()
        total, best = merged.get(key, (0, word))
        total += count
        if count > spelled.get(best, 0):
            best = word
        merged[key] = (total, best)

    picked: list[str] = []
    used = 0
    ranked = [(count, word) for count, word in merged.values() if count >= 2]
    # 全大写、纯字母、五个字母以上的（`NORMAL`、`ALARM`、`OKAY`）多半是代码里的
    # 状态值或常量，不是产品名 —— 它们在素材里出现得很频繁，光按次数排会被顶到
    # 前面，把真正的型号挤掉。降权而不是删除：万一真是个缩写（`REDIS`），还有机会。
    ranked.sort(
        key=lambda pair: (
            bool(len(pair[1]) >= 5 and pair[1].isalpha() and pair[1].isupper()),
            -pair[0],
            len(pair[1]),
        )
    )
    for _count, word in ranked:
        cost = len(word) + (1 if picked else 0)
        if used + cost > max_chars:
            continue  # 太长的编号跳过，别把预算吃光，后面还有通用词要放
        picked.append(word)
        used += cost
        if len(picked) >= limit:
            break
    return picked


def _looks_like_name(word: str) -> bool:
    """两到四个汉字、以常见姓氏开头、又不是字段名 —— 才当成人名。"""
    if not 2 <= len(word) <= 4:
        return False
    if word in _NOT_NAMES:
        return False
    if word[0] not in _SURNAMES:
        return False
    return all("\u4e00" <= char <= "\u9fff" for char in word)


def people(corpus: str, limit: int = 4) -> list[str]:
    """从用户素材里认出「这场会都有谁」。

    人名的正确率最要紧：叫错一次，整篇纪要里每一次出现都是错的。所以只认两种
    **明确**的写法，不做任何猜测式抽取：

    1. 纪要里的名单字段 —— `参会：张伟、李娜`、`记录人：王芳`。字段本身就是声明，
       出现一次就算数。
    2. 转写稿的说话人行 —— `[00:12] 张伟：……`。带时间戳才算，且要出现两次以上。

    两条都要过「姓氏表 + 非字段名」两道筛子。宁可漏掉少见姓的人（他还能靠
    `ASR_HOTWORDS` 手填补上），也不要把「销售部」当成人名写进 prompt。
    """
    if limit <= 0 or not corpus:
        return []

    score: dict[str, int] = {}
    order: list[str] = []

    def note(name: str, weight: int) -> None:
        if name not in score:
            order.append(name)
            score[name] = 0
        score[name] += weight

    for match in _ATTENDEE_FIELD.finditer(corpus):
        for item in _NAME_SPLIT.split(match.group(1)):
            name = item.strip("（）()【】[]「」《》 ")
            if _looks_like_name(name):
                note(name, 2)  # 名单字段出现一次就够

    for match in _SPEAKER_LINE.finditer(corpus):
        name = match.group(1)
        if _looks_like_name(name):
            note(name, 1)  # 说话人行要两次才过线（见下面的 >= 2）

    known = [name for name in order if score[name] >= 2]
    # sorted 是稳定的：分数相同的保持首次出现的先后
    known.sort(key=lambda name: -score[name])
    return known[:limit]


def rank(corpus: str, limit: int = 12) -> list[str]:
    """按用户语料里的出现次数排序，取前 `limit` 个。

    - **没有语料**（刚装好、一篇素材都没有）：退回默认顺序，让第一次转写就有词表可用；
    - **有语料**：只保留在本人的材料里出现过的词。一个词从来没在他的文档里出现过，
      说明不是他的常用词，塞进 prompt 只会给解码器添噪。
    """
    if limit <= 0:
        return []
    if not corpus:
        return list(HOTWORDS[:limit])

    counts = {word: corpus.count(word) for word in HOTWORDS}
    hit = [word for word in HOTWORDS if counts[word]]
    if not hit:
        # 语料里一个都对不上（纯英文材料 / 刚换领域）：别硬塞通用词，交给模型自己判断
        return []
    hit.sort(key=lambda word: (-counts[word], _ORDER[word]))
    return hit[:limit]


def build_prompt(
    base: str, hotwords: Iterable[str] = (), *, max_chars: int = MAX_PROMPT_CHARS
) -> str:
    """把热词接在短提示后面，超预算就截断（宁可少几个词，也不要挤掉提示语）。"""
    budget = max_chars - len(base) - len("常用词：") - 1
    picked: list[str] = []
    used = 0
    for word in hotwords:
        cost = len(word) + (1 if picked else 0)
        if used + cost > budget:
            break
        picked.append(word)
        used += cost
    if not picked:
        return base
    return f"{base}常用词：{'、'.join(picked)}。"


def merge_words(custom: Sequence[str], learned: Sequence[str], limit: int = 12) -> list[str]:
    """用户手填的词排最前（那是他明确说「我叫这个」的），其余按学到的顺序补。"""
    merged: list[str] = []
    for word in list(custom) + list(learned):
        if word and word not in merged:
            merged.append(word)
        if len(merged) >= limit:
            break
    return merged
