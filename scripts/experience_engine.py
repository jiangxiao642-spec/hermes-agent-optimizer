#!/usr/bin/env python3
"""
Experience Engine — 从"观察→记录"到"观察→改变行为"
====================================================

读取 predict/forget/meta 三个模块的原始输出，
生成可被下次运行时自动加载的经验产物。

三条学习管线：
  1. predict 偏差 → 聚类 → 修正因子 → factors.json
  2. forget 摘要 → 模式提取 → if-then 规则 → rules.json
  3. meta 违规 → 聚类 → 阈值调整 → thresholds.json

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

# ── 产物 ──────────────────────────────
FACTORS_FILE = EXPERIENCE_DIR / "factors.json"
RULES_FILE = EXPERIENCE_DIR / "rules.json"
THRESHOLDS_FILE = EXPERIENCE_DIR / "thresholds.json"

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
    # 全部运行
    # ═══════════════════════════════════

    def run_all(self) -> dict:
        """运行全部三条管线。"""
        return {
            "factors": self.learn_factors(),
            "rules": self.extract_rules(),
            "thresholds": self.adjust_thresholds(),
        }

    def status(self) -> dict:
        """查看经验存储状态。"""
        return {
            "factors": self._file_status(FACTORS_FILE),
            "rules": self._file_status(RULES_FILE),
            "thresholds": self._file_status(THRESHOLDS_FILE),
            "sources": {
                "predict_deviations": self._count_lines(PREDICT_DEVIATIONS),
                "forget_archives": self._count_lines(FORGET_ARCHIVE),
                "meta_violations": self._count_lines(META_PENDING),
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
        print("  status       查看经验状态")
        return

    cmd = sys.argv[1]

    if cmd == "run":
        results = engine.run_all()
        for name, result in results.items():
            samples = result.get("samples", 0)
            count = len(result.get("factors", result.get("rules", result.get("thresholds", []))))
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
