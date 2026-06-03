# Agent Runtime Governance — 学术对齐报告

> 目标：把 Hermes Agent Optimizer 的每个模块映射到已发表的学术框架，
> 确认哪些有文献支撑、哪些是空白、哪些是真正的差异化。

---

## 一、MI9 六组件对齐 (arxiv 2508.03858, AAAI 2026)

MI9 是目前最完整的 Agent 运行时治理框架。

| MI9 组件 | 我们的对应 | 状态 | 差异 |
|----------|-----------|------|------|
| Agency-Risk Index | Evidence Quality (DIRECT/FUZZY/INDIRECT/NONE) | ✅ 已有 | MI9 是动态评分，我们是静态分级 |
| Agent-semantic telemetry | `gate.log` + `check.log` + `constitution.log` | 🟡 基础 | MI9 有语义级采集，我们是模式匹配 |
| Continuous authorization monitoring | `constitution.py` 实时拦截 | ✅ 已有 | 架构一致 |
| FSM-based conformance engines | Knowledge State (UNKNOWN→HYPOTHESIS→INFERRED→VERIFIED_LOW→VERIFIED_HIGH) | ✅ 已有 | MI9 是通用 FSM，我们是五级认知状态机 |
| Goal-conditioned drift detection | `mission.py` + 三维锚点 + 约束违反计数 | ✅ 已有 | MI9 用语义距离，我们用约束计数（更可审计） |
| Graduated containment strategies | Constitution PASS/SOFT_BLOCK/HARD_BLOCK | 🟡 部分 | MI9 有更细粒度的渐进式遏制 |

**结论：六个组件全部有对应。差距在颗粒度（MI9 更细）和非功能需求（我们的更可解释）。**

---

## 二、ProbGuard 对齐 (arxiv 2508.00500, Aug 2025)

ProbGuard 核心：**概率风险预测**——在违规发生之前就预判。

| ProbGuard 特征 | 我们的对应 | 状态 |
|---------------|-----------|------|
| Probabilistic risk prediction | `predict.py` 预测编码闭环 | 🟡 有框架，`learn()` 刚落地 |
| Semantic validity constraints | `constitution.py` 正则规则 | 🟡 正则层，未到语义层 |
| PAC-style guarantees | 无 | ❌ 缺失 |
| 65% 不安全行为降低 | 无基准测试 | ❌ 缺少评估 |

**结论：核心思想一致（预测→预防），但 ProbGuard 有理论保证（PAC-learning），我们靠经验规则。**

---

## 三、Goal Drift 论文对齐 (arxiv 2505.02709, May 2025)

首篇系统研究 Agent 目标漂移的论文。

| 论文方法 | 我们的对应 | 状态 |
|---------|-----------|------|
| 漂移检测 | `mission.py` 约束违反计数 | ✅ 已有 |
| 漂移量化 | 三维锚点（成功标准/行为约束/禁止事项） | ✅ 已有 |
| 语义距离测量 | 无（选择了约束计数） | 🟡 有意识地选了不同路径 |
| 数据集 | 无 | ❌ 缺少 |
| 评估基准 | 无 | ❌ 缺少 |

**结论：论文用语义距离，我们用约束计数——这是一个有意识的选择。语义距离不可解释，约束计数可审计。但缺少评估数据。**

---

## 四、微软 Agent Governance Toolkit (Apr 2026, MIT)

微软开源，工业侧验证。

| 微软 AGT | 我们的对应 | 状态 |
|----------|-----------|------|
| Runtime security governance | Constitution + Evidence 两层 | ✅ 架构一致 |
| 开源 MIT | MIT ✅ | 协议一致 |
| 集成 LangChain | 独立中间件（不绑定框架） | 🟡 我们的更通用 |
| 企业级审计 | logs/ 目录 | 🟡 基础版 |

**结论：微软在做同一件事，验证了方向。我们是独立中间件（不绑定 LangChain），更通用但不是更成熟。**

---

## 五、Thought Management System (ScienceDirect, Jan 2026)

长期目标驱动推理框架。

| TMS 特征 | 我们的对应 | 状态 |
|---------|-----------|------|
| Long-horizon reasoning | `mission.py` 生命周期管理 | ✅ 已有 |
| Goal-driven architecture | Mission Anchor | ✅ 已有 |
| 六状态生命周期 | DRAFT→ACTIVE→DEVIATING→VOLATILE→REALIGNED→ABANDONED | ✅ 已有 |
| 偏离度计算 | 约束违反加权 | ✅ 已有 |

**结论：高度对齐。我们的六状态生命周期是独立的创新设计。**

---

## 六、TRiSM 框架对齐 (Jan 2026)

Trust, Risk, Security Management — 已对齐 NIST AI RMF / EU AI Act / ISO 42001。

| TRiSM 维度 | 我们的对应 | 状态 |
|-----------|-----------|------|
| Trust（信任） | Evidence Quality + Knowledge State | ✅ |
| Risk（风险） | predict.py 预测偏差 | 🟡 基础 |
| Security（安全） | Constitution + approvals.mode | ✅ |
| Transparency（透明） | logs/ + state.db | 🟡 基础 |
| Accountability（可问责） | evidence_validator 证据链 | ✅ |
| Human oversight（人工监督） | SOFT_BLOCK→HARD_BLOCK 升级 | 🟡 |

**结论：TRiSM 六个维度我们基本覆盖，但 Risk 和 Transparency 偏弱。这是合规对齐的直接路径。**

---

## 七、差异化和空白

### 我们做得比论文好的

1. **约束违反计数 vs 语义距离** — 我们的 Mission 偏离度用可解释的计数，不是黑盒 embedding。企业审计友好。
2. **五级认知状态机** — Knowledge State 的 UNKNOWN→VERIFIED_HIGH 链在 MI9 中对应通用 FSM，我们的更具体。
3. **框架无关** — 不是 LangChain 插件，是透明中间件。

### 论文有我们没有的

1. **PAC 理论保证** (ProbGuard)
2. **语义级违规检测** (MI9 telemetry)
3. **评估基准和数据集** (Goal Drift 论文)
4. **合规映射** (TRiSM → NIST/EU/ISO)

### 真正的空白（值得探索的）

1. **动态风险评分** — MI9 的 Agency-Risk Index 是实时的，我们是静态分级。`experience_engine.py` 可以往这个方向走。
2. **合规映射层** — 把 Constitution 规则映射到 EU AI Act / NIST AI RMF 的具体条款。
3. **评估框架** — 没有基准测试，无法量化"65% 不安全行为降低"这种指标。

---

## 八、建议

1. **先对齐 MI9 的术语** — 改文档和 VISION.md，用学术界通用术语（如 "telemetry" 而非 "logs"、"conformance engine" 而非 "gate"）。
2. **补语义层** — Constitution V2 需要从正则升级到语义分类。
3. **建评估基准** — 最简单的开始：统计 Constitution 拦截率、Evidence 低置信度比例、Mission 偏离度趋势。
4. **差异化保留** — 约束违反计数、框架无关、五级状态机是我们的壁垒，不动。
