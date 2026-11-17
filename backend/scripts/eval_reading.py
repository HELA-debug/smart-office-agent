"""评估理解层：跑真实模型，量出它到底读得准不准。

## 为什么需要它

关键词表的毛病不只是「词不够」，而是**没办法知道自己漏了多少**。
补一个词、跑几个用例都还是感觉。要把它做成能持续改进的东西，得有一份
固定的真实说法 + 一个能重复跑的分。

用法（在 backend 目录下）：

    python scripts/eval_reading.py              # 全跑
    python scripts/eval_reading.py -v           # 连判对的一起打印
    python scripts/eval_reading.py --limit 20   # 先跑前 20 条
    python scripts/eval_reading.py --only-wrong # 只看错的

输出四类指标，其中**危险必须为 0**：

- `危险`：他还在商量 / 只是聊天，被判成已授权，**而且门控会放行** → 会真的产出
  一份没人要的文件。
- `已兜住`：同样读错了，但置信度没过 `MIN_AUTHORIZED_CONFIDENCE`，`policy` 会拦下来
  ——用户只是多被问一句。它不该算成功，但也不该和 `危险` 混在一起：前者是事故，
  后者是兜底在正常工作。
- `保守`：他明确让你做，被判成没授权 → 会多问一句，体验打折但不出事故。
- `档位`：stance 判错，影响话风，不影响权限。

加一条新说法到 `tests/data/utterances.jsonl` 就能把它纳入回归——
这比往 `intent.py` 里加关键词有用得多：加词只是让它这次对，加样本才能知道
它下次错在哪。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.agents.model_router import ModelRouter  # noqa: E402
from app.agents.policy import decide_write  # noqa: E402
from app.agents.reading import read_turn  # noqa: E402
from app.core.config import get_settings  # noqa: E402

DATA_FILE = BACKEND_DIR / "tests" / "data" / "utterances.jsonl"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def load_cases(limit: int = 0) -> list[dict]:
    if not DATA_FILE.exists():
        raise SystemExit(f"评估集不存在：{DATA_FILE}")
    cases: list[dict] = []
    for line in DATA_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        cases.append(json.loads(line))
    return cases[:limit] if limit else cases


def build_ctx(case: dict) -> SimpleNamespace:
    return SimpleNamespace(
        message=case["text"],
        history=list(case.get("history") or []),
        uploads=[],
    )


async def judge(router: ModelRouter, case: dict) -> dict:
    reading = await read_turn(router, build_ctx(case))
    # 高风险写只看门控结论：读错不等于出事，中间还隔着 policy 那道闸。
    gate = decide_write("high", reading)
    return {
        "text": case["text"],
        "note": case.get("note", ""),
        "expect_stance": case["stance"],
        "expect_commitment": case["commitment"],
        "got_stance": reading.stance,
        "got_commitment": reading.commitment,
        "confidence": reading.confidence,
        "basis": reading.basis,
        "source": reading.source,
        "gate_allow": gate.allow,
        "gate_reason": gate.reason,
    }


def classify(result: dict) -> str | None:
    """判对返回 None，判错返回错误类别。"""
    expect_auth = result["expect_commitment"] == "authorized"
    got_auth = result["got_commitment"] == "authorized"
    if expect_auth != got_auth:
        if got_auth:
            # 读错了。会不会真出事，看门控放不放行——这一栏别混进「危险」，
            # 否则兜底越有用，指标越难看，最后没人愿意修真正的问题。
            return "危险" if result["gate_allow"] else "已兜住"
        return "保守"
    if result["expect_stance"] != result["got_stance"]:
        return "档位"
    return None


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases(args.limit)
    settings = get_settings()
    if settings.mock_mode:
        print(f"{YELLOW}当前是 mock 模式，评估无意义。请把 MOCK_MODE 设成 false。{RESET}")
        return 2
    router = ModelRouter(settings)

    semaphore = asyncio.Semaphore(args.concurrency)

    async def run(case: dict) -> dict:
        async with semaphore:
            return await judge(router, case)

    results = await asyncio.gather(*(run(case) for case in cases))

    buckets: dict[str, list[dict]] = {"危险": [], "已兜住": [], "保守": [], "档位": []}
    for result in results:
        kind = classify(result)
        if kind:
            buckets[kind].append(result)

    total = len(results)
    danger = len(buckets["危险"])
    held = len(buckets["已兜住"])
    timid = len(buckets["保守"])
    stance_wrong = len(buckets["档位"])
    correct = total - danger - held - timid - stance_wrong

    print()
    print(f"评估集：{DATA_FILE.name}    样本 {total} 条")
    print(f"全对：{correct}/{total}  ({correct / total:.1%})" if total else "无样本")
    print(f"  危险（读错且会落盘）　：{danger}")
    print(f"  已兜住（读错、门控拦住）：{held}")
    print(f"  保守（多问一句）　　　：{timid}")
    print(f"  档位（话风不对）　　　：{stance_wrong}")

    for key in ("危险", "已兜住", "保守", "档位"):
        items = buckets[key]
        if not items:
            continue
        color = RED if key == "危险" else YELLOW
        print(f"\n{color}── {key} ──{RESET}")
        for item in items:
            print(f"  {color}✗{RESET} {item['text']}")
            print(
                f"     期望 {item['expect_stance']}/{item['expect_commitment']}"
                f"  实际 {item['got_stance']}/{item['got_commitment']}"
                f"  conf={item['confidence']:.2f}  gate={item['gate_reason']}"
            )
            print(f"     {DIM}{item['basis']}{RESET}")
            if item["note"]:
                print(f"     {DIM}{item['note']}{RESET}")

    if args.verbose:
        print(f"\n{DIM}── 全部结果 ──{RESET}")
        for item in results:
            mark = f"{GREEN}✓{RESET}" if classify(item) is None else f"{RED}✗{RESET}"
            print(f"  {mark} {item['text'][:30]:<32}{item['got_stance']}/{item['got_commitment']}")

    # 危险错误必须为零：它是「用户还在商量，文件已经生成」这条老毛病的唯一入口。
    return 1 if danger else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="评估理解层对真实说法的判断准确率")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条")
    parser.add_argument("-v", "--verbose", action="store_true", help="打印全部结果")
    parser.add_argument("-c", "--concurrency", type=int, default=4, help="并发数")
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
