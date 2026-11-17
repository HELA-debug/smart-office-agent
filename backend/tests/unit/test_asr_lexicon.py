"""热词表：排序、prompt 拼装、自定义词解析。

这三条都直接影响识别准确率，而且都发生在「调用模型之前」——不加载模型就能验。
"""

from __future__ import annotations

from app.services import asr_lexicon


def test_custom_words_accepts_common_separators():
    """用户在设置里手填的词，逗号全角半角、顿号、空白都得认。"""
    raw = "张伟，李娜、华东区;回款 里程碑\n 张伟 "
    assert asr_lexicon.custom_words(raw) == ["张伟", "李娜", "华东区", "回款", "里程碑"]


def test_rank_without_corpus_falls_back_to_default_order():
    """一篇素材都没有时也要有词表可用，否则第一次转写等于没开这个功能。"""
    words = asr_lexicon.rank("", limit=5)
    assert words == list(asr_lexicon.HOTWORDS[:5])


def test_rank_puts_the_users_own_frequent_words_first():
    """用户材料里「回款」出现得最多，就该排在 prompt 最前面。"""
    corpus = "本周回款情况；回款节点；回款率。另外验收还未完成，验收资料待补。"
    words = asr_lexicon.rank(corpus, limit=5)
    assert words[0] == "回款"
    assert "验收" in words
    # 语料里没出现过的词不该挤进来（避免给解码器添噪）
    assert "招聘" not in words


def test_rank_returns_nothing_when_nothing_matches():
    """纯英文材料里一个中文词都对不上：别硬塞通用词，让模型自己判断。"""
    assert asr_lexicon.rank("hello world, quarterly review", limit=5) == []


def test_build_prompt_keeps_the_instruction_and_respects_budget():
    """词表再长也不能把提示语挤掉——那是模型判断语种与标点的依据。"""
    base = "以下是普通话会议录音。"
    hotwords = [f"很长的词{i}" for i in range(40)]
    prompt = asr_lexicon.build_prompt(base, hotwords)
    assert prompt.startswith(base)
    assert "常用词：" in prompt
    assert len(prompt) <= asr_lexicon.MAX_PROMPT_CHARS
    # 截断是「少放几个词」，不是把最后一个词砍成半截
    assert all(word in prompt for word in prompt.split("常用词：")[1].rstrip("。").split("、"))


def test_build_prompt_without_hotwords_is_the_bare_instruction():
    assert asr_lexicon.build_prompt("以下是普通话会议录音。", []) == "以下是普通话会议录音。"


def test_merge_words_keeps_hand_written_words_in_front():
    """手填的是用户明确说「我叫这个」，必须排在学到的高频词前面。"""
    merged = asr_lexicon.merge_words(["张伟", "华东区"], ["回款", "验收", "张伟"], limit=4)
    assert merged == ["张伟", "华东区", "回款", "验收"]


# --------------------------------------------------------------------------
# 人名：只认明确写法，宁可漏也不认错
# --------------------------------------------------------------------------


def test_people_reads_the_attendee_field():
    """纪要里的名单字段是最可靠的来源，连写的两个字段也要切开。"""
    corpus = "记录人：王芳参会：张伟、李娜、王芳、陈磊"
    assert asr_lexicon.people(corpus) == ["王芳", "张伟", "李娜", "陈磊"]


def test_people_ignores_departments_and_field_names():
    """部门名、「时间」这类字段名撞上姓氏也不能当成人 —— 写错一次整篇都错。"""
    corpus = "参会：销售部、财务部、研发部\n记录人：时间\n主持人：全员"
    assert asr_lexicon.people(corpus) == []


def test_people_needs_two_speaker_lines():
    """转写稿的「张伟：」出现一次可能是噪音，两次以上才当成常驻发言人。"""
    once = "[00:12] 张伟：这段先放着。\n[00:30] 我们继续。"
    assert asr_lexicon.people(once) == []
    twice = "[00:12] 张伟：这段先放着。\n[00:30] 张伟：好，过下一个。"
    assert asr_lexicon.people(twice) == ["张伟"]


# --------------------------------------------------------------------------
# 专名：产品名 / 型号 / 内部编号
# --------------------------------------------------------------------------


def test_proper_nouns_picks_hardware_names():
    """型号是转写错得最离谱的一类：`DHT22` 会被写成「DHT 二二」。"""
    corpus = (
        "传感器 DHT22，显示屏 SSD1306。DHT22 接 GPIO4，ESP32 主控，SSD1306 走 I2C，ESP32 供电。"
    )
    words = asr_lexicon.proper_nouns(corpus, limit=5)
    assert "DHT22" in words
    assert "SSD1306" in words
    assert "ESP32" in words


def test_proper_nouns_skips_filenames_and_plain_english():
    """`W45.txt` 是文件名，`project` 没有大写也没有数字，都不是专名。"""
    corpus = "来源：W45.txt；project 里的 hello world。W45.txt 又提了一次。"
    assert asr_lexicon.proper_nouns(corpus) == []


def test_proper_nouns_needs_two_occurrences():
    """只出现一次的英数串多半是笔误或路径碎片。"""
    assert asr_lexicon.proper_nouns("一次性的 AM2302") == []
    assert "AM2302" in asr_lexicon.proper_nouns("AM2302 出现两次，AM2302 又出现一次")


def test_proper_nouns_merges_case_variants():
    """`Esp32` / `ESP32` 是同一个词，取出现最多的那种写法 —— 模型会照着抄。"""
    corpus = "ESP32 两次，esp32 一次，ESP32 再一次"
    assert asr_lexicon.proper_nouns(corpus) == ["ESP32"]


def test_proper_nouns_demotes_long_all_caps_words():
    """`NORMAL` 是屏幕上的状态值，出现得再频繁也不该把真型号挤掉。"""
    corpus = "OLED OLED OLED NORMAL NORMAL NORMAL NORMAL NORMAL"
    assert asr_lexicon.proper_nouns(corpus, limit=2) == ["OLED", "NORMAL"]
    assert asr_lexicon.proper_nouns(corpus, limit=1) == ["OLED"]
