#!/usr/bin/env python3
"""
ToolSearch v2 — 分层 + 标签 + 唯一场景匹配。
先按标签缩小范围，再在层内匹配，冲突时用 not_for/use_instead 消歧。

用法：
  python3 tool_search.py "任务描述"
  python3 tool_search.py --load "skill-name"
  python3 tool_search.py --layers
"""

import json
import sys
from pathlib import Path

INDEX_FILE = Path.home() / ".hermes" / "skill_index.json"


def load_index():
    if not INDEX_FILE.exists():
        return {"layers": {}}
    with open(INDEX_FILE, encoding="utf-8") as f:
        return json.load(f)


def search(task_description: str):
    """v2 搜索：先按标签匹配 → 再在层内打分 → 最后消歧。"""
    index = load_index()
    desc_lower = task_description.lower()

    matches = []

    for layer_name, layer in index.get("layers", {}).items():
        for skill_name, skill in layer.get("skills", {}).items():
            score = 0.0

            # 标签匹配（权重高——标签是精心选择的）
            tags = skill.get("tags", [])
            tag_hits = 0
            for tag in tags:
                if tag.lower() in desc_lower:
                    tag_hits += 1
            score += tag_hits * 2  # tag 匹配 ×2

            # 汇总词匹配
            summary = skill.get("summary", "").lower()
            summary_words = set(summary.split())
            desc_words = set(desc_lower.split())
            score += len(summary_words & desc_words) * 0.5

            # not_for 惩罚——如果任务描述命中了"不该用"的场景，大幅扣分
            not_for = skill.get("not_for", "").lower()
            if not_for and any(w in desc_lower for w in not_for.split()):
                score -= 5

            if score > 0:
                matches.append((score, layer_name, layer.get("label", layer_name),
                                 skill_name, skill.get("summary", ""),
                                 skill.get("not_for", ""),
                                 skill.get("use_instead", "")))

    # 按得分排序
    matches.sort(key=lambda x: -x[0])

    # 消歧：如果 top 两个得分接近且 not_for 有关联，保留指定的那个
    if len(matches) >= 2:
        top = matches[0]
        second = matches[1]
        # 如果 top 的 use_instead 指向 second，交换
        if top[6] == second[3]:
            matches[0], matches[1] = matches[1], matches[0]

    return matches


def list_layers():
    """列出所有分层。"""
    index = load_index()
    for name, layer in index.get("layers", {}).items():
        label = layer.get("label", name)
        skill_count = len(layer.get("skills", {}))
        print(f"  [{name}] {label} — {skill_count} 个 skill")


def get_skill_path(name: str):
    """获取 skill 的完整路径。"""
    index = load_index()
    for layer in index.get("layers", {}).values():
        if name in layer.get("skills", {}):
            return layer["skills"][name].get("path", "")
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: tool_search.py '任务描述'  或  tool_search.py --load skill-name  或  --layers")
        sys.exit(1)

    if sys.argv[1] == "--load":
        name = sys.argv[2]
        path = get_skill_path(name)
        if path:
            print(f"SKILL:{name} → {path}")
        else:
            print(f"NOT_FOUND:{name}")

    elif sys.argv[1] == "--layers":
        list_layers()

    else:
        task = sys.argv[1]
        matches = search(task)
        if not matches:
            print("（未匹配到 skill）")
        for score, layer, label, name, summary, not_for, use_instead in matches[:5]:
            print(f"MATCH[{score:.1f}] [{layer}] {name}")
            print(f"  {summary}")
            if not_for:
                use = f" → 改用 {use_instead}" if use_instead else ""
                print(f"  ⚠️ 不适用的场景：{not_for}{use}")
            print()
