# Hermes Agent 通用优化框架

> 下载即用。让 Hermes Agent 不再裸跑。

## 这是什么

一套给 Hermes Agent 的**认知增强中间件**。不是改 Hermes 源码，而是在 Gateway 和模型之间坐一层透明代理，自动注入知识库、多层防线、预测编码闭环、主动遗忘、元认知监控。

## 解决的问题

| 问题 | 症状 | 本方案 |
|------|------|--------|
| 检索断链 | 知识/Skill 存在但不调用 | 关键词路由自动注入上下文 |
| 指令模糊 | 收到"搞一下那个"就动手 | 四项检查缺一即追问 |
| 做完不验证 | 说"搞定了"但没有证据 | 预测编码闭环——先预测再验证 |
| 记忆爆炸 | 上下文越来越长 | 主动遗忘——自动压缩旧数据 |
| 规则写了自己不读 | declaration 形同虚设 | gate.py 前置拦截，不过关不动手 |

## 安装

```bash
# 1. 克隆
git clone https://github.com/jiangxiao642-spec/hermes-agent-optimizer.git
cd hermes-agent-optimizer

# 2. 安装依赖
pip install fastapi uvicorn httpx pyyaml --break-system-packages

# 3. 初始化知识库
mkdir -p ~/.hermes/knowledge
cp knowledge/*.md ~/.hermes/knowledge/

# 4. 安装路由中间件（systemd 自动启动）
sudo cp config/systemd/hermes-router.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-router.service

# 5. 切换 Gateway 到中间件
# 编辑 ~/.hermes/config.yaml，将 model 段的 base_url 改为:
#   base_url: http://localhost:8000/v1
```

详细说明见 [INSTALL.md](INSTALL.md)

## 架构

```
用户消息
  ↓
Hermes Gateway (:8642)
  ↓
路由中间件 (:8000)          ← 本框架的核心
  ├─ gate.py 类型检测
  ├─ check_instruction.py 指令完整性
  ├─ route_and_prepare.py 知识注入
  └─ predict.py 预测编码
  ↓
DeepSeek API (或其他后端)
```

## 六个模块

| 模块 | 功能 | 触发方式 |
|------|------|----------|
| `gate.py` | 任务类型检测，自动匹配 Skill 链 | 每条消息自动过 |
| `check_instruction.py` | 四项缺失检查（目标/约束/格式/指代） | 指令不完整时追问 |
| `route_and_prepare.py` | 关键词路由 → 自动注入知识库 | Gateway 透明代理 |
| `predict.py` | 预测编码闭环——先预测再验证 | 任务前 record，任务后 verify |
| `forget.py` | 主动遗忘——自动压缩旧数据 | cron 定时执行 |
| `meta_check.py` | 元认知跳过检测——是否绕过 Gate | 会话结束审计 |

## 配置模板

`config/config.yaml.example` 是一个完整的工作配置示例，包括：
- 知识路由规则
- 多层防线开关
- 遗忘阈值
- 预测置信度

## 依赖

- Python 3.10+
- Hermes Agent（已安装并运行）
- DeepSeek API Key（或其他 OpenAI 兼容后端）

## 许可证

MIT
