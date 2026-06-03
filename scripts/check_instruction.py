#!/usr/bin/env python3
"""
指令质量前置检查器 — 置信度版
==============================
四个维度分别 0-1 打分，加权总分 → 三段行为。

维度权重：
  goal (目标):   35%  — 目标没搞清楚，其他再完整也没用
  constraints:   25%  — 立场/深度/限制
  format:        20%  — 输出格式/篇幅
  vague_refs:    20%  — 指代明确度

三段行为：
  >= 0.7  PASS       放行，不追问
  0.4-0.7 SOFT_BLOCK 追问，给默认选项
  < 0.4   HARD_BLOCK 不继续，必须补全

用法：
  python check_instruction.py "你的指令文本"
  echo "你的指令文本" | python check_instruction.py
"""

import sys
import re

# ── 权重 ──────────────────────────────
W_GOAL = 0.35
W_CONSTRAINTS = 0.25
W_FORMAT = 0.20
W_REFS = 0.20

# ── 阈值 ──────────────────────────────
THRESHOLD_PASS = 0.70
THRESHOLD_SOFT = 0.40


def check_goal(text: str) -> tuple:
    """目标置信度。返回 (score, hint)。"""
    has_verb = bool(re.search(
        r'(帮|给|做|写|画|查|搜|生成|创建|分析|调试|测试|部署|打包|优化|修复|整理|罗列|'
        r'翻译|修改|改|发布|上传|安装|卸载|配置|设计|评估|打分|检查|论证|反驳|推翻|验证|'
        r'解释|说明|列出|对比|总结|'
        r'create|write|build|make|fix|test|deploy|debug|analyze|check)',
        text
    ))
    too_short = len(text.strip()) < 6
    too_many_questions = text.count('？') + text.count('?') > 3

    if not has_verb:
        if too_short:
            return 0.05, "没动作词且太短——完全不知道要干什么"
        return 0.15, "没找到明确的动作词。你要「做什么」？"
    if too_short:
        return 0.40, "有动作但指令太短，可能缺上下文"
    if too_many_questions:
        return 0.50, "问题多于指令——像是在探索方向而非下达任务"
    return 0.95, "目标明确"


def check_constraints(text: str) -> tuple:
    """约束置信度。返回 (score, hint)。"""
    has_role = bool(re.search(
        r'(作为|当|角色|立场|你是|我是|扮演|'
        r'最强反方|中立|客观|批判|魔鬼辩护|'
        r'给我|替我|站在.+角度|以.+身份)',
        text
    ))
    has_depth = bool(re.search(
        r'(详细|简略|深度|粗略|一句话|全面|深入|浅出|展开|'
        r'detail|brief|deep|summary|overview)',
        text
    ))
    has_constraint = bool(re.search(
        r'(不要|不能|禁止|避免|别|'
        r'只|仅|最多|最少|至少|不超过|'
        r"don't|cannot|must not|only|just)",
        text
    ))

    count = sum([has_role, has_depth, has_constraint])

    if count == 0:
        return 0.10, "没有立场/深度/限制条件"
    if count == 1:
        return 0.30, f"只指定了一项约束（{['角色','深度','限制'][[has_role,has_depth,has_constraint].index(True)]}），至少需要两项"
    if count == 2:
        return 0.70, "两项约束，基本够用"
    return 0.95, "约束完整"


def check_format(text: str) -> tuple:
    """格式置信度。返回 (score, hint)。"""
    has_format = bool(re.search(
        r'(表格|列表|条目|段落|markdown|json|yaml|'
        r'字数|字以内|字符|行数|'
        r'table|list|paragraph|doc|'
        r'格式[：:]|输出[：:]|产物[：:]|'
        r'按.+格式|用.+格式)',
        text
    ))
    has_length = bool(re.search(
        r'(\d+\s*字|\d+\s*行|\d+\s*条|\d+\s*段|\d+\s*篇)',
        text
    ))

    if not has_format and not has_length:
        return 0.15, "没指定输出格式和篇幅"
    if has_format and has_length:
        return 0.95, "格式明确"
    return 0.50, "格式或篇幅只指定了一项"


def check_vague_refs(text: str) -> tuple:
    """指代置信度。返回 (score, hint)。"""
    noun_suffixes = (
        '文件|目录|脚本|功能|项目|仓库|工具|命令|配置|'
        '页面|按钮|选项|参数|路径|方案|文档|代码|程序|任务|问题|账号|'
        '数字人|声线|商品|稿子|章节|图片|视频|语音'
    )

    patterns = [
        (r'那个东西', '那个东西'),
        (r'这东西', '这东西'),
        (r'那东西', '那东西'),
        (r'那些', '那些'),
        (r'那个(?!\s*(?:' + noun_suffixes + r'))', '那个'),
        (r'这个(?!\s*(?:' + noun_suffixes + r'))', '这个'),
        (r'(?<!\w)它(?!\w)', '它'),
    ]

    vague_words = []
    for pat, label in patterns:
        if re.search(pat, text):
            vague_words.append(label)

    filtered = []
    for w in vague_words:
        if any(w != other and w in other for other in vague_words):
            continue
        filtered.append(w)
    vague_words = filtered

    if not vague_words:
        return 1.0, "指代明确"

    if len(vague_words) == 1:
        return 0.30, f"指代不明：{vague_words[0]} 没跟具体名词"

    return 0.05, f"多处指代不明：{'、'.join(vague_words)}"


def scan_instruction(text: str) -> dict:
    """扫描指令，返回加权总分 + 各维度详情。

    每个检查函数独立 try-except，单点失败不影响其他维度。
    """
    def _safe_check(fn, default_score=0.0, default_hint="检查出错，降级通过"):
        try:
            return fn(text)
        except Exception as e:
            return default_score, f"{default_hint} ({type(e).__name__})"

    g_score, g_hint = _safe_check(check_goal)
    c_score, c_hint = _safe_check(check_constraints)
    f_score, f_hint = _safe_check(check_format)
    v_score, v_hint = _safe_check(check_vague_refs)

    weighted = (
        g_score * W_GOAL
        + c_score * W_CONSTRAINTS
        + f_score * W_FORMAT
        + v_score * W_REFS
    )

    if weighted >= THRESHOLD_PASS:
        action = "PASS"
        action_hint = "可以动手"
    elif weighted >= THRESHOLD_SOFT:
        action = "SOFT_BLOCK"
        action_hint = "追问但给默认选项"
    else:
        action = "HARD_BLOCK"
        action_hint = "不继续，必须补全"

    return {
        "goal": (g_score, g_hint),
        "constraints": (c_score, c_hint),
        "format": (f_score, f_hint),
        "vague_refs": (v_score, v_hint),
        "weighted": weighted,
        "action": action,
        "action_hint": action_hint,
    }


def format_output(text: str, results: dict) -> str:
    """格式化输出。"""
    lines = []
    weighted = results["weighted"]
    action = results["action"]

    # 总分条
    bar_len = 20
    filled = int(weighted * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    lines.append(f"总分: {weighted:.0%} [{bar}] → {action} ({results['action_hint']})")
    lines.append("")

    # 各维度
    weights = {"goal": W_GOAL, "constraints": W_CONSTRAINTS, "format": W_FORMAT, "vague_refs": W_REFS}
    labels = {"goal": "目标", "constraints": "约束", "format": "格式", "vague_refs": "指代"}

    for key in ["goal", "constraints", "format", "vague_refs"]:
        score, hint = results[key]
        w = weights[key]
        contrib = score * w
        bar_filled = int(score * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"  [{bar}] {labels[key]}: {score:.0%} × {w:.0%} = {contrib:.0%}  {hint}")

    # 行为提示
    lines.append("")
    if action == "PASS":
        lines.append("✅ 全部通过，直接动手。")
    elif action == "SOFT_BLOCK":
        lines.append("⚠️ 指令有不足——追问给默认选项，不阻塞。")
        tmpl = _soft_prompt(results, text)
        if tmpl:
            lines.append(f"\n── 追问话术 ──\n{tmpl}")
    else:
        lines.append("❌ 指令严重不完整——必须补全才能继续。")
        tmpl = _hard_prompt(results, text)
        if tmpl:
            lines.append(f"\n── 追问话术 ──\n{tmpl}")

    return "\n".join(lines)


def _soft_prompt(results: dict, text: str) -> str:
    """SOFT_BLOCK 时的追问模板——给默认选项，用户可跳过。"""
    prompts = []
    for key in ["goal", "constraints", "format", "vague_refs"]:
        score, _ = results[key]
        if score < 0.60:  # 只追问明显不足的维度
            t = _question_template(key, text)
            if t:
                prompts.append(t)
    if not prompts:
        return ""
    return "\n\n".join(prompts) + "\n\n（可以跳过，默认继续）"


def _hard_prompt(results: dict, text: str) -> str:
    """HARD_BLOCK 时的追问模板——必须回答。"""
    prompts = []
    for key in ["goal", "constraints", "format", "vague_refs"]:
        score, _ = results[key]
        if score < 0.50:
            t = _question_template(key, text)
            if t:
                prompts.append(t)
    if not prompts:
        return ""
    return "\n\n".join(prompts) + "\n\n（必须补全后才能继续）"


def _is_non_tech(text: str) -> bool:
    """特征组合判断非技术场景。不再是硬编码关键词列表。

    判定：人际特征 ≥3 且无技术特征 → 非技术
          技术特征 ≥2 → 技术
          其余 → 中性（按技术处理）
    """
    # 人际特征
    interpersonal = [
        r'朋友', r'家人', r'爸妈', r'妈妈', r'爸爸', r'同学', r'同事',
        r'道歉', r'写信', r'回复', r'怎么说', r'帮我想想', r'怎么跟',
        r'人情', r'关系', r'聊天', r'措辞', r'语气', r'说话',
        r'对不起', r'不好意思', r'请假', r'约', r'聚会',
    ]
    # 技术特征
    technical = [
        r'\.py\b', r'\.js\b', r'\.json\b', r'\.yaml\b', r'\.md\b',
        r'代码', r'脚本', r'函数', r'接口', r'配置', r'部署',
        r'打包', r'构建', r'测试', r'程序', r'文件', r'数据库',
    ]

    inter_count = sum(1 for p in interpersonal if re.search(p, text))
    tech_count = sum(1 for p in technical if re.search(p, text))

    if inter_count >= 3 and tech_count == 0:
        return True
    if tech_count >= 2:
        return False
    return False  # 中性默认技术


def _get_log_dir():
    from pathlib import Path
    d = Path.home() / ".hermes" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _check_log(message: str, detail: str = ""):
    """运行日志"""
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    if detail:
        line += f" | {detail[:200]}"
    with open(_get_log_dir() / "check.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _question_template(key: str, text: str) -> str:
    """根据缺失维度生成选项式追问。"""
    is_non_tech = _is_non_tech(text)

    if key == "goal":
        if is_non_tech:
            return "你想让我帮你：\n  A. 想具体措辞/草稿\n  B. 给原则和方向\n  C. 先听你的想法，我补充\n你选哪个？"
        return "你是要我：\n  A. 分析现状找问题\n  B. 直接动手修改\n  C. 先给方案再动手\n你选哪个？"
    if key == "vague_refs":
        return "你说的「那个」是指什么？帮我明确一下。"
    if key == "format":
        if is_non_tech:
            return "你想要：\n  A. 几句话直接能用\n  B. 几个要点自己挑\n  C. 详细方案"
        return "输出格式偏好：\n  A. 简短结论\n  B. 结构化列表\n  C. 完整报告"
    if key == "constraints":
        if is_non_tech:
            return "有什么限制？不能提什么？边界在哪？"
        return "有什么不能碰的？只改特定文件/目录？告诉我边界。"
    return ""


def read_input() -> str:
    """从命令行参数或 stdin 读取指令。"""
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    print("输入指令文本（Ctrl+D 结束）：")
    return sys.stdin.read().strip()


def main():
    text = read_input()
    if not text:
        print("用法：python check_instruction.py \"你的指令\"")
        sys.exit(1)

    results = scan_instruction(text)
    print(format_output(text, results))
    print(f"\n--- 原始指令 ---\n{text}")

    # 运行日志
    _check_log(f"action={results['action']} score={results['weighted']:.0%}", text)

    # HARD_BLOCK 时非零退出
    if results["action"] == "HARD_BLOCK":
        sys.exit(2)


if __name__ == "__main__":
    main()
