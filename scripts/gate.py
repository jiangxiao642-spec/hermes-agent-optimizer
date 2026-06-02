#!/usr/bin/env python3
"""Gate — 任务类型前置路由器。

第一个工具调用必须过此门。
输出类型 + skill链 + 第一动作。
"""

import sys


TYPES = {
    "一": {
        "name": "CAD",
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
        "trigger": [
            "点击", "截图", "自动化", "桌面操作", "鼠标", "键盘",
            "识别按钮", "操作Windows", "窗口", "桌面控制",
        ],
        "skills": ["desktop-control", "windows-bridge-playbook"],
        "first": "desktop-control",
    },
    "三A": {
        "name": "内容创作",
        "trigger": ["小说", "写作", "章节", "创作", "文案"],
        "skills": ["humanizer"],
        "first": "humanizer",
    },
    "三B": {
        "name": "视频脚本",
        "trigger": ["B站", "视频", "脚本", "选题", "打分", "预测", "复盘", "拍", "发布"],
        "skills": ["cheat-on-content", "humanizer"],
        "first": "cheat-on-content",
    },
    "三C": {
        "name": "文案去AI味",
        "trigger": ["去AI味", "人话", "改写成", "自然语气"],
        "skills": ["humanizer"],
        "first": "humanizer",
    },
    "四": {
        "name": "复杂任务/编码",
        "trigger": [
            "多步骤", "拆解", "复杂", "项目", "整个流程",
            "优化", "重构", "实现", "开发", "搭建",
        ],
        "skills": ["plan", "superpowers", "autonomous-run"],
        "first": "plan",
    },
    "五": {
        "name": "信息获取",
        "trigger": [
            "搜索", "查一下", "搜一下", "找资料", "网页",
            "抓取", "提取", "论文",
        ],
        "skills": ["web_search", "web_extract"],
        "first": "web_search",
    },
    "六": {
        "name": "打包/安装",
        "trigger": [
            "打包", "压缩包", "安装器", "exe", "Electron",
            "asar", "安装包", "forge", "桌面壳", "ZIP",
        ],
        "skills": ["electron-desktop-packaging"],
        "first": "electron-desktop-packaging",
    },
    "七": {
        "name": "规则进化",
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


def match(task: str) -> tuple:
    """返回 (类型代号, 类型名, skill列表, 第一动作)"""
    task_lower = task.lower()

    # 先扫编码意图组合
    has_action = any(a in task for a in CODE_PAIRS["actions"])
    has_target = any(t in task for t in CODE_PAIRS["targets"])
    has_pattern = any(p in task for p in CODE_PATTERNS)
    if (has_action and has_target) or has_pattern:
        t = TYPES["四"]
        modify_hints = ["改", "修", "优化", "重构", "整理", "提取", "移到", "移动"]
        is_modify = any(h in task for h in modify_hints)
        return ("四", t["name"], t["skills"], t["first"], is_modify)

    # 按类型匹配
    for tid, info in TYPES.items():
        if tid.startswith("三"):
            continue
        for kw in info["trigger"]:
            if kw in task_lower or kw in task:
                return (tid, info["name"], info["skills"], info["first"], False)

    # 子类型三
    for stype in ["三A", "三B", "三C"]:
        info = TYPES[stype]
        for kw in info["trigger"]:
            if kw in task_lower or kw in task:
                return (stype, info["name"], info["skills"], info["first"], False)

    # 不匹配 → 判断是不是技术问答
    technical_hints = ["是什么", "什么意思", "区别", "怎么用", "为什么", "报错", "错误"]
    if any(h in task for h in technical_hints):
        return ("技术问答", "技术问答", ["verify-before-answer"], "verify-before-answer", False)

    return ("—", "聊天/未分类", [], None, False)


def main():
    task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else sys.stdin.read().strip()

    if not task:
        print("=== GATE === 空输入")
        return

    tid, name, skills, first, is_modify = match(task)

    print("=== GATE ===")
    print(f"任务: {task[:120]}")
    print(f"类型: {tid}（{name}）")
    if skills:
        print(f"Skill链: {' → '.join(skills)}")
        print(f"第一动作: skill_view {first}")
        if is_modify:
            print("🔧 检测到改代码意图 → 改之前先列清单 + 跑 graphify affected")
    else:
        print("操作: 无skill链，直接回复")
    print("============")


if __name__ == "__main__":
    main()
