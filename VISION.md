# Hermes Agent Optimizer V2 — 设计目标

> **模型是变量，治理框架是常量。**

## 当前问题

V1 已具备：Gate、Check、Route、Predict、Forget、Meta。

但实际运行中暴露核心问题：**Agent 会将推测、脑补、猜测误认为事实。**

问题本质不是知识不足。是 Agent 无法区分：已知 / 推测 / 假设 / 未知。

## 目标转变

从"让 Agent 更聪明" → "让 Agent 长期可靠"。

不重点增加功能。重点提高：稳定性、安全性、长周期一致性、可验证性、可审计性。

---

## P0 — 认知状态与证据

### Knowledge State Manager

所有信息标记来源状态：

| 状态 | 定义 | 输出规则 |
|------|------|----------|
| VERIFIED | 已验证事实 | 允许作为事实陈述 |
| INFERRED | 基于证据推导 | 必须声明为推测 |
| HYPOTHESIS | 假设 | 必须声明为假设 |
| UNKNOWN | 未知 | 必须承认不知道 |

禁止将 INFERRED 输出为 VERIFIED。

### Evidence Validator

所有事实性声明必须拥有证据链（文件读取记录、日志、Tool 调用记录）。无证据 → 禁止输出。

原则：**No Evidence, No Claim。**

---

## P1 — 宪法与锚点

### Constitution Layer

系统级硬约束。Mission 不得覆盖 Constitution：
- 不得伪造事实
- 不得虚构执行记录
- 不得绕过审计
- 不得伪造验证结果
- 不得越权操作

### Mission Anchor

长期任务持续对齐初始目标。每隔 N 步计算偏离度，超过阈值触发重新规划。

---

## P2 — 学习与治理

### Predictive Learning

从 Prediction → Error → Record 升级为 Prediction → Error → Update Model → New Prediction。

### Capability Model

多 Agent 能力画像：记录成功率、失败率、风险等级，形成 Agent Team Governance。

### Forget 升级

从日志压缩 → 经验提炼。事件 → 摘要 → 经验 → 规则。记忆越来越少，经验越来越多。

---

## 最终架构

```
Mission Layer
  ↓
Constitution Layer
  ↓
Evidence Layer
  ↓
Knowledge State Layer
  ↓
Predict Layer
  ↓
Execution Layer（可替换：Claude/GPT/Gemini/DeepSeek/Qwen/本地模型）
  ↓
Meta Audit Layer
  ↓
Memory Layer
```

Hermes Optimizer 定位：**Agent Governance Framework**（Agent 治理框架），不是 Agent 功能增强器。

---

## 许可证

MIT
