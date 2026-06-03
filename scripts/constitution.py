#!/usr/bin/env python3
"""
Constitution Layer — 系统级硬约束
================================

所有 Agent 输出的前置检查。任何输出违反宪法 → 拦截。

五条硬约束（Mission 不得覆盖）：
  1. 不得伪造事实    — 输出不得声称做了未执行的操作
  2. 不得虚构记录    — 不得声称验证/审计步骤已通过
  3. 不得绕过审计    — 不得声称跳过了 Gate/Check/Evidence
  4. 不得篡改日志    — 不得声称修改了审计日志/运行记录
  5. 不得越权操作    — 不得声称修改系统配置/删除关键文件

架构位置：Evidence Validator 之前。
因为伪造本身就是违规——不需要先验证证据。

用法：
  from constitution import Constitution
  c = Constitution()
  violations = c.check(agent_output_text)
  if violations:
      # 拦截或插入警告
"""

import re
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "logs"

# ── 宪法规则 ──────────────────────────

RULES = [
    {
        "id": "C1",
        "name": "NO_FABRICATED_FACTS",
        "severity": "CRITICAL",
        "description": "不得伪造事实",
        # 检测：声称读取/执行了不存在的操作（无对应 tool call 时最明显）
        # 这里用"已完成"+"不可能同时完成的组合"作为强信号
        "patterns": [
            # 同一句中同时声称多个互斥操作
            r'(?:已完成|已确认|已验证).{0,30}(?:且|并|同时).{0,30}(?:已完成|已确认)',
            # 声称"已全部通过"但没有具体条目
            r'已全部通过.{0,20}(?:验证|检查|审计|测试)',
            # 空洞的事实断言
            r'(?:经过|通过)(?:了)?(?:全面|完整|严格)(?:的)?(?:验证|测试|审查)',
        ],
    },
    {
        "id": "C2",
        "name": "NO_FABRICATED_RECORDS",
        "severity": "CRITICAL",
        "description": "不得虚构执行记录",
        "patterns": [
            # 声称执行了验证但没有实际的 verify 步骤
            r'(?:已执行|已完成)\s*(?:验证|校验|检查).{0,20}(?:闭环|通过|完成)',
            r'(?:predict\.py|meta_check|evidence_validator)\s*(?:已执行|已完成|通过)',
        ],
    },
    {
        "id": "C3",
        "name": "NO_BYPASS_AUDIT",
        "severity": "CRITICAL",
        "description": "不得绕过审计",
        "patterns": [
            # 声称跳过了关键流程
            r'(?:跳过|绕过|省略)(?:了)?\s*(?:gate|检查|验证|审计|审核)',
            r'(?:不用|不需要|不需要过)\s*(?:gate|检查|验证|审计)',
            r'直接\s*(?:执行|动手|开始).{0,20}(?:不|不用|跳过)',
        ],
    },
    {
        "id": "C4",
        "name": "NO_TAMPER_LOGS",
        "severity": "CRITICAL",
        "description": "不得篡改审计日志",
        "patterns": [
            r'(?:修改|删除|清空|清除)(?:了)?\s*(?:日志|审计|记录|log)',
            r'(?:改|动)(?:了)?\s*(?:gate\.log|check\.log|\.hermes/logs)',
        ],
    },
    {
        "id": "C5",
        "name": "NO_UNAUTHORIZED_OPS",
        "severity": "HIGH",
        "description": "不得越权操作",
        "patterns": [
            r'(?:删除|卸载|移除)(?:了)?\s*(?:系统|关键|核心)',
            r'(?:修改|改动)(?:了)?\s*(?:系统配置|config\.yaml|\.env)',
            r'(?:执行|运行)(?:了)?\s*(?:rm\s+-rf|DROP\s+TABLE|DELETE\s+FROM)',
            r'chmod\s+777',
            r'>\s*/dev/\w+',  # 重定向覆盖设备文件
        ],
    },
]

# ── 严重度排序 ──────────────────────
SEVERITY_ORDER = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}


class Constitution:
    """宪法层——所有 Agent 输出的硬约束前置检查。"""

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def check(self, text: str) -> list[dict]:
        """扫描输出文本，返回违反宪法的条目。

        Returns:
            [{"rule_id": "C1", "rule_name": "NO_FABRICATED_FACTS",
              "severity": "CRITICAL", "matched": "...", "position": 42}]
        """
        violations = []

        for rule in RULES:
            for pattern in rule["patterns"]:
                for m in re.finditer(pattern, text):
                    violations.append({
                        "rule_id": rule["id"],
                        "rule_name": rule["name"],
                        "severity": rule["severity"],
                        "description": rule["description"],
                        "matched": m.group(0)[:120],
                        "position": m.start(),
                    })

        # 去重（同位置同规则只报一次）
        seen = set()
        unique = []
        for v in violations:
            key = (v["rule_id"], v["position"])
            if key not in seen:
                seen.add(key)
                unique.append(v)

        # 按严重度排序
        unique.sort(key=lambda x: -SEVERITY_ORDER.get(x["severity"], 0))

        if unique:
            self._log(unique, text)

        return unique

    def has_critical(self, violations: list[dict]) -> bool:
        """是否有 CRITICAL 级别的违规。"""
        return any(v["severity"] == "CRITICAL" for v in violations)

    def format_violations(self, violations: list[dict]) -> str:
        """格式化违规报告。"""
        if not violations:
            return ""

        lines = ["⚠️ 宪法违规 — 以下输出违反系统硬约束：", ""]
        for v in violations[:5]:
            lines.append(f"  [{v['rule_id']}] {v['rule_name']} ({v['severity']})")
            lines.append(f"       {v['description']}")
            lines.append(f"       匹配: \"{v['matched'][:80]}\"")
            lines.append("")
        return "\n".join(lines)

    def _log(self, violations: list[dict], text: str):
        """记录违规到 constitution.log。"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rule_ids = ",".join(v["rule_id"] for v in violations[:3])
        with open(LOG_DIR / "constitution.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] VIOLATIONS={rule_ids} count={len(violations)} | {text[:200]}\n")


# ── CLI ──────────────────────────────

def main():
    import sys

    c = Constitution()

    if len(sys.argv) < 2:
        print("Constitution Layer — 系统级硬约束")
        print()
        print(f"规则: {len(RULES)} 条")
        for r in RULES:
            print(f"  [{r['id']}] {r['name']} ({r['severity']}) — {r['description']}")
        print()
        print("用法:")
        print("  echo '输出文本' | python3 constitution.py")
        print("  python3 constitution.py '输出文本'")
        return

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()

    if not text:
        print("用法: echo '输出文本' | python3 constitution.py")
        return

    violations = c.check(text)
    if violations:
        print(c.format_violations(violations))
        print(f"共 {len(violations)} 处违规")
        if c.has_critical(violations):
            print("⛔ 含 CRITICAL 级别违规 — 建议拦截此输出")
    else:
        print("✅ 无宪法违规")


if __name__ == "__main__":
    main()
