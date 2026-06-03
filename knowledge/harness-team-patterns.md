# 多 Agent 团队模式

从 revfactory/harness 偷的 6 种团队架构模式。用于 task-dispatcher 类型四（复杂任务）的高级模式。

## 六种模式

### 1. Pipeline（流水线）
A → B → C，每步依赖上一步输出。
适用：CAD 出图（解析DXF→规范检查→生成标注→搬文件）、数据处理链

### 2. Fan-out/Fan-in（扇出扇入）
一个任务拆 N 个子任务并行，结果汇聚。
适用：多文件审查、多页抓取、多维度打分

### 3. Expert Pool（专家池）
多个专家 agent，按任务类型匹配最合适的。
适用：多语言代码审查（Python专家/TS专家/Go专家轮询）

### 4. Producer-Reviewer（生产者-审查者）
一个写、一个审，交替迭代。
适用：内容创作（写稿→humanizer打分→改稿→再打分）

### 5. Supervisor（监督者）
一个监督 agent 派活给多个 worker，监控进度、处理异常。
适用：长时间自主任务、多步骤项目

### 6. Hierarchical Delegation（层级委派）
监督者把子任务委派给子监督者，层层分解。
适用：超大项目（如完整施工图出图：平面/立面/剖面/明细表各一个团队）

## 决策树

| 条件 | 推荐模式 |
|---|---|
| 步骤有严格顺序依赖 | Pipeline |
| 子任务独立无依赖 | Fan-out/Fan-in |
| 不同领域需不同技能 | Expert Pool |
| 产出需质量把关 | Producer-Reviewer |
| 单次任务超 10 步 | Supervisor |
| 子任务还能再拆 | Hierarchical Delegation |

## 与 delegate_task 的对应

delegate_task 本质上是 Fan-out 的轻量版。要升级为完整模式：
- Pipeline → 串行调 delegate_task
- Fan-out → 并行调 delegate_task（已有，max 3 路）
- Expert Pool → 按 task 语言/领域匹配 skill
- Producer-Reviewer → 第一轮 delegate_task 产出 → 第二轮 delegate_task 审查
