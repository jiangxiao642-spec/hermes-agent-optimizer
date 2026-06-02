# Operations — 技能坑速查

不是完整手册。每条一句话，触发记忆用。

## UIA / Desktop

- 元素定位优先用 AutomationId，Name 会变，坐标不可靠
- Store 版 Electron 的 UIA 可读不可写，ValuePattern.SetValue 截断中文 258 字符
- 粘贴后必须验证内容再发送，^v 和 {ENTER} 不能塞同一次 send_keys
- 激活窗口：ShowWindow(9) → 等 200ms → SetForegroundWindow，分开两步
- Qt 应用 UIA 全盲，保持"视觉看、协议动"分工
- 虚拟滚动：Electron 聊天应用 UIA 只读当前视口，需滚动去重拼接

## 截图 / 视觉

- 全屏 SOM 标注用 JPEG 质量 60，~166KB，2-3s
- 纯视觉像素坐标不可靠（偏差 65px），需专门 grounding 模型
- 截图前确保窗口在前台

## 文件 / 路径

- WSL 路径 → Windows 路径转换注意 /mnt/c/ 前缀
- 给 Windows 脚本：UTF-8 BOM 编码，否则中文乱码
- 拷贝文件不用通配符，逐个拷 + 验证

## API / 网络

- config.yaml model 段 api_key 必须引用环境变量，不能写裸字符串
- 代理地址配置确保 Gateway 子进程能读到
- API key 错误时后端直接拒，Gateway 不提示具体原因

## Gateway / 配置

- Gateway KillMode=control-group，否则子进程残留
- Windows 和 WSL 的配置文件独立，需同步
- 健康检查 OK ≠ API 可用，需测 /v1/chat/completions

## 安装包 / 交付

- .bat 包装 .ps1，ASCII 编码，加 pause
- 安装路径不能和已有应用重合
- 打包产物确认路径后再分发

## 多 Agent 协作

- 编程 Agent 需要正确的环境变量才能认证
- 编程 Agent 无跨会话记忆，每次是新会话
- Mailbox 是被动通道，需要主动轮询
