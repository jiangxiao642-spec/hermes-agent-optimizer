#!/usr/bin/env python3
"""
Agent规则变更提案生成器 v2 — HyperAgents 沙箱原则落地版。

用法:
  # 正常提案（直接提交用户审核）
  python3 propose_rule_change.py --problem "..." --proposed "..." --target "..." --action add

  # 沙箱模式（先在日志里跑 3 天，自动验证）
  python3 propose_rule_change.py --problem "..." --proposed "..." --target "..." --dry-run

  # 查看沙箱规则状态
  python3 propose_rule_change.py --dry-run-list

  # 列出待审提案
  python3 propose_rule_change.py --list
"""

import argparse
import json
import os
from datetime import datetime, timezone, timedelta

PROPOSALS_FILE = os.path.expanduser("~/.hermes/brainstem/rule_proposals.md")
DRYRUN_FILE = os.path.expanduser("~/.hermes/experience/rule_dryrun.json")
TZ = timezone(timedelta(hours=8))


def count_existing():
    if not os.path.exists(PROPOSALS_FILE):
        return 0
    with open(PROPOSALS_FILE) as f:
        return f.read().count("## 提案 #")


def write_proposal(problem, proposed, target, action):
    n = count_existing() + 1
    now = datetime.now(TZ).strftime("%Y-%m-%d %H:%M")
    action_label = {"add": "新增", "strengthen": "加固", "modify": "修改"}.get(action, action)

    template = f"""## 提案 #{n} — {action_label} — 待审核

**目标文件：** `{target}`
**动作：** {action_label}
**建议文本：**
> {proposed}
**原因：** {problem}
**证据：** 见对话记录
**日期：** {now}

---
"""

    os.makedirs(os.path.dirname(PROPOSALS_FILE), exist_ok=True)
    with open(PROPOSALS_FILE, "a", encoding="utf-8") as f:
        f.write(template)

    print(f"[OK] 提案 #{n} 已写入 {PROPOSALS_FILE}")
    print(f"     动作: {action_label}")
    print(f"     当前待审提案总数: {n}")
    if n >= 5:
        print(f"     ⚠ 待审提案已堆积 {n} 条，建议通知用户。")


def dryrun_add(problem, proposed, target, action):
    """沙箱模式：规则不在提案里，只在 dryrun.json 里记录。
    等累积 3 次命中 → 自动升级为真实提案。"""
    now = datetime.now(TZ)

    # 加载现有沙箱
    dryruns = []
    if os.path.exists(DRYRUN_FILE):
        with open(DRYRUN_FILE, encoding="utf-8") as f:
            dryruns = json.load(f)

    # 检查是否已有相似规则（匹配 target + action）
    existing = None
    for dr in dryruns:
        if dr["target"] == target and dr["action"] == action:
            existing = dr
            break

    if existing:
        existing["hit_count"] += 1
        existing["last_hit"] = now.isoformat()
        existing["hits"].append({
            "time": now.isoformat(),
            "reason": problem[:200]
        })
        hit_count = existing["hit_count"]
    else:
        entry = {
            "id": f"DRY-{len(dryruns)+1:03d}",
            "target": target,
            "action": action,
            "proposed": proposed,
            "problem_first": problem,
            "hit_count": 1,
            "created": now.isoformat(),
            "last_hit": now.isoformat(),
            "hits": [{"time": now.isoformat(), "reason": problem[:200]}],
            "status": "observing"
        }
        dryruns.append(entry)
        hit_count = 1

    os.makedirs(os.path.dirname(DRYRUN_FILE), exist_ok=True)
    with open(DRYRUN_FILE, "w", encoding="utf-8") as f:
        json.dump(dryruns, f, ensure_ascii=False, indent=2)

    print(f"[DRY-RUN] 规则已加入沙箱观察 ({DRYRUN_FILE})")
    print(f"         目标: {target}")
    print(f"         命中次数: {hit_count}/3")

    # 自动升级：累积 3 次 → 正式提案
    if hit_count >= 3 and existing and existing["status"] == "observing":
        existing["status"] = "promoted"
        with open(DRYRUN_FILE, "w", encoding="utf-8") as f:
            json.dump(dryruns, f, ensure_ascii=False, indent=2)

        write_proposal(
            problem=f"[自动升级] 沙箱累积 {hit_count} 次命中：{existing['problem_first'][:100]}",
            proposed=proposed,
            target=target,
            action=action
        )
        print(f"     ✅ 已达 3 次命中，自动升级为正式提案！")


def dryrun_list():
    if not os.path.exists(DRYRUN_FILE):
        print("[空] 没有沙箱规则。")
        return

    with open(DRYRUN_FILE, encoding="utf-8") as f:
        dryruns = json.load(f)

    active = [d for d in dryruns if d["status"] == "observing"]
    promoted = [d for d in dryruns if d["status"] == "promoted"]

    print(f"沙箱规则: {len(active)} 观察中 / {len(promoted)} 已升级\n")
    for d in active:
        days = (datetime.now(TZ) - datetime.fromisoformat(d["created"])).days
        print(f"  [{d['id']}] {d['target']}")
        print(f"       命中: {d['hit_count']}/3  |  观察 {days} 天")
        print(f"       原因: {d['problem_first'][:80]}")
        print()

    if promoted:
        print("已升级（已自动提交正式提案）:")
        for d in promoted:
            print(f"  [{d['id']}] {d['target']} — {d['hit_count']} 次命中后自动升级")


def list_proposals():
    if not os.path.exists(PROPOSALS_FILE):
        print("[空] 没有待审提案。")
        return
    with open(PROPOSALS_FILE, encoding="utf-8") as f:
        content = f.read()
    pending = [p for p in content.split("---\n") if "待审核" in p]
    print(f"待审提案: {len(pending)} 条\n")
    for p in pending:
        print(p.strip())
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent规则变更提案生成器 v2 (HyperAgents沙箱)")
    parser.add_argument("--problem", help="触发原因")
    parser.add_argument("--proposed", help="建议的规则文本")
    parser.add_argument("--target", help="目标文件路径")
    parser.add_argument("--action", choices=["add", "strengthen", "modify"], default="add")
    parser.add_argument("--dry-run", action="store_true", help="沙箱模式：先观察 3 天再决定")
    parser.add_argument("--dry-run-list", action="store_true", help="查看沙箱规则状态")
    parser.add_argument("--list", action="store_true", help="列出待审提案")

    args = parser.parse_args()

    if args.dry_run_list:
        dryrun_list()
    elif args.list:
        list_proposals()
    elif args.dry_run and args.problem and args.proposed and args.target:
        dryrun_add(args.problem, args.proposed, args.target, args.action)
    elif args.problem and args.proposed and args.target:
        write_proposal(args.problem, args.proposed, args.target, args.action)
    else:
        parser.print_help()
