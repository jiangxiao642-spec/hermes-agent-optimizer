#!/usr/bin/env python3
"""
主动遗忘 —— 人脑式记忆管理
================================
像睡眠时的突触下缩：结晶后的碎片自动压缩，不重要的清除。

三件事：
1. 小脑 thought log 轮转：保留最近 5000 条，旧的压成摘要
2. Hermes memory 检查：超 75% → 提醒压缩
3. Agentmemory 检查：触发自动遗忘

用法：
  python3 forget.py           # 正常执行
  python3 forget.py --dry-run  # 只看不动
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
THOUGHT_LOG = HERMES_HOME / "brainstem" / "thoughts.jsonl"
THOUGHT_ARCHIVE = HERMES_HOME / "brainstem" / "thoughts_archive.jsonl"
MAX_THOUGHTS = 5000
MEMORY_PERSISTENT = HERMES_HOME / "memories" / "MEMORY.md"
MEMORY_MAX_CHARS = 120000
AGENTMEMORY_URL = "http://localhost:3111"


def log(msg):
    print(f"[forget] {datetime.now().strftime('%H:%M')} {msg}")


def rotate_thoughts(dry_run=False):
    """保留最近 MAX_THOUGHTS 条，旧压缩成统计摘要。"""
    if not THOUGHT_LOG.exists():
        log("thought log 不存在，跳过")
        return

    lines = []
    with open(THOUGHT_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    total = len(lines)
    if total <= MAX_THOUGHTS:
        log(f"thought log: {total} 条，未超 {MAX_THOUGHTS}，跳过")
        return

    keep = lines[-MAX_THOUGHTS:]
    archive = lines[:-MAX_THOUGHTS]

    moods = {}
    types = {}
    for line in archive:
        try:
            entry = json.loads(line)
            m = entry.get("mood", "?")
            t = entry.get("type", "?")
            moods[m] = moods.get(m, 0) + 1
            types[t] = types.get(t, 0) + 1
        except Exception:
            pass

    top_moods = sorted(moods.items(), key=lambda x: -x[1])[:5]
    top_types = sorted(types.items(), key=lambda x: -x[1])[:5]

    summary = (
        f"=== 压缩 {len(archive)} 条旧数据 ===\n"
        f"情绪分布: {', '.join(f'{m}({c})' for m, c in top_moods)}\n"
        f"类型分布: {', '.join(f'{t}({c})' for t, c in top_types)}\n"
        f"压缩于: {datetime.now().isoformat()}\n"
        f"===================================\n"
    )

    if dry_run:
        log(f"DRY-RUN: 将压缩 {len(archive)} 条 → 保留 {len(keep)} 条")
        log(f"摘要预览:\n{summary[:200]}")
        return

    with open(THOUGHT_ARCHIVE, "a", encoding="utf-8") as f:
        f.write(summary)

    with open(THOUGHT_LOG, "w", encoding="utf-8") as f:
        for line in keep:
            f.write(line + "\n")

    log(f"✅ 压缩完成: {len(archive)} 条 → 保留 {len(keep)} 条")


def check_hermes_memory(dry_run=False):
    """检查 Hermes persistent memory 是否超 75%。"""
    if not MEMORY_PERSISTENT.exists():
        log("persistent.md 不存在，跳过")
        return

    size = MEMORY_PERSISTENT.stat().st_size
    pct = size / MEMORY_MAX_CHARS * 100

    if pct >= 75:
        log(f"⚠ persistent.md: {size}/{MEMORY_MAX_CHARS} ({pct:.0f}%) — 超 75% 阈值，需要压缩！")
        if dry_run:
            log("DRY-RUN: 不执行压缩")
        else:
            log("请在下一条会话消息中执行 memory 压缩")
    else:
        log(f"persistent.md: {size}/{MEMORY_MAX_CHARS} ({pct:.0f}%) — 正常")


def trigger_agentmemory_forget(dry_run=False):
    """触发 agentmemory 的内置自动遗忘。"""
    try:
        payload = json.dumps({"dryRun": dry_run}).encode()
        req = urllib.request.Request(
            f"{AGENTMEMORY_URL}/agentmemory/auto-forget",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            log(f"agentmemory auto-forget: {json.dumps(result, ensure_ascii=False)[:200]}")
    except urllib.error.HTTPError as e:
        log(f"agentmemory auto-forget: HTTP {e.code}")
    except Exception as e:
        log(f"agentmemory auto-forget: 连接失败 ({e})")


def main():
    dry_run = "--dry-run" in sys.argv

    if dry_run:
        log("=== DRY RUN ===")

    rotate_thoughts(dry_run)
    check_hermes_memory(dry_run)
    trigger_agentmemory_forget(dry_run)

    log("完成")


if __name__ == "__main__":
    main()
