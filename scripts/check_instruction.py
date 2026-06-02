#!/usr/bin/env python3
"""
指令质量前置检查器
扫描四项：目标、约束、格式、指代。
任意缺失 → 提示追问方向。

用法：
  python check_instruction.py "你的指令文本"
  echo "你的指令文本" | python check_instruction.py
"""

import sys
import re


def check_goal(text: str) -> tuple:
    """目标是否清晰？"""
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
        return False, "没找到明确的动作词。你要「做什么」？"
    if too_short:
        return False, "指令太短，可能缺上下文。"
    if too_many_questions:
        return False, "问题多于指令——像是在探索方向而非下达任务。"

    return True, "目标明确"


def check_constraints(text: str) -> tuple:
    """立场/约束是否明确？"""
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
        r'don\'t|cannot|must not|only|just)',
        text
    ))

    if not has_role and not has_depth and not has_constraint:
        return False, (
            "没有立场/深度/限制条件。补充：\n"
            "  ① 立场：最强反方？中立分析？魔鬼辩护？\n"
            "  ② 深度：一句话结论？详细论证？\n"
            "  ③ 限制：有什么不能做的？"
        )

    return True, "约束清晰"


def check_format(text: str) -> tuple:
    """输出格式是否指定？"""
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
        return False, (
            "没指定输出格式。补充：\n"
            "  ① 篇幅：多少字/行/条？\n"
            "  ② 结构：表格？列表？段落？代码？\n"
            "  ③ 颗粒度：概览还是逐条？"
        )

    return True, "格式明确"


def check_vague_refs(text: str) -> tuple:
    """指代词是否明确？"""
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

    if vague_words:
        return False, (
            f"指代不明：{'、'.join(vague_words)} 没跟具体名词。\n"
            "别猜、别列清单让对方选、别自己推断。\n"
            "直接问：「你说的'那个'是指什么？」"
        )

    return True, "指代明确"


def scan_instruction(text: str) -> dict:
    """扫描指令，返回四项检查结果"""
    goal_ok, goal_hint = check_goal(text)
    constraint_ok, constraint_hint = check_constraints(text)
    format_ok, format_hint = check_format(text)
    refs_ok, refs_hint = check_vague_refs(text)

    return {
        "goal": (goal_ok, goal_hint),
        "constraints": (constraint_ok, constraint_hint),
        "format": (format_ok, format_hint),
        "vague_refs": (refs_ok, refs_hint),
    }


def format_output(text: str, results: dict) -> str:
    """格式化输出，含选项式追问模板"""
    lines = []
    all_pass = all(v[0] for v in results.values())

    if all_pass:
        lines.append("✅ 四项检查全部通过，可以动手。")
    else:
        lines.append("⚠️ 指令有缺失——直接用下面的话术追问：\n")

    for key, label in [("goal", "目标"), ("constraints", "约束"), ("format", "格式"), ("vague_refs", "指代")]:
        ok, hint = results[key]
        icon = "✅" if ok else "❌"
        lines.append(f"  {icon} {label}：{hint}")
        if not ok:
            tmpl = _question_template(key, text)
            if tmpl:
                lines.append(tmpl)

    return "\n".join(lines)


def _question_template(key: str, text: str) -> str:
    """根据缺失项生成选项式追问模板"""
    non_tech_signals = [
        "道歉", "写信", "回复", "怎么说", "帮我想想", "怎么跟",
        "朋友", "家人", "爸妈", "妈妈", "爸爸", "同学", "同事",
        "人情", "关系", "聊天", "说话", "措辞", "语气",
    ]
    tech_signals = [
        "代码", "文件", ".py", ".js", "脚本", "函数", "接口",
        "配置", "部署", "打包", "构建", "测试", ".yaml", ".json",
    ]
    is_non_tech = any(s in text for s in non_tech_signals) and not any(s in text for s in tech_signals)

    if key == "goal":
        if is_non_tech:
            return "你想让我帮你：\n  A. 想具体措辞/草稿\n  B. 给原则和方向\n  C. 先听你的想法，我补充\n你选哪个？"
        return "我没有完全理解——你是要我：\n  A. 分析现状找问题\n  B. 直接动手修改\n  C. 先给方案再动手\n你选哪个？"
    if key == "vague_refs":
        return "你说的「那个」是指什么？帮我明确一下。"
    if key == "format":
        if is_non_tech:
            return "你想要：\n  A. 几句话直接能用\n  B. 几个要点自己挑\n  C. 详细方案"
        return "输出格式偏好：\n  A. 简短结论\n  B. 结构化列表\n  C. 完整报告"
    if key == "constraints":
        if is_non_tech:
            return "有什么不能提的？告诉我边界。"
        return "有什么不能碰的？或者只改特定文件/目录？告诉我边界。"
    return ""


def read_input() -> str:
    """从命令行参数或 stdin 读取指令"""
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

    all_pass = all(v[0] for v in results.values())
    if not all_pass:
        print(f"\n--- 原始指令 ---\n{text}")


if __name__ == "__main__":
    main()
