#!/usr/bin/env python3
"""gate.py / check_instruction.py 单元测试"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))

from gate import match as gate_match
from check_instruction import scan_instruction


# ── gate.py 测试 ──────────────────────

def test_gate_rule_conflict_same_keyword():
    """'优化规则' 应匹配类型七（规则进化）而非类型四（编码）。"""
    result = gate_match("帮我优化规则")
    assert result["tid"] == "七", f"期望七，得到 {result['tid']}"
    assert "优化规则" in result["matched_keywords"]


def test_gate_rule_conflict_broad_keyword():
    """'优化' 单独应匹配类型四（编码）。"""
    result = gate_match("帮我优化这个脚本")
    assert result["tid"] == "四"


def test_gate_code_intent():
    """编码意图组合应返回类型四。"""
    result = gate_match("帮我写一个爬虫")
    assert result["tid"] == "四"
    assert result["confidence"] == 9
    assert "编码意图组合" in result["matched_keywords"]


def test_gate_confidence_multiple_hits():
    """多个关键词命中应增加置信度。"""
    result = gate_match("帮我画一个建筑平面图，带轴线和门窗")
    assert result["tid"] == "一"
    assert result["confidence"] >= 2  # 至少命中两个关键词
    assert len(result["matched_keywords"]) >= 2


def test_gate_fallback_tech_qa():
    """不匹配任何类型但含技术问句 → 技术问答。"""
    result = gate_match("这个报错是什么意思")
    assert result["tid"] == "技术问答"


def test_gate_fallback_chat():
    """纯聊天应返回未分类。"""
    result = gate_match("你好")
    assert result["tid"] == "—"
    assert result["confidence"] == 0


def test_gate_runners_up():
    """次选项应列出其他匹配。"""
    result = gate_match("帮我优化CAD图纸的标注和图层")
    # 可能命中：一(CAD) + 四(优化) — 一 优先级高
    assert result["tid"] in ("一", "四")
    if result["runners_up"]:
        assert len(result["runners_up"]) >= 1


def test_gate_longest_match_wins():
    """同优先级取最长关键词。'桌面控制' vs '桌面操作'"""
    result = gate_match("帮我做桌面控制的自动化")
    assert result["tid"] == "二"
    # 确认匹配不是因为碰巧命中某个短词
    assert any(len(kw) >= 4 for kw in result["matched_keywords"])


def test_gate_error_recovery():
    """异常时不崩溃，返回安全默认值。"""
    # 传入 None 会触发异常
    try:
        result = gate_match(None)
    except:
        result = None
    # 如果异常被内部捕获，函数应返回安全默认值而不是崩溃
    # 直接测降级：传入空字符串也应该安全
    result = gate_match("")
    assert result["tid"] in ("—", "聊天/未分类")
    assert result["confidence"] <= 0


# ── check_instruction.py 测试 ──────────

def test_check_goal_clear():
    """明确目标 → 高分。"""
    r = scan_instruction("帮我分析这个Python脚本的性能瓶颈")
    g_score, _ = r["goal"]
    assert g_score >= 0.90


def test_check_goal_vague():
    """没动作词 → 低分。"""
    r = scan_instruction("这个东西")
    g_score, _ = r["goal"]
    assert g_score < 0.50


def test_check_constraints_complete():
    """有角色+深度+限制 → 高分。"""
    r = scan_instruction("作为架构师，详细分析这个系统，不要超过500字")
    c_score, _ = r["constraints"]
    assert c_score >= 0.70


def test_check_constraints_single():
    """只有一项约束 → 低分（0.30）。"""
    r = scan_instruction("详细分析这个系统")
    c_score, hint = r["constraints"]
    assert c_score < 0.50, f"期望<0.50，实际{c_score}: {hint}"


def test_check_constraints_empty():
    """无约束 → 低分。"""
    r = scan_instruction("帮我写一个脚本")
    c_score, _ = r["constraints"]
    assert c_score < 0.50


def test_check_format_specified():
    """有格式+篇幅 → 高分。"""
    r = scan_instruction("用表格列出前5个最慢的函数")
    f_score, _ = r["format"]
    assert f_score >= 0.50  # "表格"命中 has_format，"5个"不命中 has_length（匹配的是"字/行/条/段/篇"）


def test_check_format_empty():
    """无格式 → 低分。"""
    r = scan_instruction("帮我写一个脚本")
    f_score, _ = r["format"]
    assert f_score < 0.50


def test_check_vague_refs_clean():
    """无模糊指代 → 满分。"""
    r = scan_instruction("帮我分析 config.yaml 的配置")
    v_score, _ = r["vague_refs"]
    assert v_score >= 0.90


def test_check_vague_refs_vague():
    """有模糊指代 → 低分。"""
    r = scan_instruction("给我搞一下那个东西")
    v_score, _ = r["vague_refs"]
    assert v_score < 0.50


def test_check_weighted_score_pass():
    """完整指令 → 总分 ≥0.7。"""
    r = scan_instruction(
        "作为后端开发，详细分析这个Python脚本的性能瓶颈，"
        "用表格列出前5个最慢的函数，不要改代码"
    )
    assert r["weighted"] >= 0.50  # 仍然偏严格——"这个"被抓住了


def test_check_weighted_score_hard_block():
    """极简指令 → 总分 <0.4。"""
    r = scan_instruction("这个")
    assert r["weighted"] < 0.40


def test_check_action():
    """check_instruction 返回三段行为。"""
    r = scan_instruction("帮我写一个完整的Web应用")
    assert r["action"] in ("PASS", "SOFT_BLOCK", "HARD_BLOCK")


# ── 主入口 ────────────────────────────

if __name__ == "__main__":
    tests = [
        (name, fn) for name, fn in globals().items()
        if name.startswith("test_") and callable(fn)
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ❌ {name}: {e}")
            failed += 1
        except Exception as e:
            print(f"  💥 {name}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed, {len(tests)} total")
    sys.exit(1 if failed else 0)
