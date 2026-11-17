#!/usr/bin/env python
"""生成演示用的会议记录 DOCX 样例（确定性内容，无个人信息）。

用法：
    python scripts/make_sample.py [--out data/samples/meeting_notes.docx]

产物供 Demo 0:30「上传文件」步骤与 smoke 测试使用。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.shared import Pt

DEFAULT_OUT = Path("data/samples/meeting_notes.docx")

TITLE = "产品周会会议记录（2026-W43）"

# 内容为虚构演示数据；邮箱统一 example 域名，不含任何真实个人信息。
SECTIONS: list[tuple[str, list[str]]] = [
    (
        "会议信息",
        [
            "时间：2026-10-22（周四）14:00-15:00",
            "地点：线上会议",
            "参会：产品、研发、设计（共 3 人，演示用虚构名单）",
            "记录：me@example.com",
        ],
    ),
    (
        "本周进展",
        [
            "1. 毛胚主链路已打通：上传素材 → 生成计划 → 工具调用 → 审批 → 产物下载。",
            "2. 审批卡与产物卡完成联调，拒绝链路可正常中断且不产生外部写操作。",
            "3. DOCX 周报模板确定：标题、本周完成、风险与阻塞、下周计划四段式。",
        ],
    ),
    (
        "风险与阻塞",
        [
            "1. 真实模型 Key 尚未配置，当前使用 mock 模式演示，需在 D7 前完成真实模式验证。",
            "2. 部署机 Docker 环境待确认，若不可用则改用本地进程方式演示。",
            "3. 邮件仅走 mock 发件箱，真实发送与 OAuth 授权本版明确不做。",
        ],
    ),
    (
        "下周计划",
        [
            "1. 完成产物预览与审计记录（D6）。",
            "2. 接入真实模型并验证降级路径（D7）。",
            "3. 代码冻结、部署到测试机、录制 3 分钟 Demo（D8-D9）。",
        ],
    ),
    (
        "决议",
        [
            "本版以「端到端可跑、过程可见、可替换、可降级、可交接」为验收标准，",
            "新增需求须说明砍掉哪一条，否则进入 backlog。",
        ],
    ),
]


def build_document() -> Document:
    doc = Document()

    # 正文默认字体（中文环境优先宋体/等线，缺字体时 Word 自动回退）
    style = doc.styles["Normal"]
    style.font.name = "DengXian"
    style.font.size = Pt(11)

    doc.add_heading(TITLE, level=1)
    doc.add_paragraph("本文件由 scripts/make_sample.py 生成，仅用于演示与 smoke 测试。")

    for heading, lines in SECTIONS:
        doc.add_heading(heading, level=2)
        for line in lines:
            doc.add_paragraph(line)

    doc.add_paragraph("")
    doc.add_paragraph("—— 记录人：me@example.com（mock 演示数据）")
    return doc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成演示用会议记录 DOCX")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出路径")
    args = parser.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = build_document()
    doc.save(out)

    size = out.stat().st_size
    chars = sum(len(p.text) for p in doc.paragraphs)
    print(f"已生成样例：{out}（{size} 字节，{len(doc.paragraphs)} 段，约 {chars} 字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
