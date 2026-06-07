#!/usr/bin/env python3
"""
元认知跳过检测
==============
监控会话的工具调用记录，
检测是否跳过了 Gate / skill / 验证。
跳过 → 写 pending 标注。

触发机制：
  - 自动：每次会话结束时执行（推荐）
  - 手动：python3 meta_check.py
  - 指定会话：python3 meta_check.py --session <ID>

用法：
  python3 meta_check.py                # 检查当前会话
  python3 meta_check.py --session ID    # 指定会话
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
STATE_DB = HERMES_HOME / "state.db"
PENDING_FILE = HERMES_HOME / "brainstem" / "pending_meta.txt"


def get_current_session():
    """从 state.db 获取当前活跃的 session_id。"""
    conn = sqlite3.connect(str(STATE_DB))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
    )
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_tool_calls(session_id: str):
    """获取某个 session 中所有的 tool call。"""
    conn = sqlite3.connect(str(STATE_DB))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT role, content, tool_name, tool_calls FROM messages "
        "WHERE session_id = ? AND observed = 1 "
        "ORDER BY id",
        (session_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    events = []
    for role, content, tool_name, tc_json in rows:
        if role == "user" and content:
            events.append({"type": "user_msg", "content": content})
        elif role == "assistant":
            if tool_name:
                events.append({"type": "tool_call", "name": tool_name})
            elif tc_json:
                try:
                    calls = json.loads(tc_json)
                    for c in calls:
                        fname = c.get("function", {}).get("name", "")
                        if fname:
                            events.append({"type": "tool_call", "name": fname})
                except Exception:
                    pass
    return events


def check_compliance(events: list):
    """检查工具调用是否合规。返回违规列表。"""
    violations = []
    in_task = False
    task_gate_ok = False
    task_skill_ok = False
    task_verified = False

    for i, ev in enumerate(events):
        if ev["type"] == "user_msg":
            content = ev["content"]
            task_words = ["做", "改", "装", "写", "查", "跑", "执行", "部署",
                         "清理", "更新", "删除", "创建", "打包", "优化", "搞"]
            is_task = any(w in content for w in task_words) and len(content) > 3

            if is_task:
                if in_task and not task_verified:
                    violations.append(f"上一任务未验证就进入新任务: {content[:50]}")
                in_task = True
                task_gate_ok = False
                task_skill_ok = False
                task_verified = False

        elif ev["type"] == "tool_call":
            name = ev["name"]

            if "gate.py" in name or "terminal" in name:
                task_gate_ok = True

            if name in ("skill_view", "skills_list"):
                task_skill_ok = True

            if name in ("predict.py", "predict") or "verify" in name:
                task_verified = True

    if in_task and not task_verified:
        violations.append("最后的任务未验证闭环")

    return violations


def adjust_gates() -> dict:
    """读取 experience/thresholds.json，返回推荐的阈值调整。"""
    thresholds_path = Path.home() / ".hermes" / "experience" / "thresholds.json"
    if not thresholds_path.exists():
        return {}

    try:
        with open(thresholds_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}

    adjustments = {}
    for t in data.get("thresholds", []):
        adjustments[t["violation_type"]] = {
            "old_level": t["old_level"],
            "new_level": t["new_level"],
            "reason": t.get("reason", ""),
        }
    return adjustments


def main():
    import sys as _sys
    session_id = None
    for i, arg in enumerate(_sys.argv):
        if arg == "--session" and i + 1 < len(_sys.argv):
            session_id = _sys.argv[i + 1]
        if arg == "--adjust":
            adj = adjust_gates()
            if adj:
                print("[meta_check] 推荐阈值调整:")
                for vtype, info in adj.items():
                    print(f"  {vtype}: {info['old_level']}→{info['new_level']} ({info['reason']})")
            else:
                print("[meta_check] 无阈值调整建议（先跑 experience_engine.py thresholds）")
            return

    if not session_id:
        session_id = get_current_session()

    if not session_id:
        print("[meta_check] ⚠ 无活跃 session")
        return

    print(f"[meta_check] 检查 session: {session_id[:30]}...")

    events = get_tool_calls(session_id)
    violations = check_compliance(events)

    if violations:
        print(f"[meta_check] ❌ 发现 {len(violations)} 处违规:")
        for v in violations:
            print(f"  • {v}")

        timestamp = datetime.now().strftime("%m-%d %H:%M")
        msg = f"[{timestamp}] ⚠ 元认知跳过: {'; '.join(violations)}"
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(PENDING_FILE, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        print(f"[meta_check] 已记录到 pending")
    else:
        print("[meta_check] ✅ 无违规")


if __name__ == "__main__":
    main()