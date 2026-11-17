"""同音字校对：四道闸（等长 / 原件存在 / 次数上限 / 总条数）一个都不能松。

这个模块会改用户的转写稿，所以测试的重点不是「改得准」，而是「**改错的时候
它也只会换一个词，绝不会动到别的内容**」。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import Settings
from app.services import asr_proofread


class _FakeProvider:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        return SimpleNamespace(text=self.reply)


def _install(monkeypatch, reply: str) -> _FakeProvider:
    provider = _FakeProvider(reply)
    monkeypatch.setattr(
        asr_proofread, "build_configured_providers", lambda settings: {"fake": provider}
    )
    return provider


def test_parse_pairs_tolerates_code_fence_and_prose():
    """模型经常套 ```json 围栏，甚至在数组前后加一句话。"""
    raw = '好的，我找到了两处：\n```json\n[["厌收","验收"],["排齐","排期"]]\n```'
    assert asr_proofread.parse_pairs(raw) == [("厌收", "验收"), ("排齐", "排期")]


def test_parse_pairs_returns_empty_on_garbage():
    for raw in ("", "没有发现问题", "[", '{"a":1}', "[1,2,3]"):
        assert asr_proofread.parse_pairs(raw) == []


def test_apply_pairs_requires_same_length():
    """等长是防改稿最关键的一道闸：不等长一律不换。"""
    text, applied = asr_proofread.apply_pairs("客户厌收通过", [("厌收", "验收通过")])
    assert text == "客户厌收通过"
    assert applied == []


def test_apply_pairs_requires_the_wrong_form_in_text():
    _text, applied = asr_proofread.apply_pairs("客户验收通过", [("厌收", "验收")])
    assert applied == []


def test_apply_pairs_skips_forms_that_appear_too_often():
    """一个「错写法」出现五六次，多半本来就是正常词，不能全改。"""
    text = "对章 " * 5
    fixed, applied = asr_proofread.apply_pairs(text, [("对章", "对账")])
    assert fixed == text
    assert applied == []


def test_apply_pairs_reports_what_it_changed():
    text = "[00:12] 客户厌收通过，下周排齐"
    fixed, applied = asr_proofread.apply_pairs(text, [("厌收", "验收"), ("排齐", "排期")])
    assert fixed == "[00:12] 客户验收通过，下周排期"
    assert applied == [("厌收", "验收"), ("排齐", "排期")]


def test_proofread_without_provider_leaves_text_alone(monkeypatch):
    """没配 Key（纯离线）时必须是原样返回，不能报错也不能卡住。"""
    monkeypatch.setattr(asr_proofread, "build_configured_providers", lambda settings: {})
    text, pairs = asr_proofread.proofread("客户厌收通过", ["验收"], settings=Settings())
    assert text == "客户厌收通过"
    assert pairs == []


def test_proofread_applies_a_valid_pair(monkeypatch):
    _install(monkeypatch, '[["厌收","验收"]]')
    text, pairs = asr_proofread.proofread("客户厌收通过", ["验收"], settings=Settings())
    assert text == "客户验收通过"
    assert pairs == [("厌收", "验收")]


def test_proofread_only_replaces_substrings_not_whole_text(monkeypatch):
    """模型即使回一段改写过的全文，代码也只会把配对里的词换掉。"""
    _install(monkeypatch, "这是一段被重写过的会议纪要，客户验收通过。")
    original = "客户厌收通过，下周继续跟进。"
    text, pairs = asr_proofread.proofread(original, ["验收"], settings=Settings())
    assert text == original
    assert pairs == []


def test_proofread_matches_against_hotwords_in_prompt(monkeypatch):
    provider = _install(monkeypatch, "[]")
    asr_proofread.proofread("客户厌收通过", ["验收", "回款"], settings=Settings())
    prompt = provider.calls[0][-1]["content"]
    assert "验收" in prompt and "回款" in prompt
