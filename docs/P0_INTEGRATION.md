# P0 模块对接说明

## 两个新模块

### Knowledge State Manager (`knowledge_state.py`)
认知状态标记系统。所有信息四个状态：VERIFIED / INFERRED / HYPOTHESIS / UNKNOWN。

### Evidence Validator (`evidence_validator.py`)
证据验证层。所有事实性声明必须有 tool call 记录支撑。

## 与其他模块的关系

```
route_and_prepare.py (知识注入)
  ↓
Agent 处理请求
  ↓
━━━━━━━ 输出闸门 ━━━━━━━
  ↓
constitution.check()              ← 【新】宪法硬约束 — 伪造本身就该拦
  ↓
evidence_validator.scan_output()  ← 检查"声称做过的事"是否真有 tool call
  ↓
knowledge_state.check()           ← 检查"事实性声明"是否标记了状态
  ↓
通过 → 返回用户
不通过 → 在回复前插入警告
  ↓
meta_check.py (事后审计)          ← 会话结束后检查整体合规
```

## 集成方式

在 `route_and_prepare.py` 的 `chat_completions` 端点中，Agent 产出回复后插入两道闸：

```python
from knowledge_state import KnowledgeStateManager
from evidence_validator import EvidenceValidator

ksm = KnowledgeStateManager()
ev = EvidenceValidator()

# ... Agent 处理后得到 response_text ...

# 1. 证据验证
evidence_violations = ev.scan_output(response_text, session_id)
if evidence_violations:
    warning = "⚠️ 以下声明缺少工具调用记录:\n"
    for v in evidence_violations:
        warning += f"  • {v['claim'][:60]}: {v['issue']}\n"
    response_text = warning + "\n" + response_text

# 2. 认知状态检查
state_violations = ksm.check(response_text)
if state_violations:
    warning = "⚠️ 以下事实性声明未标记状态:\n"
    for v in state_violations:
        warning += f"  • {v['claim'][:60]}: {v['issue']}\n"
    response_text = warning + "\n" + response_text
```

## 数据存储

| 模块 | 存储位置 | 格式 |
|------|----------|------|
| knowledge_state | `~/.hermes/knowledge_state/items.jsonl` | JSONL |
| evidence_validator | state.db (messages 表) | SQLite（共享） |

## CLI 快速测试

```bash
# 标记一条知识
python3 knowledge_state.py mark "base_url 指向 localhost:8000" --state VERIFIED --source file_read

# 检查输出
echo "已读取 config.yaml，确认配置正确" | python3 knowledge_state.py check

# 验证声明
python3 evidence_validator.py validate "已读取 config.yaml" --session <id>

# 扫描输出
echo "已搜索相关资料，GPT说这个方向可行" | python3 evidence_validator.py scan --session <id>
```
