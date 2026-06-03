#!/usr/bin/env python3
"""
Experience Engine — 从"观察→记录"到"观察→改变行为"
====================================================

读取 predict/forget/meta 三个模块的原始输出，
生成可被下次运行时自动加载的经验产物。

四条学习管线：
  1. predict 偏差 → 聚类 → 修正因子 → factors.json
  2. forget 摘要 → 模式提取 → if-then 规则 → rules.json
  3. meta 违规 → 聚类 → 阈值调整 → thresholds.json
  4. constitution 语义 → 短语提取 → 正则模式 → constitution_patterns.json

经验存储：~/.hermes/experience/

用法：
  python3 experience_engine.py run          # 运行全部三条管线
  python3 experience_engine.py factors      # 只跑 predict 管线
  python3 experience_engine.py rules        # 只跑 forget 管线
  python3 experience_engine.py thresholds   # 只跑 meta 管线
  python3 experience_engine.py status       # 查看经验状态
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict, Counter

HERMES_HOME = Path.home() / ".hermes"
EXPERIENCE_DIR = HERMES_HOME / "experience"

# ── 数据源 ────────────────────────────
PREDICT_DEVIATIONS = HERMES_HOME / "predictions" / "deviations.jsonl"
FORGET_ARCHIVE = HERMES_HOME / "brainstem" / "thoughts_archive.jsonl"
META_PENDING = HERMES_HOME / "brainstem" / "pending_meta.txt"
CONSTITUTION_SEMANTIC_LOG = HERMES_HOME / "logs" / "constitution_semantic.log"

# ── 产物 ──────────────────────────────
FACTORS_FILE = EXPERIENCE_DIR / "factors.json"
RULES_FILE = EXPERIENCE_DIR / "rules.json"
THRESHOLDS_FILE = EXPERIENCE_DIR / "thresholds.json"
PATTERNS_FILE = EXPERIENCE_DIR / "constitution_patterns.json"

# ── 阈值 ──────────────────────────────
MIN_SAMPLES = 5          # 至少需要这么多样本才生成经验
MIN_CONFIDENCE = 0.3     # 规则最低置信度
MAX_RULES = 20           # 最多保留多少条规则


class ExperienceEngine:
    """统一学习引擎。"""

    def __init__(self):
        EXPERIENCE_DIR.mkdir(parents=True, exist_ok=True)

    # ═══════════════════════════════════
    # 管线 1: Predict → Factors
    # ═══════════════════════════════════

    def learn_factors(self) -> dict:
        """从 predict 偏差日志聚类，生成修正因子。

        Returns:
            {"factors": [...], "samples": 42, "generated_at": "..."}
        """
        deviations = self._read_jsonl(PREDICT_DEVIATIONS)
        if len(deviations) < MIN_SAMPLES:
            return {"factors": [], "samples": len(deviations),
                    "note": f"样本不足（需≥{MIN_SAMPLES}）"}

        # 按预测内容聚类关键词
        clusters = defaultdict(list)
        for d in deviations:
            pred = d.get("prediction", "")
            # 提取主题词
            topic = self._extract_topic(pred)
            clusters[topic].append(d)

        factors = []
        for topic, items in clusters.items():
            if len(items) < 3:
                continue

            # 计算实际偏差幅度
            high_conf = [d for d in items if d.get("confidence", 0) >= 0.7]
            if not high_conf:
                continue

            overconfident = len(high_conf) / len(items)
            # 如果高置信预测频繁偏差 → 该领域需要修正
            if overconfident >= 0.3:
                factor = {
                    "domain": topic,
                    "type": "overconfidence",
                    "samples": len(items),
                    "error_rate": round(overconfident, 2),
                    "adjustment": "reduce_confidence",
                    "multiplier": max(0.5, 1.0 - overconfident * 0.5),
                    "generated_at": datetime.now().isoformat(),
                }
                factors.append(factor)

        # 写产物
        result = {
            "version": self._next_version(FACTORS_FILE),
            "factors": factors,
            "samples": len(deviations),
            "clusters": len(clusters),
            "generated_at": datetime.now().isoformat(),
        }
        self._write_json(FACTORS_FILE, result)
        return result

    # ═══════════════════════════════════
    # 管线 2: Forget → Rules
    # ═══════════════════════════════════

    def extract_rules(self) -> dict:
        """从 forget 压缩摘要中提炼 if-then 规则。

        Returns:
            {"rules": [...], "samples": N, "generated_at": "..."}
        """
        archives = self._read_jsonl(FORGET_ARCHIVE)
        if not archives:
            return {"rules": [], "samples": 0, "note": "无归档数据"}

        # 从归档摘要中提取模式
        patterns = []
        for arch in archives:
            # 支持 JSON 和纯文本
            if isinstance(arch, dict):
                text = arch.get("summary", arch.get("raw", ""))
            else:
                text = str(arch)
            if isinstance(text, str):
                # 提取 "X分布" 或 "Y分类" 的模式
                for m in re.finditer(r'(\w+)(?:分布|分类|频率)[：:]\s*(.+)', str(text)):
                    detail_text = m.group(2)
                    # 逗号分隔的子项各自算一条
                    for item in re.split(r'[,，]', detail_text):
                        item = item.strip()
                        if item:
                            patterns.append({"category": m.group(1), "detail": item})

        # 按类别聚合
        rules = []
        by_cat = defaultdict(list)
        for p in patterns:
            by_cat[p["category"]].append(p)

        for cat, items in by_cat.items():
            if len(items) < 3:
                continue

            # 找最常见模式
            details = [i["detail"] for i in items]
            most_common = Counter(details).most_common(1)[0]
            confidence = most_common[1] / len(details)

            if confidence >= MIN_CONFIDENCE:
                rules.append({
                    "condition": f"任务涉及 {cat}",
                    "action": f"检查 {cat} 相关: {most_common[0][:80]}",
                    "confidence": round(confidence, 2),
                    "samples": len(items),
                    "source": "forget",
                    "generated_at": datetime.now().isoformat(),
                })

        # 按置信度排序，保留前 MAX_RULES
        rules.sort(key=lambda x: -x["confidence"])
        rules = rules[:MAX_RULES]

        result = {
            "version": self._next_version(RULES_FILE),
            "rules": rules,
            "samples": len(patterns),
            "generated_at": datetime.now().isoformat(),
        }
        self._write_json(RULES_FILE, result)
        return result

    # ═══════════════════════════════════
    # 管线 3: Meta → Thresholds
    # ═══════════════════════════════════

    def adjust_thresholds(self) -> dict:
        """从 meta 违规记录聚类，生成阈值调整建议。

        Returns:
            {"thresholds": [...], "samples": N, "generated_at": "..."}
        """
        if not META_PENDING.exists():
            return {"thresholds": [], "samples": 0, "note": "无违规记录"}

        with open(META_PENDING, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if len(lines) < MIN_SAMPLES:
            return {"thresholds": [], "samples": len(lines),
                    "note": f"样本不足（需≥{MIN_SAMPLES}）"}

        # 按违规类型聚类
        violations = defaultdict(list)
        for line in lines:
            # 提取违规类型关键词
            if "未验证" in line or "verify" in line.lower():
                violations["verify_skip"].append(line)
            elif "未标记" in line or "unregistered" in line.lower():
                violations["unregistered"].append(line)
            elif "绕过" in line or "跳过" in line or "bypass" in line.lower():
                violations["bypass"].append(line)
            elif "Gate" in line or "gate" in line.lower():
                violations["gate_skip"].append(line)
            elif "skill" in line.lower():
                violations["skill_skip"].append(line)
            else:
                violations["other"].append(line)

        thresholds = []
        for vtype, items in violations.items():
            if len(items) < 3:
                continue

            severity = len(items) / max(len(lines), 1)
            current_level = self._get_current_threshold(vtype)

            if severity >= 0.3 and current_level != "HARD_BLOCK":
                thresholds.append({
                    "violation_type": vtype,
                    "count": len(items),
                    "severity": round(severity, 2),
                    "old_level": current_level,
                    "new_level": "HARD_BLOCK" if severity >= 0.5 else "SOFT_BLOCK",
                    "reason": f"过去记录中 {vtype} 占 {severity:.0%}",
                    "generated_at": datetime.now().isoformat(),
                })

        result = {
            "version": self._next_version(THRESHOLDS_FILE),
            "thresholds": thresholds,
            "samples": len(lines),
            "violations_by_type": {k: len(v) for k, v in violations.items()},
            "generated_at": datetime.now().isoformat(),
        }
        self._write_json(THRESHOLDS_FILE, result)
        return result

    # ═══════════════════════════════════
    # 管线 4: Constitution 语义日志 → 正则模式
    # ═══════════════════════════════════

    def extract_constitution_patterns(self) -> dict:
        """从 constitution_semantic.log 提取绕弯话短语，生成正则模式建议。

        流程：语义违规短语 → 去重聚类 → 生成正则 → constitution_patterns.json
        constitution.py 启动时可选加载这些模式，下次正则直接命中。

        Returns:
            {"patterns": [{"rule_id":"C3","phrase":"先放一放","regex":"先放一放|暂时搁置"}], ...}
        """
        if not CONSTITUTION_SEMANTIC_LOG.exists():
            return {"patterns": [], "samples": 0, "note": "无语义日志"}

        with open(CONSTITUTION_SEMANTIC_LOG, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if len(lines) < MIN_SAMPLES:
            return {"patterns": [], "samples": len(lines),
                    "note": f"样本不足（需≥{MIN_SAMPLES}）"}

        # 解析日志：提取 VIOLATION 行的规则ID和触发短语
        violations = []
        for line in lines:
            # 格式: [ts] VIOLATION | C3: 暗示跳过验证流程 | 文本
            if "VIOLATION" in line:
                parts = line.split(" | ", 2)
                if len(parts) >= 3:
                    rule_detail = parts[1]  # "C3: 暗示跳过验证流程"
                    text = parts[2]  # 原始文本片段
                    rule_id = rule_detail.split(":")[0].strip()  # "C3"
                    # 从文本中提取关键短语（取最可能的绕弯话片段）
                    phrase = self._extract_evasion_phrase(text)
                    if phrase:
                        violations.append({"rule_id": rule_id, "phrase": phrase})

        if len(violations) < MIN_SAMPLES:
            return {"patterns": [], "samples": len(violations),
                    "note": f"有效短语不足（需≥{MIN_SAMPLES}）"}

        # 按规则ID聚类
        by_rule = defaultdict(list)
        for v in violations:
            by_rule[v["rule_id"]].append(v["phrase"])

        patterns = []
        for rule_id, phrases in by_rule.items():
            if len(phrases) < 3:
                continue

            # 找最长公共子串（而不是直接计数完整短语）
            common = self._find_common_phrases(phrases)

            if common:
                escaped = [re.escape(p) for p in common[:5]]
                regex = "|".join(escaped)
                patterns.append({
                    "rule_id": rule_id,
                    "source_phrases": common[:5],
                    "regex": regex,
                    "samples": len(phrases),
                    "total": len(phrases),
                    "generated_at": datetime.now().isoformat(),
                })

        result = {
            "version": self._next_version(PATTERNS_FILE),
            "patterns": patterns,
            "samples": len(violations),
            "rules_found": len(by_rule),
            "generated_at": datetime.now().isoformat(),
        }
        self._write_json(PATTERNS_FILE, result)
        return result

    @staticmethod
    def _extract_evasion_phrase(text: str) -> str | None:
        """从语义违规日志的文本片段中提取绕弯话短语。

        提取去标点后的纯中文文本，作为后续最长公共子串的输入。
        """
        cleaned = re.sub(r'[^\u4e00-\u9fff]', '', text)
        if len(cleaned) < 4:
            return None
        return cleaned  # 返回完整中文，聚类时找最长公共子串

    @staticmethod
    def _find_common_phrases(phrases: list[str]) -> list[str]:
        """从一组短语中找重复出现的子串（2-8字窗口），过滤停用词。"""
        from collections import Counter as _Ctr
        stopwords = {"这个", "那个", "这些", "那些", "一个", "一下", "可以",
                     "已经", "没有", "什么", "怎么", "不是", "还是", "不过",
                     "但是", "而且", "然后", "所以", "如果", "因为", "验证",
                     "通过", "全部", "检查", "执行", "开始", "直接", "进行"}
        substrings = []
        for p in phrases:
            seen = set()
            for w in range(3, min(9, len(p) + 1)):  # 最少3字，排除太短的
                for i in range(len(p) - w + 1):
                    sub = p[i:i + w]
                    if sub not in seen and sub not in stopwords:
                        seen.add(sub)
                        substrings.append(sub)
        return [s for s, c in _Ctr(substrings).most_common(10) if c >= 2]

    # ═══════════════════════════════════
    # 全部运行
    # ═══════════════════════════════════

    def run_all(self) -> dict:
        """运行全部四条管线。"""
        return {
            "factors": self.learn_factors(),
            "rules": self.extract_rules(),
            "thresholds": self.adjust_thresholds(),
            "patterns": self.extract_constitution_patterns(),
        }

    def status(self) -> dict:
        """查看经验存储状态。"""
        return {
            "factors": self._file_status(FACTORS_FILE),
            "rules": self._file_status(RULES_FILE),
            "thresholds": self._file_status(THRESHOLDS_FILE),
            "patterns": self._file_status(PATTERNS_FILE),
            "sources": {
                "predict_deviations": self._count_lines(PREDICT_DEVIATIONS),
                "forget_archives": self._count_lines(FORGET_ARCHIVE),
                "meta_violations": self._count_lines(META_PENDING),
                "semantic_violations": self._count_lines(CONSTITUTION_SEMANTIC_LOG),
            },
        }

    # ── 内部 ────────────────────────

    @staticmethod
    def _read_jsonl(path: Path) -> list:
        if not path.exists():
            return []
        items = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        items.append(json.loads(line))
                    except json.JSONDecodeError:
                        # 非 JSON 行也保留（如 forget 归档的纯文本）
                        items.append({"raw": line})
        return items

    @staticmethod
    def _write_json(path: Path, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _extract_topic(prediction: str) -> str:
        """从预测文本提取主题词。"""
        topics = ["文件操作", "数据库", "配置", "部署", "网络", "API",
                  "GUI", "桌面", "CAD", "代码", "测试", "文档", "打包"]
        for t in topics:
            if t in prediction:
                return t
        return "通用"

    @staticmethod
    def _next_version(path: Path) -> int:
        if not path.exists():
            return 1
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("version", 0) + 1
        except Exception:
            return 1

    @staticmethod
    def _file_status(path: Path) -> dict:
        if not path.exists():
            return {"exists": False}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            stat = path.stat()
            return {
                "exists": True,
                "version": data.get("version", 0),
                "size_kb": round(stat.st_size / 1024, 1),
                "generated_at": data.get("generated_at", "unknown"),
            }
        except Exception:
            return {"exists": True, "error": "解析失败"}

    @staticmethod
    def _count_lines(path: Path) -> int:
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for _ in f)

    @staticmethod
    def _get_current_threshold(vtype: str) -> str:
        """获取当前阈值等级。"""
        if THRESHOLDS_FILE.exists():
            try:
                with open(THRESHOLDS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for t in data.get("thresholds", []):
                    if t.get("violation_type") == vtype:
                        return t.get("new_level", "SOFT_BLOCK")
            except Exception:
                pass
        return "SOFT_BLOCK"  # 默认


# ── CLI ──────────────────────────────

def main():
    import sys

    engine = ExperienceEngine()

    if len(sys.argv) < 2:
        print("Experience Engine — 从观察到改变行为")
        print()
        print("子命令:")
        print("  run          运行全部三条管线")
        print("  factors      只跑 predict→factors")
        print("  rules        只跑 forget→rules")
        print("  thresholds   只跑 meta→thresholds")
        print("  patterns     只跑 constitution→patterns")
        print("  status       查看经验状态")
        return

    cmd = sys.argv[1]

    if cmd == "run":
        results = engine.run_all()
        for name, result in results.items():
            samples = result.get("samples", 0)
            item_key = "factors" if "factors" in result else "rules" if "rules" in result else "thresholds" if "thresholds" in result else "patterns"
            count = len(result.get(item_key, []))
            note = result.get("note", "")
            print(f"  {name}: {count}条产物, {samples}样本 {note}")

    elif cmd == "factors":
        r = engine.learn_factors()
        print(f"factors: {len(r.get('factors',[]))}条, {r.get('samples',0)}样本, {r.get('clusters',0)}聚类")
        for f in r.get("factors", []):
            print(f"  [{f['domain']}] {f['type']} ×{f['multiplier']} ({f['error_rate']:.0%}错误率)")

    elif cmd == "rules":
        r = engine.extract_rules()
        print(f"rules: {len(r.get('rules',[]))}条, {r.get('samples',0)}模式")
        for rule in r.get("rules", []):
            print(f"  IF {rule['condition']} THEN {rule['action']} ({rule['confidence']:.0%})")

    elif cmd == "thresholds":
        r = engine.adjust_thresholds()
        print(f"thresholds: {len(r.get('thresholds',[]))}条调整, {r.get('samples',0)}违规")
        if r.get("violations_by_type"):
            print(f"  违规分布: {r['violations_by_type']}")
        for t in r.get("thresholds", []):
            print(f"  [{t['violation_type']}] {t['old_level']}→{t['new_level']} ({t['count']}次, {t['severity']:.0%})")

    elif cmd == "patterns":
        r = engine.extract_constitution_patterns()
        print(f"patterns: {len(r.get('patterns',[]))}条规则, {r.get('samples',0)}样本, {r.get('rules_found',0)}类违规")
        for p in r.get("patterns", []):
            print(f"  [{p['rule_id']}] {p['regex'][:60]} ({p['samples']}次)")

    elif cmd == "status":
        s = engine.status()
        for name, info in s.items():
            if name == "sources":
                print("数据源:")
                for src, count in info.items():
                    print(f"  {src}: {count}行")
            else:
                if info.get("exists"):
                    print(f"  {name}: v{info.get('version','?')} {info.get('size_kb',0)}KB ({info.get('generated_at','?')[:19]})")
                else:
                    print(f"  {name}: 空")

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
