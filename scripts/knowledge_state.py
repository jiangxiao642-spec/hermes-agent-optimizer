#!/usr/bin/env python3
"""
Knowledge State Manager — 认知状态系统
======================================

所有信息必须标记来源状态。四个状态硬边界：

  VERIFIED    — 已验证事实（有工具调用记录/文件内容/用户确认）
  INFERRED    — 基于证据推导（有逻辑链但不是直接读出）
  HYPOTHESIS  — 假设（合理但未验证）
  UNKNOWN     — 未知（必须承认不知道）

禁止将 INFERRED 输出为 VERIFIED。

存储：~/.hermes/knowledge_state/items.jsonl

用法：
  from knowledge_state import KnowledgeStateManager
  ksm = KnowledgeStateManager()

  # 标记
  ksm.mark("config.yaml 中 base_url 指向 localhost:8000",
           state="VERIFIED", source="file_read",
           evidence_refs=["read_file:config.yaml:line42"])

  # 输出前检查
  violations = ksm.check(agent_output_text)
  # → [{"claim": "GPT已确认...", "issue": "UNVERIFIED: 无对应证据"}]
"""

import json
import os
import re
from datetime import datetime
from pathlib import Path
from enum import Enum


class State(Enum):
    VERIFIED_HIGH = "VERIFIED_HIGH"    # 直接证据（DIRECT）
    VERIFIED_LOW = "VERIFIED_LOW"      # 间接证据（FUZZY/INDIRECT）
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


VALID_STATES = {s.value for s in State}
DEFAULT_HOME = Path.home() / ".hermes"
DEFAULT_DIR = DEFAULT_HOME / "knowledge_state"
DEFAULT_FILE = DEFAULT_DIR / "items.jsonl"

# ── 输出规则 ──────────────────────────
OUTPUT_RULES = {
    "VERIFIED_HIGH": "允许作为事实陈述（直接证据）",
    "VERIFIED_LOW": "允许陈述但建议标注证据质量（间接证据）",
    "INFERRED": "必须声明为推测（'基于X推断Y'）",
    "HYPOTHESIS": "必须声明为假设（'假设X成立，则Y'）",
    "UNKNOWN": "必须承认不知道",
}

# ── 禁止转换 ──────────────────────────
TRANSITION_ALLOWED = {
    "UNKNOWN": {"VERIFIED_HIGH": False, "VERIFIED_LOW": False, "INFERRED": False, "HYPOTHESIS": True, "UNKNOWN": True},
    "HYPOTHESIS": {"VERIFIED_HIGH": False, "VERIFIED_LOW": False, "INFERRED": True, "HYPOTHESIS": True, "UNKNOWN": False},
    "INFERRED": {"VERIFIED_HIGH": True, "VERIFIED_LOW": True, "INFERRED": True, "HYPOTHESIS": False, "UNKNOWN": False},
    "VERIFIED_LOW": {"VERIFIED_HIGH": True, "VERIFIED_LOW": True, "INFERRED": False, "HYPOTHESIS": False, "UNKNOWN": False},
    "VERIFIED_HIGH": {"VERIFIED_HIGH": True, "VERIFIED_LOW": True, "INFERRED": False, "HYPOTHESIS": False, "UNKNOWN": False},
}

# ── 事实性声明检测模式 ─────────────────
# Agent 输出中哪些句子是"事实性声明"需要检查
CLAIM_PATTERNS = [
    # 文件读取声明
    (r'(?:已(?:读取|查看|检查|打开)|读过?了?)\s*[「《]?(.{2,80}?)[」》]?\s*(?:文件|代码|日志|配置|文档)', "file_read"),
    # 工具调用声明
    (r'(?:已(?:执行|运行|调用|完成|启动|停止|部署|安装|卸载|打包|提交|推送))\s*(.{2,80})', "tool_call"),
    # 外部信息引用
    (r'(?:GPT|Claude|DeepSeek|某\S*?)\s*(?:说|认为|评价|指出|分析|建议|反馈|回复|确认|表示)(.{2,80})', "external_ref"),
    # 数据声明
    (r'(?:共|总计|结果|输出|返回)\s*[是为有]\s*(.{2,80})', "data_claim"),
    # 断言式
    (r'(?:确实|显然|无疑|肯定|一定|必然)\s*(.{3,80})', "assertion"),
]

# ── 可忽略的非事实性表述 ──────────────
IGNORE_PATTERNS = [
    r'^[我你他她]',           # 人称开头
    r'^(?:可以|应该|需要|建议|推荐)',  # 建议类
    r'^(?:如果|假设|假如|比如|例如)',  # 条件/举例
    r'^(?:但是|不过|然而|所以|因此)',  # 转折/因果
    r'[？?！!。，,、]$',         # 疑问/感叹结尾
]


class KnowledgeStateManager:
    """认知状态管理器。"""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DEFAULT_DIR
        self.data_file = self.data_dir / "items.jsonl"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    # ── 标记 ────────────────────────

    def mark(self, content: str, state: str, source: str,
             evidence_refs: list[str] | None = None) -> dict:
        """标记一条知识。

        Args:
            content: 事实陈述（用自己的话复述）
            state: VERIFIED | INFERRED | HYPOTHESIS | UNKNOWN
            source: tool_call | file_read | web_search | user_input | derived
            evidence_refs: 证据引用列表，如 ["read_file:config.yaml:42", "terminal:curl:0"]

        Returns:
            {"id": "20260602_143022", "content": "...", "state": "VERIFIED", ...}
        """
        if state not in VALID_STATES:
            raise ValueError(f"无效状态: {state}，有效值: {VALID_STATES}")

        entry = {
            "id": datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:18],
            "content": content.strip(),
            "state": state,
            "source": source,
            "evidence_refs": evidence_refs or [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        with open(self.data_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    # ── 查询 ────────────────────────

    def get(self, content: str) -> dict | None:
        """精确查找（子串匹配）。返回最新一条。"""
        if not self.data_file.exists():
            return None
        with open(self.data_file, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]
        matches = [i for i in items if content in i["content"]]
        return matches[-1] if matches else None

    def query(self, state: str | None = None, source: str | None = None,
              limit: int = 20) -> list[dict]:
        """按状态/来源查询。"""
        if not self.data_file.exists():
            return []
        with open(self.data_file, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]

        if state:
            items = [i for i in items if i["state"] == state]
        if source:
            items = [i for i in items if i["source"] == source]

        return items[-limit:]

    # ── 升级 ────────────────────────

    def upgrade(self, content: str, new_state: str,
                evidence_ref: str | None = None) -> dict | None:
        """升级状态（需提供证据）。

        UNKNOWN → HYPOTHESIS → INFERRED → VERIFIED
        每个升级都需要新的 evidence_ref。
        """
        existing = self.get(content)
        if not existing:
            return None

        old_state = existing["state"]
        if not TRANSITION_ALLOWED.get(old_state, {}).get(new_state, False):
            raise ValueError(
                f"不允许 {old_state} → {new_state}。"
                f"允许: {[k for k, v in TRANSITION_ALLOWED.get(old_state, {}).items() if v]}"
            )

        entry = {
            **existing,
            "state": new_state,
            "updated_at": datetime.now().isoformat(),
        }
        if evidence_ref:
            entry["evidence_refs"] = list(set(existing.get("evidence_refs", []) + [evidence_ref]))

        # 追加新版本（保留旧版本在日志中）
        with open(self.data_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        return entry

    # ── 输出检查 ────────────────────

    def check(self, text: str) -> list[dict]:
        """扫描输出文本，查找未标记状态的事实性声明。

        Returns:
            [{"claim": "...", "pattern": "file_read", "issue": "UNVERIFIED: 未找到状态记录"}]
        """
        violations = []
        sentences = self._extract_claims(text)

        for sent, pattern_type in sentences:
            existing = self.get(sent)
            if not existing:
                violations.append({
                    "claim": sent,
                    "pattern": pattern_type,
                    "issue": "UNREGISTERED: 未在 knowledge_state 中标记",
                    "action": "需要 mark() 或声明为 UNKNOWN",
                })
            elif existing["state"] in ("INFERRED", "HYPOTHESIS"):
                # 检查是否违反了输出规则
                # INFERRED 输出时必须带"基于X推断"
                if existing["state"] == "INFERRED":
                    if not any(w in sent for w in ["推断", "推测", "根据", "基于"]):
                        violations.append({
                            "claim": sent,
                            "pattern": pattern_type,
                            "issue": f"INFERRED_AS_FACT: 状态={existing['state']}但未声明推测",
                            "action": "加前缀：'根据X推断，Y'",
                        })

        return violations

    def _extract_claims(self, text: str) -> list[tuple[str, str]]:
        """从文本中提取事实性声明。"""
        claims = []

        # 按句子分割
        sentences = re.split(r'[。！!？?\n]', text)
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 5:
                continue

            # 跳过非事实性表述
            if any(re.search(p, sent) for p in IGNORE_PATTERNS):
                continue

            # 匹配声明模式
            for pattern, ptype in CLAIM_PATTERNS:
                m = re.search(pattern, sent)
                if m:
                    claims.append((sent, ptype))
                    break

        return claims

    # ── 统计 ────────────────────────

    def stats(self) -> dict:
        """知识库统计。"""
        if not self.data_file.exists():
            return {"total": 0, "by_state": {}, "by_source": {}}

        with open(self.data_file, "r", encoding="utf-8") as f:
            items = [json.loads(line) for line in f if line.strip()]

        by_state = {}
        by_source = {}
        for item in items:
            s = item["state"]
            by_state[s] = by_state.get(s, 0) + 1
            src = item["source"]
            by_source[src] = by_source.get(src, 0) + 1

        return {
            "total": len(items),
            "by_state": by_state,
            "by_source": by_source,
        }


# ── CLI ──────────────────────────────

def main():
    import sys

    ksm = KnowledgeStateManager()

    if len(sys.argv) < 2:
        print("Knowledge State Manager")
        print()
        print("子命令:")
        print("  mark    <内容> --state VERIFIED --source file_read [--evidence ref1,ref2]")
        print("  check   <文本>                    扫描输出中的事实性声明")
        print("  query   [--state VERIFIED] [--source file_read]")
        print("  upgrade <内容> --to INFERRED --evidence ref")
        print("  stats")
        return

    cmd = sys.argv[1]

    if cmd == "mark":
        # 简单 CLI：后两个参数是内容和状态
        args = " ".join(sys.argv[2:])
        state = "UNKNOWN"
        source = "user_input"
        if "--state" in args:
            m = re.search(r'--state\s+(\w+)', args)
            if m:
                state = m.group(1)
        if "--source" in args:
            m = re.search(r'--source\s+(\w+)', args)
            if m:
                source = m.group(1)
        content = re.sub(r'\s*--\w+.*$', '', " ".join(sys.argv[2:])).strip()
        entry = ksm.mark(content, state=state, source=source)
        print(json.dumps(entry, ensure_ascii=False, indent=2))

    elif cmd == "check":
        text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else sys.stdin.read().strip()
        violations = ksm.check(text)
        if violations:
            print(f"发现 {len(violations)} 处违规:")
            for v in violations:
                print(f"  ❌ {v['claim'][:60]}")
                print(f"     {v['issue']}")
                print(f"     → {v['action']}")
        else:
            print("✅ 所有事实性声明已标记")

    elif cmd == "query":
        state = None
        source = None
        for i, arg in enumerate(sys.argv):
            if arg == "--state" and i + 1 < len(sys.argv):
                state = sys.argv[i + 1]
            if arg == "--source" and i + 1 < len(sys.argv):
                source = sys.argv[i + 1]
        items = ksm.query(state=state, source=source)
        for item in items:
            print(f"[{item['state']}] {item['content'][:80]}")

    elif cmd == "upgrade":
        content = sys.argv[2] if len(sys.argv) > 2 else ""
        new_state = "VERIFIED"
        evidence = None
        for i, arg in enumerate(sys.argv):
            if arg == "--to" and i + 1 < len(sys.argv):
                new_state = sys.argv[i + 1]
            if arg == "--evidence" and i + 1 < len(sys.argv):
                evidence = sys.argv[i + 1]
        try:
            entry = ksm.upgrade(content, new_state, evidence)
            print(f"✅ {entry['state']}: {content[:60]}")
        except ValueError as e:
            print(f"❌ {e}")

    elif cmd == "stats":
        s = ksm.stats()
        print(f"总计: {s['total']} 条")
        print(f"按状态: {s['by_state']}")
        print(f"按来源: {s['by_source']}")


if __name__ == "__main__":
    main()
