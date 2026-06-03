#!/usr/bin/env python3
"""
Evidence Validator — 证据验证层
===============================

所有事实性声明必须拥有证据链。无证据 → 禁止输出。

原则：No Evidence, No Claim.

数据源：state.db 的 messages 表（与 meta_check.py 共享）

用法：
  from evidence_validator import EvidenceValidator
  ev = EvidenceValidator()

  # 单条验证
  result = ev.validate_claim("已读取 config.yaml", session_id)
  # → {"pass": True, "evidence": ["read_file:config.yaml:42"]}

  # 批量扫描
  violations = ev.scan_output(agent_text, session_id)
  # → [{"claim": "GPT已确认...", "issue": "FABRICATED: 无对应tool call"}]
"""

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

HERMES_HOME = Path.home() / ".hermes"
STATE_DB = HERMES_HOME / "state.db"

# ── 声明 → Tool Call 映射 ────────────
# Agent 在输出中声称做了什么 → 对应的 tool 名称和参数提取

CLAIM_TO_TOOL = [
    # 文件读取
    {
        "pattern": r'(?:已(?:读取|查看|检查|打开)|读了|看过?了?)\s*[「《]?(.{2,80}?)[」》]?\s*(?:文件|代码|日志|配置|文档|内容)',
        "tools": ["read_file"],
        "param_field": "path",
        "param_extractor": lambda m: m.group(1).strip(),
    },
    # 终端执行
    {
        "pattern": r'(?:已(?:执行|运行|调用))\s*(.{2,80})',
        "tools": ["terminal"],
        "param_field": "command",
        "param_extractor": lambda m: m.group(1).strip(),
    },
    # 文件写入
    {
        "pattern": r'(?:已(?:写入|创建|保存|生成|输出))\s*(?:文件\s*)?[「《]?(.{2,80}?)[」》]?',
        "tools": ["write_file"],
        "param_field": "path",
        "param_extractor": lambda m: m.group(1).strip(),
    },
    # Web 搜索
    {
        "pattern": r'(?:已(?:搜索|查询|检索|查找))\s*(.{2,80})',
        "tools": ["web_search"],
        "param_field": "query",
        "param_extractor": lambda m: m.group(1).strip(),
    },
    # 外部引用
    {
        "pattern": r'(?:GPT|Claude|DeepSeek|某\S*?)\s*(?:说|认为|评价|指出|分析|建议)(.{2,80})',
        "tools": ["*"],  # 任意 tool call 都行——至少证明调过外部
        "param_field": None,
        "param_extractor": lambda m: m.group(0).strip(),
    },
    # 提交/推送
    {
        "pattern": r'(?:已(?:提交|推送|commit|push))\s*(.{2,80})',
        "tools": ["terminal"],
        "param_field": "command",
        "param_extractor": lambda m: m.group(0).strip(),
    },
]

# ── 可忽略的非声明 ────────────────────
IGNORE_CLAIMS = [
    r'^(?:我|你|他|她|它)',       # 人称
    r'^(?:可以|应该|需要|建议)',    # 建议
    r'^(?:如果|假设|假如|比如)',    # 条件
    r'[？?！!]$',                    # 疑问
]


class EvidenceValidator:
    """证据验证器 — 所有事实声明必须有 tool call 记录。

    证据质量分级（Evidence ≠ Truth）：
      DIRECT    — 参数精确匹配，confidence 0.95
      FUZZY     — 子串模糊匹配，confidence 0.60
      INDIRECT  — 工具类型对但参数不匹配，或仅有外部引用, confidence 0.30
      NONE      — 无匹配，confidence 0.0
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or STATE_DB

    # ── 核心：验证单条声明 ──────────

    def validate_claim(self, claim: str, session_id: str) -> dict:
        """验证一条声明是否有对应的 tool call 记录。

        Returns:
            {"pass": bool, "claim": str,
             "evidence_quality": "DIRECT"|"FUZZY"|"INDIRECT"|"NONE",
             "confidence": 0.0-0.95, "matched_tool": str | None,
             "evidence": [str], "issue": str | None}
        """
        # 找到这条声明匹配的 tool 类型
        matched_rule = None
        match_obj = None
        for rule in CLAIM_TO_TOOL:
            m = re.search(rule["pattern"], claim)
            if m:
                matched_rule = rule
                match_obj = m
                break

        if not matched_rule:
            return {"pass": True, "claim": claim, "matched_tool": None,
                    "evidence": [], "issue": None, "note": "非事实性声明",
                    "evidence_quality": "DIRECT", "confidence": 1.0}

        # 从 session 中查 tool call 历史
        tool_calls = self._get_session_tool_calls(session_id)
        param_hint = matched_rule["param_extractor"](match_obj) if matched_rule["param_field"] else ""
        target_tools = matched_rule["tools"]

        # 精确匹配
        for tc in tool_calls:
            if "*" in target_tools or tc["name"] in target_tools:
                if matched_rule["param_field"] and param_hint:
                    params = tc.get("params", "")
                    if self._exact_match(param_hint, params):
                        return self._result(True, claim, tc["name"],
                            [f"{tc['name']}:{params[:80]}"], None, "DIRECT", 0.95)
                    if self._fuzzy_match(param_hint, params):
                        return self._result(True, claim, tc["name"],
                            [f"{tc['name']}:{params[:80]}"], None, "FUZZY", 0.60)
                elif "*" in target_tools:
                    return self._result(True, claim, tc["name"],
                        [f"{tc['name']}:{tc.get('params', '')[:80]}"],
                        None, "INDIRECT", 0.30)

        # 工具类型匹配但参数不匹配 → 间接证据
        for tc in tool_calls:
            if tc["name"] in target_tools:
                return self._result(True, claim, tc["name"],
                    [f"{tc['name']}:{tc.get('params', '')[:80]}"],
                    "INDIRECT_MATCH: 工具类型正确但参数不匹配", "INDIRECT", 0.30)

        # 完全没匹配
        return self._result(False, claim,
            target_tools[0] if target_tools else None,
            [],
            f"FABRICATED: 声称执行了 {target_tools} 但 session 中无匹配记录",
            "NONE", 0.0)

    @staticmethod
    def _result(pass_val, claim, tool, evidence, issue, quality, confidence):
        return {"pass": pass_val, "claim": claim, "matched_tool": tool,
                "evidence": evidence, "issue": issue,
                "evidence_quality": quality, "confidence": confidence}

    # ── 批量扫描 ────────────────────

    def scan_output(self, text: str, session_id: str,
                    min_confidence: float = 0.30) -> list[dict]:
        """扫描整个输出，提取所有事实性声明并逐条验证。

        min_confidence: 低于此阈值的声明视为违规。默认 0.30（至少 INDIRECT）。

        Returns:
            违规列表。空列表 = 全部通过。
        """
        violations = []
        claims = self._extract_claims(text)

        for claim in claims:
            result = self.validate_claim(claim, session_id)
            if result["confidence"] < min_confidence:
                violations.append(result)

        return violations

    # ── 证据链回溯 ──────────────────

    def get_evidence_chain(self, claim: str, session_id: str) -> list[dict]:
        """回溯完整证据链——从声明追溯到原始 tool call 及其上下文。"""
        result = self.validate_claim(claim, session_id)
        quality = result.get("evidence_quality", "NONE")
        confidence = result.get("confidence", 0.0)

        if quality == "NONE":
            return [{"level": "claim", "content": claim,
                     "status": f"UNVERIFIED ({quality})"}]

        tool_name = result["matched_tool"]
        tool_calls = self._get_session_tool_calls(session_id)

        chain = [{"level": "claim", "content": claim,
                  "status": f"VERIFIED_{quality} ({confidence:.0%})"}]

        for tc in tool_calls:
            if tc["name"] == tool_name:
                chain.append({
                    "level": "tool_call",
                    "content": f"{tc['name']}({tc.get('params', '')[:120]})",
                    "status": "RECORDED",
                    "timestamp": tc.get("timestamp", "unknown"),
                })
                break

        return chain

    # ── 内部：从 state.db 读 tool calls ──

    def _get_session_tool_calls(self, session_id: str) -> list[dict]:
        """获取 session 中所有 tool call 记录。"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, tool_name, tool_calls, timestamp FROM messages "
            "WHERE session_id = ? AND observed = 1 "
            "ORDER BY id",
            (session_id,),
        )
        rows = cursor.fetchall()
        conn.close()

        tool_calls = []
        for msg_id, tool_name, tc_json, ts in rows:
            if tool_name:
                tool_calls.append({
                    "msg_id": msg_id,
                    "name": tool_name,
                    "params": "",
                    "timestamp": ts,
                })
            elif tc_json:
                try:
                    calls = json.loads(tc_json)
                    for c in calls:
                        f = c.get("function", {})
                        tool_calls.append({
                            "msg_id": msg_id,
                            "name": f.get("name", ""),
                            "params": json.dumps(f.get("arguments", {}), ensure_ascii=False),
                            "timestamp": ts,
                        })
                except Exception:
                    pass
        return tool_calls

    # ── 内部：文本提取 ──────────────

    def _extract_claims(self, text: str) -> list[str]:
        """从文本中提取事实性声明句子。"""
        claims = []
        sentences = re.split(r'[。！!？?\n]', text)

        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue
            if any(re.search(p, sent) for p in IGNORE_CLAIMS):
                continue

            # 是否匹配任何声明模式
            for rule in CLAIM_TO_TOOL:
                if re.search(rule["pattern"], sent):
                    claims.append(sent)
                    break

        return claims

    # ── 内部：匹配 ──────────────

    @staticmethod
    def _exact_match(hint: str, params: str) -> bool:
        """精确匹配：hint 作为完整词出现在 params 中。"""
        if not hint or not params:
            return False
        hint_clean = re.sub(r'[「」《》\s]', '', hint)
        if len(hint_clean) < 3:
            return False
        # 完整路径/命令名匹配
        return hint_clean in params

    @staticmethod
    def _fuzzy_match(hint: str, params: str) -> bool:
        """检查 hint 是否在 params 中（子串匹配）。"""
        if not hint or not params:
            return False
        # 取 hint 中最长的有意义片段
        hint_clean = re.sub(r'[「」《》\s]', '', hint)
        if len(hint_clean) < 3:
            return False
        return hint_clean.lower() in params.lower()


# ── CLI ──────────────────────────────

def main():
    import sys

    ev = EvidenceValidator()

    if len(sys.argv) < 2:
        print("Evidence Validator — No Evidence, No Claim")
        print()
        print("子命令:")
        print("  validate <声明> --session <id>    验证单条声明")
        print("  scan <文本> --session <id>        扫描输出文本")
        print("  chain <声明> --session <id>       回溯证据链")
        return

    cmd = sys.argv[1]

    # 解析 --session
    session_id = ""
    for i, arg in enumerate(sys.argv):
        if arg == "--session" and i + 1 < len(sys.argv):
            session_id = sys.argv[i + 1]

    if not session_id:
        # 尝试从 meta_check 的方式获取当前 session
        conn = sqlite3.connect(str(STATE_DB))
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        session_id = row[0] if row else ""

    if cmd == "validate":
        claim = " ".join(sys.argv[2:]).replace(" --session " + session_id, "").strip()
        result = ev.validate_claim(claim, session_id)
        quality = result.get("evidence_quality", "?")
        conf = result.get("confidence", 0)
        if result["pass"]:
            print(f"✅ {quality} ({conf:.0%}) {result.get('note', '')}")
            if result["evidence"]:
                print(f"   证据: {result['evidence']}")
        else:
            print(f"❌ {quality} ({conf:.0%}) {result['issue']}")

    elif cmd == "scan":
        text = " ".join(sys.argv[2:]).replace(" --session " + session_id, "").strip()
        if not text:
            text = sys.stdin.read().strip()
        violations = ev.scan_output(text, session_id)
        if violations:
            print(f"发现 {len(violations)} 处低置信度声明 (<0.30):")
            for v in violations:
                print(f"  ❌ [{v.get('evidence_quality','?')}] {v['claim'][:60]}")
                print(f"     {v['issue']}")
        else:
            print("✅ 所有声明有证据支撑 (≥INDIRECT)")

    elif cmd == "chain":
        claim = " ".join(sys.argv[2:]).replace(" --session " + session_id, "").strip()
        chain = ev.get_evidence_chain(claim, session_id)
        for item in chain:
            print(f"[{item['status']}] {item['content'][:100]}")


if __name__ == "__main__":
    main()
