#!/usr/bin/env python3
"""
进化曲线 — Agent自我量化看板。
灵感：自进化客服 Agent（Young-1231）的可测量进化曲线。
统计宪法违规、Gate 绕过、闭环缺失三项，输出趋势。

用法:
  python3 evolution_metrics.py
  python3 evolution_metrics.py --weeks 4
"""

import os
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

HERMES = Path.home() / ".hermes"
TZ = timezone(timedelta(hours=8))
NOW = datetime.now(TZ)


def count_constitution_violations(weeks=4):
    """统计 constitution.log 中的违规——按周分组"""
    logfile = HERMES / "logs" / "constitution.log"
    if not logfile.exists():
        return {}

    weekly = defaultdict(lambda: defaultdict(int))
    cutoff = NOW - timedelta(weeks=weeks)

    with open(logfile, encoding="utf-8") as f:
        for line in f:
            # [2026-06-04 03:22:26] VIOLATIONS=C3,C1 count=2 | ...
            match = re.match(r'\[(\d{4}-\d{2}-\d{2})[^\]]*\] VIOLATIONS=([^\s]+) count=(\d+)', line)
            if not match:
                continue
            date_str = match.group(1)
            rule_ids = match.group(2)
            count = int(match.group(3))

            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ)
            except ValueError:
                continue

            if date < cutoff:
                continue

            # Get week number
            week_key = date.strftime("%Y-W%W")
            for rid in rule_ids.split(","):
                weekly[week_key][rid] += 1

    return dict(weekly)


def count_gate_bypasses(weeks=4):
    """统计 gate.py 绕过——扫描 session 数据库的 bare-write 标记"""
    # 目前靠 bare-write-log.md 手动记录
    logfile = HERMES / "memories" / "failures" / "raw" / "bare-write-log.md"
    if not logfile.exists():
        return 0

    cutoff = NOW - timedelta(weeks=weeks)
    count = 0

    with open(logfile, encoding="utf-8") as f:
        for line in f:
            match = re.match(r'^##?\s*(\d{4}-\d{2}-\d{2})', line)
            if match:
                try:
                    date = datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=TZ)
                    if date >= cutoff:
                        count += 1
                except ValueError:
                    continue

    return count


def count_unverified_closures(weeks=4):
    """统计"假闭环"——在 session 中搜索疑似未验证的完成声明"""
    # 简化版：从 brainstem outbox 中搜模式
    outbox = HERMES / "brainstem" / "outbox.txt"
    if not outbox.exists():
        return 0

    cutoff = NOW - timedelta(weeks=weeks)
    patterns = [
        r'搞定了',
        r'完成了',
        r'已经.*好了',
    ]
    count = 0

    # outbox 太大，只读最近 N 行
    lines = []
    with open(outbox, encoding="utf-8") as f:
        # 读最后 5000 行
        all_lines = f.readlines()
        lines = all_lines[-5000:]

    for line in lines:
        for pat in patterns:
            if re.search(pat, line):
                count += 1
                break

    return count


def count_rule_evolution(weeks=4):
    """统计规则进化活动"""
    proposals = HERMES / "brainstem" / "rule_proposals.md"
    dryrun = HERMES / "experience" / "rule_dryrun.json"

    result = {"proposals": 0, "dryrun_rules": 0, "promoted": 0}

    if proposals.exists():
        with open(proposals, encoding="utf-8") as f:
            result["proposals"] = f.read().count("## 提案 #")

    if dryrun.exists():
        with open(dryrun, encoding="utf-8") as f:
            data = json.load(f)
            result["dryrun_rules"] = len(data)
            result["promoted"] = sum(1 for d in data if d.get("status") == "promoted")

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent进化曲线看板")
    parser.add_argument("--weeks", type=int, default=4, help="统计最近几周（默认4）")
    args = parser.parse_args()

    weeks = args.weeks
    viols = count_constitution_violations(weeks)
    bypasses = count_gate_bypasses(weeks)
    unverified = count_unverified_closures(weeks)
    evolved = count_rule_evolution()

    print(f"📊 Agent进化曲线 — 最近 {weeks} 周")
    print(f"   统计时间: {NOW.strftime('%Y-%m-%d %H:%M')}")
    print()

    # 宪法违规
    total_viols = sum(sum(r.values()) for r in viols.values())
    print(f"🔴 宪法违规: {total_viols} 次")
    if viols:
        for week in sorted(viols.keys()):
            rules = viols[week]
            rule_str = " ".join(f"{k}×{v}" for k, v in sorted(rules.items()))
            print(f"   {week}: {rule_str}")
    else:
        print(f"   （无违规记录）")

    print()

    # Gate 绕过
    print(f"🟡 Gate 绕过: {bypasses} 次")

    # 假闭环
    print(f"🟠 疑似未验证闭: ~{unverified} 次（outbox 模式匹配）")

    # 规则进化
    print(f"🟢 规则进化: {evolved['proposals']} 提案 / {evolved['dryrun_rules']} 沙箱 / {evolved['promoted']} 已升级")

    print()
    print("---")
    print("趋势判断:")
    if total_viols == 0:
        print("  ✅ 无宪法违规")
    elif total_viols <= 2:
        print("  ⚠️ 偶发违规，检查是否有同类型重复")
    else:
        print("  🔴 频繁违规，需要 root cause 分析")

    if bypasses <= 1:
        print("  ✅ Gate 绕过控制良好")
    else:
        print("  ⚠️ Gate 绕过频率偏高，检查触发模式")


if __name__ == "__main__":
    main()
