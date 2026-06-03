# Instinct 层 — 预判型规则

ECC（affaan-m/ECC）的四层架构中，我们缺的是 instinct 层：

| ECC 层 | 我们的对照 | 状态 |
|---|---|---|
| Skills | task-dispatcher + 自定义 skill | ✅ |
| Instincts | 预判型规则（"遇到X情况→先做Y"） | ❌ |
| Memory | agentmemory | ✅ |
| Security | agent_safety_rules | ✅ |

## 什么是 Instinct

Instinct 不是 skill（需要手动加载），不是 memory（事后记录），不是 security（硬边界）。
**是预判型规则**——在特定条件触发时，无需判断、自动执行。

ECC 的实现：parse_instinct_file() 解析 YAML frontmatter + Action/Evidence/Examples 段，confidence scoring。

## 我们的落地

不需要模仿 ECC 的文件格式。用 declaration 硬门 + gate.py 替代：
- 硬门 = instinct 触发条件（"碰壁≥2次→切 API"）
- gate.py = instinct 执行器
- 自检表 = instinct 验证

本质上我们已经有了 instinct 层，只是没叫这个名字。

## 可以加强的

ECC 的 instinct 引入 confidence scoring（置信度评分）——如果一条规则连续 5 次有效，自动提升为 instinct；如果连续 3 次无效，降级回 skill。

我们可以偷这个：
- 规则升级：自检表第 N 条连续 5 次拦截成功 → 焊进硬门
- 规则降级：硬门某条连续 3 次未命中 → 退回软规则
