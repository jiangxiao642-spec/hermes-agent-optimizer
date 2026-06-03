# Hermes Agent Optimizer

**Agent 治理框架** —— 让 LLM Agent 不再靠提示词自律。

## 模块

| 模块 | 做什么 |
|---|---|
| `gate_enforcer/` | 插件：工具调用前拦截——Gate 没过就阻断 |
| `scripts/gate.py` | 任务类型路由器——判类型 → 匹配 skill 链 |
| `scripts/tool_search.py` | 分层索引搜索——标签+消歧，skill 不再堆在一起 |
| `scripts/check_instruction.py` | 指令完整性扫描——目标/约束/格式/指代 |
| `scripts/constitution.py` | 宪法层——正则+语义双层防线 |
| `scripts/propose_rule_change.py` | 规则进化——沙箱 dry-run → 3 次命中自动升级 |
| `scripts/evolution_metrics.py` | 进化曲线——宪法违规/Gate绕过/闭环缺失统计 |
| `scripts/output_compressor.py` | 工具输出压缩——去时间戳/进度条/空行 |

## 新：Mirsky's Ladder 架构（v2）

参考 "Agents of Chaos" (2026-05) 论文发现：**自主基础设施 ≠ 自主。没有内在自我模型，心跳只是死的基础设施。**

四层架构：

```
DMN（默认模式网络）— 持续后台感知 → 发现任务
GOALS.md           — 权限表 ✅自主/⛔确认/🚫禁止
执行层             — 自主 spawn 带记忆的 agent session
护栏层             — gate_enforcer 框架级拦截 + 宪法硬约束
```

详见 `knowledge/mirsky-ladder-architecture.md`

## 安装

```bash
git clone https://github.com/jiangxiao642-spec/hermes-agent-optimizer
cp -r scripts/* ~/.hermes/scripts/
cp -r plugins/* ~/.hermes/plugins/
cp -r knowledge/* ~/.hermes/knowledge/
cp config/skill_index.json ~/.hermes/

# 启用 gate_enforcer 插件
hermes plugins enable gate_enforcer
hermes gateway restart
```

## 许可证

MIT
