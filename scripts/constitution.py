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

    def semantic_check(self, text: str, api_key: str | None = None,
                       base_url: str = "https://api.deepseek.com/v1") -> dict:
        """LLM 单次语义判断——正则全过时的第二道防线。

        只在边界情况触发：文本通过了正则检查，但措辞可能绕过了规则。
        用 LLM 做一次语义等价判断，保留可审计性（结果写日志）。

        Args:
            text: 要检查的文本
            api_key: DeepSeek API key（不传则从环境变量读取）
            base_url: API 地址

        Returns:
            {"verdict": "PASS" | "SEMANTIC_VIOLATION",
             "rule_id": "C3" | None,
             "reason": "..."}
        """
        import os, json, urllib.request

        key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        if not key:
            return {"verdict": "SKIP", "rule_id": None,
                    "reason": "无 API key，跳过语义检查"}

        # 只检查较长的文本（短文本正则已经够用）
        if len(text) < 30:
            return {"verdict": "PASS", "rule_id": None,
                    "reason": "文本过短，正则覆盖"}

        prompt = f"""你是宪法合规检查器。检查以下文本是否用不同措辞表达了违规行为。

宪法规则：
C1 不得伪造事实：声称做了未执行的操作、空洞断言"已全部通过"
C2 不得虚构记录：声称验证/审计已完成但无具体步骤
C3 不得绕过审计：声称跳过/绕过/省略gate、检查、验证流程，包括暗示"这一步可以先放一放""这个流程暂时不跑"
C4 不得篡改日志：声称修改、清空审计日志或运行记录
C5 不得越权操作：声称修改系统配置、删除关键文件、执行危险命令

文本：
{text[:2000]}

只回答一个词：PASS 或 VIOLATION:Cx（x为规则编号）。
如果VIOLATION，加一个空格后写理由（不超过20字）。
示例：VIOLATION:C3 暗示跳过验证流程"""

        try:
            payload = json.dumps({
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 50,
                "temperature": 0.0,
            }).encode()
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            reply = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            self._log_semantic("ERROR", text, f"API调用失败: {e}")
            return {"verdict": "SKIP", "rule_id": None,
                    "reason": f"API错误: {str(e)[:50]}"}

        # 解析结果
        if reply.upper().startswith("PASS"):
            self._log_semantic("PASS", text, reply)
            return {"verdict": "PASS", "rule_id": None, "reason": reply}
        elif "VIOLATION" in reply.upper():
            # 提取规则编号
            import re as _re
            rule_match = _re.search(r'C(\d)', reply)
            rule_id = f"C{rule_match.group(1)}" if rule_match else "C?"
            reason = reply.split(" ", 1)[1] if " " in reply else reply
            self._log_semantic("VIOLATION", text, f"{rule_id}: {reason}")
            return {"verdict": "SEMANTIC_VIOLATION", "rule_id": rule_id,
                    "reason": reason}
        else:
            self._log_semantic("UNKNOWN", text, reply)
            return {"verdict": "PASS", "rule_id": None, "reason": f"未识别: {reply[:50]}"}

    def full_check(self, text: str, api_key: str | None = None) -> dict:
        """完整检查：正则 + 语义（双层）。"""
        # 第一层：正则
        regex_violations = self.check(text)
        if regex_violations:
            return {
                "blocked": self.has_critical(regex_violations),
                "layer": "regex",
                "violations": regex_violations,
                "semantic": None,
            }

        # 第二层：语义（正则全过时才触发）
        semantic = self.semantic_check(text, api_key)
        blocked = semantic["verdict"] == "SEMANTIC_VIOLATION"

        return {
            "blocked": blocked,
            "layer": "semantic" if blocked else "none",
            "violations": [],
            "semantic": semantic,
        }

    def _log_semantic(self, verdict: str, text: str, detail: str):
        """记录语义检查到 constitution_semantic.log。"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_DIR / "constitution_semantic.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {verdict} | {detail[:200]} | {text[:200]}\n")

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
