#!/usr/bin/env python3
"""
预测编码闭环
============
大脑不被动接收信息——一直在预测下一秒会发生什么。
预测错了就更新模型。预测误差是学习信号。

用法：
  python3 predict.py record "我预测这个脚本不会有语法错误" --confidence 0.9
  python3 predict.py verify "脚本成功运行，一次通过" 
  python3 predict.py verify "脚本报错SyntaxError"  # 偏差 → 标记
  python3 predict.py list           # 列出最近预测
  python3 predict.py stats          # 统计预测准确率

预测文件：~/.hermes/predictions/predictions.jsonl
"""

import json
import sys
import os
from datetime import datetime
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
PRED_DIR = HERMES_HOME / "predictions"
PRED_FILE = PRED_DIR / "predictions.jsonl"
DEVIATIONS_FILE = PRED_DIR / "deviations.jsonl"
MAX_ACTIVE = 20  # 最多保留多少条未验证的


def _ensure_dir():
    PRED_DIR.mkdir(parents=True, exist_ok=True)


def record_help():
    print("用法: python3 predict.py record \"预测内容\" [--confidence 0.8]")
    print()
    print("预测内容是一句话。例子：")
    print('  "我预测修改后的 config.yaml 重启 Gateway 不会报错"')
    print('  "我预测 UIA 激活后 OpenClaw 会显示 2000+ 元素"')
    print('  "我预测这次 skill 加载不会被跳过"')


def record(prediction: str, confidence: float = 0.7):
    """记录一条预测——任务执行前调用。"""
    _ensure_dir()

    entry = {
        "id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "time": datetime.now().isoformat(),
        "type": "prediction",
        "prediction": prediction,
        "confidence": confidence,
        "status": "pending",
        "actual": None,
        "deviated": None,
    }

    with open(PRED_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"[predict] 📋 已记录: {prediction[:60]}... (置信度: {confidence:.0%})")
    print(f"[predict]    ID: {entry['id']}")

    # 清理过时未验证的
    _cleanup_stale()

    return entry["id"]


def verify(actual: str):
    """对比预测和实际结果——任务执行后调用。"""
    _ensure_dir()

    if not PRED_FILE.exists():
        print("[predict] ⚠ 没有待验证的预测")
        return

    # 读最后一条 pending
    lines = []
    with open(PRED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    pending = []
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("status") == "pending":
                pending.append(entry)
        except Exception:
            continue

    if not pending:
        print("[predict] ⚠ 没有待验证的预测")
        return

    # 取最近一条
    target = pending[-1]
    prediction = target["prediction"]
    deviated = _detect_deviation(prediction, actual)

    # 更新状态
    target["status"] = "verified"
    target["actual"] = actual
    target["deviated"] = deviated
    target["verified_at"] = datetime.now().isoformat()

    # 写回
    updated_lines = []
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("id") == target["id"]:
                updated_lines.append(json.dumps(target, ensure_ascii=False))
            else:
                updated_lines.append(line)
        except Exception:
            updated_lines.append(line)

    with open(PRED_FILE, "w", encoding="utf-8") as f:
        for line in updated_lines:
            f.write(line + "\n")

    if deviated:
        print(f"[predict] ❌ 偏差！")
        print(f"[predict]    预测: {prediction[:80]}")
        print(f"[predict]    实际: {actual[:80]}")

        # 写偏差日志
        dev_entry = {
            "time": datetime.now().isoformat(),
            "prediction_id": target["id"],
            "prediction": prediction,
            "actual": actual,
            "confidence": target["confidence"],
        }
        with open(DEVIATIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(dev_entry, ensure_ascii=False) + "\n")
        print(f"[predict]    偏差已记录 → deviations.jsonl")
    else:
        print(f"[predict] ✅ 预测匹配！")


def _detect_deviation(prediction: str, actual: str) -> bool:
    """判断预测与实际是否偏差。基于关键词匹配。"""
    pred = prediction.lower()
    act = actual.lower()

    # 预测"不会有问题"，实际出现负面信号 → 偏差
    predicts_ok = any(w in pred for w in ["不会", "没有", "没问题", "正常", "成功",
                                           "一次通过", "不会报错", "不报错"])
    # 但先排除"无错误""没问题"这类正面表述
    actual_negative_signals = ["报错", "失败", "不行", "异常", "超时", "refused",
                               "denied", "invalid", "syntaxerror", "traceback",
                               "exception", "404", "500"]
    # "无错误" "没问题" "没报错" 不算负面
    actual_bad = any(w in act for w in actual_negative_signals) and \
                 not any(w in act for w in ["无错误", "没问题", "没报错", "没有错误",
                                            "没有报错", "无异常", "正常"])

    if predicts_ok and actual_bad:
        return True

    return False


def _cleanup_stale():
    """删除过于陈旧（>7天）的 pending 预测。"""
    if not PRED_FILE.exists():
        return

    lines = []
    with open(PRED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    cutoff = datetime.now().timestamp() - 7 * 86400
    kept = []
    removed = 0
    for line in lines:
        try:
            entry = json.loads(line)
            if entry.get("status") == "pending":
                t = datetime.fromisoformat(entry["time"]).timestamp()
                if t < cutoff:
                    entry["status"] = "expired"
                    entry["actual"] = "超时未验证"
                    removed += 1
            kept.append(json.dumps(entry, ensure_ascii=False))
        except Exception:
            kept.append(line)

    if removed > 0:
        with open(PRED_FILE, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
        print(f"[predict] 🧹 清理了 {removed} 条过期预测")


def list_predictions():
    """列出最近的预测。"""
    if not PRED_FILE.exists():
        print("[predict] 无预测记录")
        return

    lines = []
    with open(PRED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)

    print(f"\n{'ID':<18} {'状态':<10} {'置信度':<8} 预测")
    print("-" * 80)
    for line in lines[-15:]:
        try:
            e = json.loads(line)
            status = e.get("status", "?")
            conf = f"{e.get('confidence', 0):.0%}"
            pred = e.get("prediction", "")[:50]
            icon = "✅" if status == "verified" and not e.get("deviated") else \
                   "❌" if e.get("deviated") else \
                   "⏳" if status == "pending" else \
                   "💤"
            print(f"{e.get('id','?'):<18} {icon} {status:<8} {conf:<8} {pred}")
        except Exception:
            continue


def stats():
    """预测准确率统计。"""
    if not PRED_FILE.exists():
        print("[predict] 无预测记录")
        return

    total = 0
    verified = 0
    deviated = 0
    with open(PRED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                total += 1
                if e.get("status") == "verified":
                    verified += 1
                    if e.get("deviated"):
                        deviated += 1
            except Exception:
                continue

    if verified == 0:
        print(f"[predict] 共 {total} 条预测，0 条已验证")
        return

    accuracy = (verified - deviated) / verified * 100
    print(f"[predict] 共 {total} 条预测，{verified} 条已验证")
    print(f"[predict] 偏差 {deviated} 条，准确率 {accuracy:.0f}%")


def main():
    if len(sys.argv) < 2:
        print("预测编码闭环工具")
        print()
        print("子命令:")
        print("  record  \"预测内容\" [--confidence 0.8]    记录预测")
        print("  verify  \"实际结果\"                       验证预测")
        print("  list                                      列出最近预测")
        print("  stats                                     统计准确率")
        return

    cmd = sys.argv[1]

    if cmd == "record":
        if len(sys.argv) < 3:
            record_help()
            return
        conf = 0.7
        for i, arg in enumerate(sys.argv):
            if arg == "--confidence" and i + 1 < len(sys.argv):
                try:
                    conf = float(sys.argv[i + 1])
                except ValueError:
                    pass
        record(sys.argv[2], conf)

    elif cmd in ("verify", "check"):
        if len(sys.argv) < 3:
            print("用法: python3 predict.py verify \"实际结果描述\"")
            return
        verify(sys.argv[2])

    elif cmd == "list":
        list_predictions()

    elif cmd == "stats":
        stats()

    else:
        print(f"未知命令: {cmd}")


if __name__ == "__main__":
    main()
