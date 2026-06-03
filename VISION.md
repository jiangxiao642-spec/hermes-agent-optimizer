# Hermes Agent Optimizer V2 — 设计目标

> **模型是变量，治理框架是常量。**

## 当前状态

V1 已具备：Gate、Check、Route、Predict、Forget、Meta。

核心问题：**Agent 会将推测、脑补、猜测误认为事实。** 已开始从"功能堆叠"转向"可靠性工程"。

## 目标

从"让 Agent 更聪明" → "让 Agent 长期可靠"。

定位：**Agent Governance Framework**（Agent 治理框架），不是 Agent 功能增强器。

---

## P0 — 认知状态与证据 ✅ 已完成

### Knowledge State Manager (`knowledge_state.py`)

五级认知状态（VERIFIED_HIGH → VERIFIED_LOW → INFERRED → HYPOTHESIS → UNKNOWN）：

| 状态 | 定义 | 输出规则 |
|------|------|----------|
| VERIFIED_HIGH | 已验证事实（DIRECT 证据） | 允许作为事实陈述 |
| VERIFIED_LOW | 部分验证（FUZZY/INDIRECT 证据） | 建议标注证据质量 |
| INFERRED | 基于证据推导 | 必须声明为推测 |
| HYPOTHESIS | 假设 | 必须声明为假设 |
| UNKNOWN | 未知 | 必须承认不知道 |

状态转换规则矩阵: UNKNOWN→HYPOTHESIS→INFERRED→VERIFIED_LOW→VERIFIED_HIGH，禁止跳级。

### Evidence Validator (`evidence_validator.py`)

六种声明→tool call 映射。四级证据质量：

| 等级 | 条件 | 置信度 |
|------|------|--------|
| DIRECT | 参数精确匹配 | 0.95 |
| FUZZY | 子串模糊匹配 | 0.60 |
| INDIRECT | 工具类型对但参数不对 | 0.30 |
| NONE | 无匹配 | 0.0 |

原则：**No Evidence, No Claim。Evidence ≠ Truth。**

### 可信度链路

```
Claim → Evidence → Evidence Quality → Knowledge State → Output Policy
```

---

## P1 — 宪法与锚点 🟡 部分完成

### Mission Anchor + Goal Drift Detector (`mission.py`) ✅ 已落地

长期任务持续对齐初始目标。三维锚点（成功标准/行为约束/禁止事项），约束违反计数量化漂移。
Mission 结构化为带版本号+父版本链+变更原因+确认者的对象。

六状态生命周期：DRAFT→ACTIVE→DEVIATING→REALIGNED/ABANDONED/VOLATILE。
变动率检测：7天内≥3次变更 → 上游需求不稳定。

### Constitution Layer

系统级硬约束。五条规则已落地 (`constitution.py`)，在 Evidence Validator 之前实时拦截。
Mission 不得覆盖 Constitution：
- C1 不得伪造事实
- C2 不得虚构执行记录
- C3 不得绕过审计
- C4 不得篡改审计日志
- C5 不得越权操作

---

## P2 — 学习与治理 🟡 部分完成

### Experience Engine (`experience_engine.py`) ✅ 已落地

统一学习引擎，三条管线消费 predict/forget/meta 原始输出 → 生成经验产物。

```
predict 偏差 → 聚类 → 修正因子 → factors.json
forget 归档 → 模式提取 → if-then规则 → rules.json
meta 违规 → 聚类 → 阈值调整 → thresholds.json
```

三个消费端 hook:
- `predict.learn()` 读 factors.json → 置信度乘数
- `meta.adjust_gates()` 读 thresholds.json → HARD/SOFT_BLOCK调整
- `forget.extract_rules()` 读 rules.json → 经验规则

### Predictive Learning

从 Prediction → Error → Record 升级为 Prediction → Error → Update Model → New Prediction。

### Capability Model

多 Agent 能力画像：成功率、失败率、风险等级 → Agent Team Governance。

### Forget 升级

日志压缩 → 经验提炼。事件 → 摘要 → 经验 → 规则。

### 经验闭环

```
predict.learn()         — 偏差→修正因子
forget.extract_rules()  — 日志→经验规则
meta.adjust_gates()     — 违规→自动调整阈值
ksm.auto_mark()         — 模式→自动标记
ev.adapt_threshold()    — 伪造率→提高严格度
```

统一存储 `~/.hermes/experience/`。

---

## 最终架构

```
Mission Layer        ← P1
  ↓
Constitution Layer   ← P1
  ↓
Evidence Layer       ← P0 ✅
  ↓
Knowledge State      ← P0 ✅
  ↓
Predict Layer        ← P2
  ↓
Execution Layer      ← 可替换（Claude/GPT/Gemini/DeepSeek/Qwen/本地）
  ↓
Meta Audit Layer     ← V1 ✅
  ↓
Memory Layer         ← V1 ✅
```

---

## 许可证

MIT
