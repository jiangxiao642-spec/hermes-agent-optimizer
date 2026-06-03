# Hermes Optimizer V2 — 调整方案（基于 GPT 诊断）

## 诊断

有自我迭代思想（8/10），实现停在"观察→记录"（3-4/10）。
缺一个 Learning Engine 把 predict / forget / meta / knowledge_state / evidence_validator 串成闭环。

## 核心缺口

```
现有： 观察 → 记录
目标： 观察 → 记录 → 分析 → 生成经验 → 修改行为 → 验证效果
```

五个模块都做到了前两步，后四步分散在各处但没有串联层。

## 调整：不加模块，加闭环

不是新建 experience_engine.py 取代一切——那会变成另一个孤岛。
而是在现有模块上各加一个 **闭环方法**，共享同一个经验存储。

### 1. predict.py → 加 `learn()`

```python
# 现有
predict.py record "预测" → verify "实际" → 记录偏差

# 新增
predict.py learn  → 读取 deviations.jsonl
                  → 聚类同类偏差
                  → 生成修正因子（如"涉及文件操作时初始预测×3"）
                  → 写回 ~/.hermes/experience/factors.json
```

下次 `record()` 时自动加载 factors.json 调整初始预测。

### 2. forget.py → 加 `extract_rules()`

```python
# 现有
forget.py → 压缩旧日志 → 统计摘要

# 新增
forget.py extract  → 读取压缩摘要 + agentmemory 教训
                   → 提炼为 if-then 规则
                   → 写 ~/.hermes/experience/rules.json
```

例如：从"数据库操作 100 次中 23 次失败"提炼为
`{"condition": "任务含数据库操作", "action": "执行前必须验证Schema", "confidence": 0.7}`

### 3. meta_check.py → 加 `adjust_gates()`

```python
# 现有
meta_check.py → 检测违规 → 记录

# 新增
meta_check.py adjust → 读取违规记录
                      → 发现同类违规 ≥N 次
                      → 自动提高对应 Gate 阈值
                      → 写 ~/.hermes/experience/thresholds.json
```

例如：连续 30 次"跳过 skill 加载" → 自动把 skill 检查从 SOFT_BLOCK 升级为 HARD_BLOCK。

### 4. knowledge_state.py → 加 `auto_mark()`

```python
# 现有
ksm.check() → 发现未标记声明 → 报告

# 新增
ksm.auto_mark() → 读取未标记声明
                 → 匹配 evidence_validator 的证据链
                 → 有证据 → 自动标记为 VERIFIED
                 → 无证据 → 自动标记为 UNKNOWN
                 → 写经验：同类声明模式 → 默认状态
```

### 5. evidence_validator.py → 加 `adapt_threshold()`

```python
# 现有
ev.scan_output() → 验证 → 报告违规

# 新增
ev.adapt_threshold() → 读取违规历史
                      → 发现某类声明伪造率 >30%
                      → 自动提高该类声明的验证严格度
                      → 写 ~/.hermes/experience/evidence_profiles.json
```

## 统一经验存储

```
~/.hermes/experience/
├── factors.json          # predict 修正因子
├── rules.json            # forget 提炼的规则
├── thresholds.json       # meta 自动调整的阈值
├── evidence_profiles.json # evidence 验证严格度
└── auto_marks.json       # knowledge_state 自动标记规则
```

所有模块读同一个目录，消费彼此的输出。

## 最小可行版（先做哪条链路）

优先级最高的闭环：**meta_check.adjust_gates()**

原因：
1. 数据现成——meta_check 已经在记录违规
2. 效果直接——自动提高阈值比修正预测参数更直观
3. 不依赖其他模块改造

三步实现：
```
1. meta_check 运行时读 ~/.hermes/experience/thresholds.json
2. 发现同类违规 ≥10 次 → 写入阈值提升建议
3. gate.py 下次启动时读 thresholds.json，自动应用
```

## 架构图（调整后）

```
predict ──→ learn() ──────────────┐
forget ──→ extract_rules() ───────┤
meta_check ──→ adjust_gates() ────┼──→ ~/.hermes/experience/
knowledge_state ──→ auto_mark() ──┤      ├── factors.json
evidence_validator ──→ adapt() ───┘      ├── rules.json
                                          ├── thresholds.json
                                          ├── evidence_profiles.json
                                          └── auto_marks.json
                                          ↓
                              下次运行时自动加载
                              → 行为永久改变
```
