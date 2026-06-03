#!/usr/bin/env python3
"""
Mission Layer — 长期目标锚点 + 漂移检测
=======================================

解决"每一步都正确，最终结果错误"的问题。

核心设计：
  1. Mission 结构化 — 不是文本，是带版本号、父版本链、变更原因的对象
  2. 漂移量化 — 三个锚点（成功标准/行为约束/禁止事项），用约束违反计数
  3. 变动率 — 时间窗口内版本跳数，识别上游需求不稳定
  4. 生命周期 — DRAFT→ACTIVE→DEVIATING→REALIGNED/ABANDONED/VOLATILE

与 Constitution 的区别：
  Constitution 是"死的"——底线不可协商
  Mission 是"活的"——方向可以变更，但必须可追溯

存储：~/.hermes/missions/missions.jsonl

用法：
  from mission import MissionManager
  mm = MissionManager()

  # 定义
  mm.create("开发CRM系统",
            success_criteria=["输出可运行的Python脚本", "支持用户CRUD"],
            constraints=["不改动数据库schema", "不引入新依赖"],
            prohibited=["删除用户数据", "修改系统表"])

  # 漂移检查
  result = mm.check(mission_id)
  # → {"drift_score": 0.25, "lifecycle": "DEVIATING", "violations": [...]}
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum


HERMES_HOME = Path.home() / ".hermes"
MISSION_DIR = HERMES_HOME / "missions"
MISSION_FILE = MISSION_DIR / "missions.jsonl"
LOG_DIR = HERMES_HOME / "logs"

# ── 生命周期 ──────────────────────────

class Lifecycle(Enum):
    DRAFT = "DRAFT"            # 草稿，未激活
    ACTIVE = "ACTIVE"          # 运行中
    DEVIATING = "DEVIATING"    # 偏离中，可纠正
    REALIGNED = "REALIGNED"    # 纠正后回到 ACTIVE
    VOLATILE = "VOLATILE"      # 上游频繁变更，暂缓纠正
    ABANDONED = "ABANDONED"    # 用户放弃

# ── 漂移阈值 ──────────────────────────
DRIFT_WARNING = 0.25   # >= 此值 → DEVIATING
DRIFT_CRITICAL = 0.50  # >= 此值 → 触发重规划
VOLATILE_WINDOW_DAYS = 7
VOLATILE_THRESHOLD = 3  # N天内≥N次变更 → VOLATILE


class MissionManager:
    """长期目标管理器。"""

    def __init__(self):
        MISSION_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    # ── 创建 ────────────────────────

    def create(self, goal: str,
               success_criteria: list[str] | None = None,
               constraints: list[str] | None = None,
               prohibited: list[str] | None = None,
               confirmed_by: str = "user") -> dict:
        """创建一个新 Mission。

        Args:
            goal: 一句话描述目标
            success_criteria: 成功标准列表
            constraints: 行为约束列表
            prohibited: 禁止事项列表
            confirmed_by: 谁确认的（user / agent / system）
        """
        mission = {
            "id": datetime.now().strftime("M%Y%m%d_%H%M%S"),
            "version": 1,
            "goal": goal.strip(),
            "success_criteria": success_criteria or [],
            "constraints": constraints or [],
            "prohibited": prohibited or [],
            "parent_version": None,
            "change_reason": "初始定义",
            "confirmed_by": confirmed_by,
            "lifecycle": Lifecycle.ACTIVE.value,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "state_history": [
                {
                    "from": None,
                    "to": Lifecycle.ACTIVE.value,
                    "reason": "创建",
                    "at": datetime.now().isoformat(),
                }
            ],
            "drift_log": [],
        }

        self._write(mission)
        self._log(mission["id"], "CREATE", f"v1: {goal[:80]}")
        return mission

    # ── 漂移检查 ────────────────────

    def check(self, mission_id: str,
              current_outputs: list[str] | None = None,
              violated_constraints: list[str] | None = None,
              triggered_prohibited: list[str] | None = None) -> dict:
        """检查当前状态是否偏离 Mission。

        Args:
            mission_id: 目标 ID
            current_outputs: 最近 N 步的产出描述
            violated_constraints: 违反的行为约束
            triggered_prohibited: 触发的禁止事项

        Returns:
            {"drift_score": 0.25, "lifecycle": "DEVIATING",
             "violations": [...], "recommendation": "..."}
        """
        mission = self._load_latest(mission_id)
        if not mission:
            return {"error": f"Mission {mission_id} 不存在"}

        violations = []
        total_checks = 0

        # 1. 禁止事项 — 最重，触发即 CRITICAL
        if triggered_prohibited:
            for item in triggered_prohibited:
                for rule in mission.get("prohibited", []):
                    if item in rule or rule in item:
                        violations.append({
                            "type": "PROHIBITED",
                            "rule": rule,
                            "actual": item,
                            "weight": 1.0,  # 全权重
                        })

        # 2. 行为约束 — 中等
        if violated_constraints:
            total_constraints = len(mission.get("constraints", [])) or 1
            for item in violated_constraints:
                violations.append({
                    "type": "CONSTRAINT",
                    "rule": item,
                    "actual": item,
                    "weight": 1.0 / total_constraints,
                })

        # 3. 成功标准 — 累计比例
        criteria = mission.get("success_criteria", [])
        if criteria and current_outputs:
            outputs_text = " ".join(current_outputs).lower()
            total_checks = len(criteria)
            for criterion in criteria:
                if criterion.lower() not in outputs_text:
                    violations.append({
                        "type": "SUCCESS_GAP",
                        "rule": criterion,
                        "actual": "未在产出中找到此标准",
                        "weight": 0.5 / max(total_checks, 1),
                    })

        # 计算漂移分数
        max_possible = 1.0 + (len(mission.get("constraints", [])) * 0.5) + (total_checks * 0.3)
        drift_score = min(
            sum(v["weight"] for v in violations) / max(max_possible, 0.1),
            1.0
        )

        # 生命周期判断
        old_lifecycle = mission.get("lifecycle", Lifecycle.ACTIVE.value)
        new_lifecycle = self._determine_lifecycle(drift_score, old_lifecycle, mission_id)

        # 写漂移日志
        if drift_score > 0 or new_lifecycle != old_lifecycle:
            self._log_drift(mission, drift_score, violations, new_lifecycle)

        # 更新生命周期
        if new_lifecycle != old_lifecycle:
            mission["lifecycle"] = new_lifecycle
            mission["state_history"].append({
                "from": old_lifecycle,
                "to": new_lifecycle,
                "reason": f"漂移分数 {drift_score:.0%}",
                "at": datetime.now().isoformat(),
            })
            self._write(mission)

        recommendation = self._recommend(drift_score, new_lifecycle)

        return {
            "mission_id": mission_id,
            "version": mission["version"],
            "goal": mission["goal"],
            "drift_score": round(drift_score, 2),
            "lifecycle": new_lifecycle,
            "violations": violations,
            "recommendation": recommendation,
        }

    # ── 更新 ────────────────────────

    def update(self, mission_id: str, new_goal: str,
               reason: str = "", confirmed_by: str = "user") -> dict:
        """更新 Mission——版本号+1，记录父版本和变更原因。

        这是正常需求变更，不是漂移。confirmed_by 必须明确。
        """
        old = self._load_latest(mission_id)
        if not old:
            return {"error": f"Mission {mission_id} 不存在"}

        # 检查变动率
        change_freq = self._change_frequency(mission_id)

        new = {
            **old,
            "id": mission_id,
            "version": old["version"] + 1,
            "goal": new_goal.strip(),
            "parent_version": old["version"],
            "change_reason": reason,
            "confirmed_by": confirmed_by,
            "lifecycle": Lifecycle.ACTIVE.value,  # 用户确认的变更回 ACTIVE
            "updated_at": datetime.now().isoformat(),
            "state_history": old.get("state_history", []) + [
                {
                    "from": old.get("lifecycle", "ACTIVE"),
                    "to": Lifecycle.ACTIVE.value,
                    "reason": f"用户更新 v{old['version']}→{old['version']+1}: {reason}",
                    "at": datetime.now().isoformat(),
                }
            ],
        }

        # 变动率标记
        if change_freq >= VOLATILE_THRESHOLD:
            new["lifecycle"] = Lifecycle.VOLATILE.value
            new["state_history"].append({
                "from": Lifecycle.ACTIVE.value,
                "to": Lifecycle.VOLATILE.value,
                "reason": f"过去{VOLATILE_WINDOW_DAYS}天内变更{change_freq}次，上游需求不稳定",
                "at": datetime.now().isoformat(),
            })

        self._write(new)
        self._log(mission_id, "UPDATE", f"v{old['version']}→v{new['version']}: {new_goal[:80]}")
        return new

    # ── 查询 ────────────────────────

    def get(self, mission_id: str) -> dict | None:
        """获取最新版本。"""
        return self._load_latest(mission_id)

    def history(self, mission_id: str) -> list[dict]:
        """获取完整版本历史。"""
        if not MISSION_FILE.exists():
            return []
        with open(MISSION_FILE, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
        return [i for i in items if i["id"] == mission_id]

    def list_active(self) -> list[dict]:
        """列出所有活跃 Mission。"""
        if not MISSION_FILE.exists():
            return []
        with open(MISSION_FILE, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
        active = [i for i in items if i.get("lifecycle") in
                   (Lifecycle.ACTIVE.value, Lifecycle.DEVIATING.value, Lifecycle.VOLATILE.value)]
        # 每个 id 只取最新版本
        seen = {}
        for item in sorted(active, key=lambda x: x["version"], reverse=True):
            if item["id"] not in seen:
                seen[item["id"]] = item
        return list(seen.values())

    # ── 内部 ────────────────────────

    def _load_latest(self, mission_id: str) -> dict | None:
        """加载最新版本。"""
        versions = self.history(mission_id)
        if not versions:
            return None
        return max(versions, key=lambda x: x["version"])

    def _write(self, mission: dict):
        """追加写入。"""
        mission["updated_at"] = datetime.now().isoformat()
        with open(MISSION_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(mission, ensure_ascii=False) + "\n")

    def _determine_lifecycle(self, drift_score: float, current: str,
                             mission_id: str) -> str:
        """根据漂移分数判定生命周期。"""
        if current == Lifecycle.ABANDONED.value:
            return current
        if current == Lifecycle.VOLATILE.value:
            return current  # 上游不稳定时不自动切换

        if drift_score >= DRIFT_CRITICAL:
            return Lifecycle.DEVIATING.value
        if drift_score >= DRIFT_WARNING:
            return Lifecycle.DEVIATING.value
        return Lifecycle.ACTIVE.value

    def _change_frequency(self, mission_id: str) -> int:
        """计算过去 N 天内版本变更次数。"""
        cutoff = datetime.now() - timedelta(days=VOLATILE_WINDOW_DAYS)
        versions = self.history(mission_id)
        return sum(
            1 for v in versions
            if datetime.fromisoformat(v["updated_at"]) > cutoff
        )

    def _recommend(self, drift_score: float, lifecycle: str) -> str:
        """根据漂移分数生成建议。"""
        if lifecycle == Lifecycle.VOLATILE.value:
            return "上游需求频繁变更，建议锁定一版目标后暂停纠正"
        if drift_score >= DRIFT_CRITICAL:
            return "严重偏离——触发重规划，不回滚只纠偏"
        if drift_score >= DRIFT_WARNING:
            return f"轻微偏离（{drift_score:.0%}），检查是否需要调整"
        return "对齐"

    def _log_drift(self, mission: dict, score: float,
                   violations: list, lifecycle: str):
        """记录漂移日志。"""
        mission.setdefault("drift_log", []).append({
            "at": datetime.now().isoformat(),
            "score": score,
            "violations_count": len(violations),
            "lifecycle": lifecycle,
        })

    def _log(self, mission_id: str, action: str, detail: str):
        """写运行日志。"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_DIR / "mission.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {action} {mission_id} | {detail[:200]}\n")


# ── CLI ──────────────────────────────

def main():
    import sys

    mm = MissionManager()

    if len(sys.argv) < 2:
        print("Mission Layer — 长期目标锚点 + 漂移检测")
        print()
        print("子命令:")
        print("  create   <目标> [--criteria c1,c2] [--constraints c1,c2] [--prohibited p1,p2]")
        print("  check    <id> [--violations v1,v2] [--prohibited p1,p2]")
        print("  update   <id> <新目标> --reason '改需求了'")
        print("  list")
        print("  history  <id>")
        return

    cmd = sys.argv[1]

    if cmd == "create":
        args = " ".join(sys.argv[2:])
        goal = sys.argv[2] if len(sys.argv) > 2 else ""
        criteria = []
        constraints = []
        prohibited = []
        for i, arg in enumerate(sys.argv):
            if arg == "--criteria" and i + 1 < len(sys.argv):
                criteria = [c.strip() for c in sys.argv[i + 1].split(",")]
            if arg == "--constraints" and i + 1 < len(sys.argv):
                constraints = [c.strip() for c in sys.argv[i + 1].split(",")]
            if arg == "--prohibited" and i + 1 < len(sys.argv):
                prohibited = [c.strip() for c in sys.argv[i + 1].split(",")]

        m = mm.create(goal, criteria, constraints, prohibited)
        print(f"✅ {m['id']} v{m['version']}: {m['goal']}")
        print(f"   标准: {m['success_criteria']}")
        print(f"   约束: {m['constraints']}")
        print(f"   禁止: {m['prohibited']}")

    elif cmd == "check":
        mid = sys.argv[2] if len(sys.argv) > 2 else ""
        violations = []
        prohibited_triggers = []
        for i, arg in enumerate(sys.argv):
            if arg == "--violations" and i + 1 < len(sys.argv):
                violations = [v.strip() for v in sys.argv[i + 1].split(",")]
            if arg == "--prohibited" and i + 1 < len(sys.argv):
                prohibited_triggers = [v.strip() for v in sys.argv[i + 1].split(",")]

        result = mm.check(mid,
                          violated_constraints=violations,
                          triggered_prohibited=prohibited_triggers)
        if "error" in result:
            print(f"❌ {result['error']}")
            return

        print(f"Mission: {result['goal']} (v{result['version']})")
        print(f"漂移分数: {result['drift_score']:.0%}")
        print(f"生命周期: {result['lifecycle']}")
        if result["violations"]:
            print(f"违规: {len(result['violations'])} 处")
            for v in result["violations"][:5]:
                print(f"  • [{v['type']}] {v['rule'][:60]}")
        print(f"建议: {result['recommendation']}")

    elif cmd == "update":
        mid = sys.argv[2] if len(sys.argv) > 2 else ""
        new_goal = sys.argv[3] if len(sys.argv) > 3 else ""
        reason = ""
        for i, arg in enumerate(sys.argv):
            if arg == "--reason" and i + 1 < len(sys.argv):
                reason = sys.argv[i + 1]

        m = mm.update(mid, new_goal, reason)
        if "error" in m:
            print(f"❌ {m['error']}")
        else:
            print(f"✅ {m['id']} v{m['version']}: {m['goal']}")
            print(f"   生命周期: {m['lifecycle']}")

    elif cmd == "list":
        missions = mm.list_active()
        if not missions:
            print("无活跃 Mission")
        for m in missions:
            print(f"[{m['lifecycle']}] {m['id']} v{m['version']}: {m['goal'][:60]}")

    elif cmd == "history":
        mid = sys.argv[2] if len(sys.argv) > 2 else ""
        versions = mm.history(mid)
        for v in versions:
            print(f"  v{v['version']} [{v['lifecycle']}] {v['goal'][:80]}")
            print(f"    {v['change_reason']} ({v['updated_at'][:19]})")


if __name__ == "__main__":
    main()
