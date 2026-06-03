#!/usr/bin/env python3
"""Gate — 任务类型前置路由器。

优先级裁决：多类型命中取最高优先级（数字越小越优先）。
同优先级取最长关键词匹配。

用法：
  echo "优化规则" | python3 gate.py
  python3 gate.py "帮我写一个CAD绘图脚本"
"""

import sys
import os
from datetime import datetime
from pathlib import Path

LOG_DIR = Path.home() / ".hermes" / "logs"


def _log(level: str, message: str, detail: str = ""):
    """简单运行日志。写 ~/.hermes/logs/gate.log。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {level} {message}"
    if detail:
        line += f" | {detail[:200]}"
    with open(LOG_DIR / "gate.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


TYPES = {
    "一": {
        "name": "CAD",
        "priority": 3,
        "trigger": [
            "画图", "出图", "平面图", "剖面图", "DXF", "ezdxf", "CAD",
            "AutoCAD", "识图", "仿制", "建筑图", "轴线", "墙体", "门窗",
            "标注", "图层", "线型", "施工图",
        ],
        "skills": ["cad-gb-standard", "cad-autodraw"],
        "first": "cad-gb-standard",
    },
    "二": {
        "name": "桌面GUI",
        "priority": 3,
        "trigger": [
            "点击", "截图", "自动化", "桌面操作", "鼠标", "键盘",
            "识别按钮", "操作Windows", "窗口", "桌面控制",
        ],
        "skills": ["desktop-control", "windows-bridge-playbook"],
        "first": "desktop-control",
    },
    "三A": {
        "name": "内容创作",
        "priority": 5,
        "trigger": ["小说", "写作", "章节", "创作", "文案"],
        "skills": ["humanizer"],
        "first": "humanizer",
    },
    "三B": {
        "name": "视频脚本",
        "priority": 5,
        "trigger": ["B站", "视频", "脚本", "选题", "打分", "预测", "复盘", "拍", "发布"],
        "skills": ["cheat-on-content", "humanizer"],
        "first": "cheat-on-content",
    },
    "三C": {
        "name": "文案去AI味",
        "priority": 6,
        "trigger": ["去AI味", "人话", "改写成", "自然语气"],
        "skills": ["humanizer"],
        "first": "humanizer",
    },
    "四": {
        "name": "复杂任务/编码",
        "priority": 2,
        "trigger": [
            "多步骤", "拆解", "复杂", "项目", "整个流程",
            "优化", "重构", "实现", "开发", "搭建",
        ],
        "skills": ["plan", "superpowers", "autonomous-run"],
        "first": "plan",
    },
    "五": {
        "name": "信息获取",
        "priority": 1,
        "trigger": [
            "搜索", "查一下", "搜一下", "找资料", "网页",
            "抓取", "提取", "论文",
        ],
        "skills": ["web_search", "web_extract"],
        "first": "web_search",
    },
    "六": {
        "name": "打包/安装",
        "priority": 4,
        "trigger": [
            "打包", "压缩包", "安装器", "exe", "Electron",
            "asar", "安装包", "forge", "桌面壳", "ZIP",
        ],
        "skills": ["electron-desktop-packaging"],
        "first": "electron-desktop-packaging",
    },
    "七": {
        "name": "规则进化",
        "priority": 7,
        "trigger": [
            "优化规则", "修改原则", "加固", "新增规则",
            "自我迭代", "规则提案", "改自己的规则", "固化教训",
        ],
        "skills": ["rule-evolution", "agent-self-learning"],
        "first": "rule-evolution",
    },
}

# 编码意图关键词 — 含这些的组合强制走类型四
CODE_PAIRS = {
    "actions": [
        "写", "做", "开发", "实现", "搭", "改", "修",
        "帮我写", "帮我做", "帮我改", "帮我优化",
        "帮我写一个", "帮我做一个", "帮我开发",
        "写一个", "做一个", "开发一个", "搭一个",
    ],
    "targets": [
        "代码", "脚本", "工具", "程序", "软件", "壳子", "插件",
        "服务", "接口", "API", "页面", "界面", "组件", "壳",
        "函数", "类", "模块", "功能", "计算器", "爬虫", "网站",
        "应用", "app", "App", "APP",
        ".py", ".js", ".ts", ".go", ".rs", ".java", ".cpp", ".c",
        ".yaml", ".yml", ".json", ".toml", ".md", ".sh", ".ps1",
        "文件", "源码", "源代码",
    ],
}

CODE_PATTERNS = [
    "写一个", "做一个", "开发一个", "搭一个", "改一个",
    "建一个", "实现一个", "帮我写一个", "帮我做一个",
    "写个", "做个", "搭个", "改个", "帮我写个", "帮我做个",
]

# 优先级定义（数字越小越优先）
PRIORITY_CODE_PAIR = 9   # 最高 — 明确的编码意图
PRIORITY_TECH_QA = 0     # 最低 — "是什么"类兜底


def match(task: str) -> dict:
    """返回完整匹配结果，含置信度。

    Returns:
        {"tid": "七", "name": "规则进化", "skills": [...], "first": "...",
         "confidence": 2, "matched_keywords": ["优化规则", "加固"],
         "is_modify": False, "runners_up": [("四", "优化", 1), ...]}

    异常时降级：返回安全默认值（"聊天/未分类"），不崩溃。
    """
    try:
        return _match_inner(task)
    except Exception as e:
        _log("ERROR", f"match() 异常降级: {type(e).__name__}: {e}", task)
        return {
            "tid": "—", "name": "聊天/未分类（降级）",
            "skills": [], "first": None,
            "confidence": -1,
            "matched_keywords": [f"异常:{type(e).__name__}"],
            "is_modify": False, "runners_up": [],
        }


def _match_inner(task: str) -> dict:
    task_lower = task.lower()

    # ── 1. 编码意图组合（最高优先级）─────────────────
    has_action = any(a in task for a in CODE_PAIRS["actions"])
    has_target = any(t in task for t in CODE_PAIRS["targets"])
    has_pattern = any(p in task for p in CODE_PATTERNS)
    if (has_action and has_target) or has_pattern:
        t = TYPES["四"]
        modify_hints = ["改", "修", "优化", "重构", "整理", "提取", "移到", "移动"]
        is_modify = any(h in task for h in modify_hints)
        return {
            "tid": "四", "name": t["name"],
            "skills": t["skills"], "first": t["first"],
            "confidence": PRIORITY_CODE_PAIR,
            "matched_keywords": ["编码意图组合"],
            "is_modify": is_modify,
            "runners_up": [],
        }

    # ── 2. 全类型扫描，收集所有命中 ──────────────────
    hits = []  # [(tid, keyword, keyword_len, priority)]
    for tid, info in TYPES.items():
        priority = info.get("priority", 0)
        for kw in info["trigger"]:
            if kw in task_lower:
                hits.append((tid, kw, len(kw), priority))

    if not hits:
        # 技术问答兜底
        technical_hints = ["是什么", "什么意思", "区别", "怎么用", "为什么", "报错", "错误"]
        if any(h in task for h in technical_hints):
            return {
                "tid": "技术问答", "name": "技术问答",
                "skills": ["verify-before-answer"], "first": "verify-before-answer",
                "confidence": PRIORITY_TECH_QA,
                "matched_keywords": [h for h in technical_hints if h in task],
                "is_modify": False, "runners_up": [],
            }
        return {
            "tid": "—", "name": "聊天/未分类",
            "skills": [], "first": None,
            "confidence": 0,
            "matched_keywords": [],
            "is_modify": False, "runners_up": [],
        }

    # ── 3. 裁决：优先级 > 关键词长度 ──────────────────
    hits.sort(key=lambda x: (-x[3], -x[2]))  # priority desc, kw_len desc
    best = hits[0]
    runners_up = [(tid, kw, priority) for tid, kw, _, priority in hits[1:4]]

    t = TYPES[best[0]]
    return {
        "tid": best[0], "name": t["name"],
        "skills": t["skills"], "first": t["first"],
        "confidence": len(hits),  # 命中关键词数量 = 置信度
        "matched_keywords": [kw for _, kw, _, _ in hits],
        "is_modify": False,
        "runners_up": runners_up,
    }


def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()

    if not task:
        print("=== GATE === 空输入")
        return

    result = match(task)

    print("=== GATE ===")
    print(f"任务: {task[:120]}")
    print(f"类型: {result['tid']}（{result['name']}）")
    print(f"置信度: {result['confidence']}（命中关键词: {', '.join(result['matched_keywords'][:5])}）")
    if result["runners_up"]:
        ru = ", ".join(f"{tid}({kw})" for tid, kw, _ in result["runners_up"])
        print(f"次选: {ru}")
    if result["skills"]:
        print(f"Skill链: {' → '.join(result['skills'])}")
        print(f"第一动作: skill_view {result['first']}")
        if result["is_modify"]:
            print("🔧 检测到改代码意图 → 改之前先列清单 + 跑 graphify affected")
    else:
        print("操作: 无skill链，直接回复")
    print("============")

    # 运行日志
    _log("INFO", f"类型={result['tid']} 置信度={result['confidence']}", task)


if __name__ == "__main__":
    main()
