# 安装说明

## 前提

- Hermes Agent 已安装并运行
- Python 3.10+
- DeepSeek API Key（或其他 OpenAI 兼容后端）

## 安装

### 1. 克隆仓库

```bash
git clone https://github.com/jiangxiao642-spec/hermes-agent-optimizer.git
cd hermes-agent-optimizer
```

### 2. 安装 Python 依赖

```bash
pip install fastapi uvicorn httpx pyyaml --break-system-packages
```

### 3. 部署文件

```bash
# 脚本
cp scripts/*.py ~/.hermes/scripts/

# 知识库
mkdir -p ~/.hermes/knowledge
cp knowledge/*.md ~/.hermes/knowledge/

# 规则
cp rules/core-principles.md ~/.hermes/knowledge/
```

### 4. 安装 systemd 服务

```bash
mkdir -p ~/.config/systemd/user/
cp config/systemd/hermes-router.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-router.service
```

### 5. 验证

```bash
# 检查路由中间件
curl http://localhost:8000/health

# 应返回 {"status":"ok","routes":["operations","decision","rules",...]}
```

### 6. 切换 Gateway 到中间件

编辑 `~/.hermes/config.yaml`，将 `model.base_url` 改为：

```yaml
model:
  base_url: http://localhost:8000/v1
```

重启 Gateway：

```bash
systemctl --user restart hermes-gateway
```

## 验证效果

发一条消息给 Hermes。如果中间件起作用，你会看到 system message 被注入了相关知识。

查看日志：

```bash
journalctl --user -u hermes-router.service -f
```

## 卸载

```bash
systemctl --user disable --now hermes-router.service
rm ~/.config/systemd/user/hermes-router.service
systemctl --user daemon-reload

# 恢复 config.yaml 中的 base_url 为原始 API 地址
```
