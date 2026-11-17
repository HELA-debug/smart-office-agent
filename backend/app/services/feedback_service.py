"""意见反馈：本机存档 + 生成可以直接发出的邮件。

为什么不用「后端偷偷上报」：
    这是本机部署的产品，用户的数据不该在没有告知的情况下离开这台电脑。所以反馈只走
    用户自己的邮件客户端——后端把内容整理成一条 `mailto:` 链接，由系统默认邮件程序
    带着内容打开，用户点「发送」才算真的发出去。

开发者邮箱从配置 `FEEDBACK_EMAIL` 读，留空时不拼邮件、只落本机存档，
界面据此退化成「复制内容，自己发到 xxx」的兜底路径。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..core.config import Settings
from ..core.utils import detect_git_sha, new_id

# 反馈类型 → 邮件标题里的中文标签
KIND_LABELS: dict[str, str] = {
    "bug": "问题反馈",
    "idea": "功能建议",
    "other": "其他反馈",
}

# 正文上限：存档里保留完整内容，拼邮件时按「编码后的链接长度」再收一次
MAX_MESSAGE_CHARS = 1500
MAX_CONTACT_CHARS = 120
# mailto 是 URL，中文按百分号编码会膨胀三倍；超过这个长度系统邮件程序会截断，
# 与其让用户发出去半截，不如主动收短并在正文里注明「完整版已存本机」。
MAX_MAILTO_CHARS = 1900
# 收短时保留多少字（编码后 ≈ 1200 字符，给标题与环境信息留余量）
SHORT_MESSAGE_CHARS = 400


class FeedbackService:
    """把一条反馈变成「存档 + 邮件」两件事，两者互不依赖。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ---------- 对外 ----------
    def submit(
        self,
        *,
        kind: str,
        message: str,
        contact: str = "",
        include_diagnostics: bool = True,
        client: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """存档并返回邮件素材；`target` 为空表示开发者邮箱还没配。"""
        text = message.strip()
        if not text:
            raise ValueError("反馈内容不能为空")
        text = text[:MAX_MESSAGE_CHARS]
        contact = (contact or "").strip()[:MAX_CONTACT_CHARS]
        kind_key = kind if kind in KIND_LABELS else "other"

        created_at = datetime.now().astimezone()
        feedback_id = new_id("fb")
        record: dict[str, Any] = {
            "id": feedback_id,
            "kind": kind_key,
            "message": text,
            "contact": contact,
            "include_diagnostics": include_diagnostics,
            "client": client or {},
            "created_at": created_at.isoformat(timespec="seconds"),
            "version": self.settings.version,
            # settings.git_sha 只在启动时探测成功才有值；这里再兜一层，
            # 邮件里带上 commit 才能对着代码定位问题
            "git_sha": self.settings.git_sha or detect_git_sha(),
        }
        saved_path = self._append(record)

        target = (self.settings.feedback_email or "").strip()
        subject = f"[Office Agent] {KIND_LABELS[kind_key]}"
        body = self._compose_body(record, include_diagnostics)
        mailto = ""
        truncated = False
        if target:
            mailto = self._mailto(target, subject, body)
            if len(mailto) > MAX_MAILTO_CHARS:
                # 太长：收短正文重拼一条，别让邮件客户端悄悄截掉后半段
                truncated = True
                body = self._compose_body(
                    record,
                    include_diagnostics,
                    message=f"{text[:SHORT_MESSAGE_CHARS]}……（内容较长，邮件里只放前面一段，完整版已存本机）",
                )
                mailto = self._mailto(target, subject, body)
        return {
            "id": feedback_id,
            "kind": kind_key,
            "saved": True,
            "saved_path": str(saved_path),
            "target": target,
            "subject": subject,
            "body": body,
            "mailto": mailto,
            "truncated": truncated,
        }

    @staticmethod
    def _mailto(target: str, subject: str, body: str) -> str:
        return f"mailto:{target}?subject={quote(subject)}&body={quote(body)}"

    # ---------- 内部 ----------
    def _append(self, record: dict[str, Any]) -> Path:
        """一行一条 JSON：坏了一条也不影响其它记录，出问题能直接 grep。"""
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def _path(self) -> Path:
        return self.settings.feedback_path / "feedback.jsonl"

    def _compose_body(
        self,
        record: dict[str, Any],
        include_diagnostics: bool,
        message: str | None = None,
    ) -> str:
        """拼邮件正文。`message` 传值用于「太长收短」时替换首段，其余信息照旧。"""
        text = record["message"] if message is None else message
        lines = [f"类型：{KIND_LABELS[record['kind']]}", "", text, ""]
        if record["contact"]:
            lines += [f"联系方式：{record['contact']}", ""]
        if include_diagnostics:
            client = record.get("client") or {}
            settings = self.settings
            lines += [
                "—— 下面由程序自动填写 ——",
                f"反馈编号：{record['id']}",
                f"时间：{record['created_at']}",
                f"版本：{record['version']} · {record['git_sha'][:7] or '未记录'}",
                f"引擎：{settings.engine_kind}"
                f"（{'演示模式' if settings.mock_mode else '真实模型'}）· "
                f"{settings.model_provider}/{settings.model_name}",
            ]
            # 客户端信息只放前端明确给的那几项（窗口形态、系统、屏幕尺寸），不塞 UA 原文
            for label, key in (
                ("窗口", "window"),
                ("系统", "platform"),
                ("屏幕", "screen"),
                ("界面", "theme"),
            ):
                value = client.get(key)
                if value:
                    lines.append(f"{label}：{value}")
        return "\n".join(lines).rstrip()


def local_feedback_path(settings: Settings) -> Path:
    """给设置页展示「反馈存在哪儿」用；不创建目录。"""
    return settings.feedback_path / "feedback.jsonl"


__all__ = ["KIND_LABELS", "MAX_MESSAGE_CHARS", "FeedbackService", "local_feedback_path"]
