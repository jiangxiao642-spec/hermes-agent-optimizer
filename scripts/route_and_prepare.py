#!/usr/bin/env python3
"""知识路由中间件 — 在 Hermes Gateway 和后端 API 之间拦截请求，自动注入知识库上下文。

架构：Hermes Gateway → localhost:8000 → 本脚本 → 后端 API
对 Hermes 透明，不需要改核心代码。

启动：python3 route_and_prepare.py
"""

import json
import re
import os
import sys as _sys
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI()

# 确保同目录模块可在任意 CWD 被导入（模块级，线程安全）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in _sys.path:
    _sys.path.insert(0, _SCRIPTS_DIR)

HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
KNOWLEDGE_DIR = os.path.join(HERMES_HOME, "knowledge")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_URL = f"{DEEPSEEK_BASE}/chat/completions"
DEEPSEEK_TIMEOUT = 300.0
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def _get_api_key() -> str:
    """多路径查找 DEEPSEEK_API_KEY，按优先级：环境变量 > ~/.hermes/.env > 当前目录 .env"""
    # 1. 环境变量（Windows 用户级/系统级 或 Linux export）
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        return key

    # 2. ~/.hermes/.env
    hermes_env = os.path.join(HERMES_HOME, ".env")
    if os.path.exists(hermes_env):
        key = _read_key_from_env_file(hermes_env)
        if key:
            return key

    # 3. 当前目录 .env（用户从 GitHub 下载后可能放在这里）
    local_env = os.path.join(os.getcwd(), ".env")
    if os.path.exists(local_env):
        key = _read_key_from_env_file(local_env)
        if key:
            return key

    return ""


def _read_key_from_env_file(path: str) -> str:
    """从 .env 文件中提取 DEEPSEEK_API_KEY。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == "DEEPSEEK_API_KEY":
                    return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


# API key 延迟加载——不在模块导入时读，避免 .env 还没创建就固定为空
def _load_api_key() -> str:
    """每次请求前重新读取 API key（支持 .env 热更新，无缓存）"""
    return _get_api_key()

# ── 关键词路由表 ──────────────────────────────
KNOWLEDGE_ROUTING = {
    "operations": [
        "uia", "截图", "浏览器", "desktop", "notepad",
        "文件", "自动化", "autoui", "窗口", "点击", "坐标",
        "powershell", "bridge", "send_keys", "鼠标", "激活",
        "screenshot", "sketchup", "autocad", "cad",
    ],
    "decision": [
        "决策", "判断", "选", "权衡",
        "博弈", "系统思维", "魔鬼辩护", "批判",
        "定价", "策略",
    ],
    "rules": [
        "教训", "规则", "硬门",
        "gate", "违规", "纠正", "core-principles",
        "自检", "ood", "debug", "踩坑",
    ],
    "robustness": [
        "容错", "异常", "失败", "降级",
        "护盾", "验证", "verif", "robust",
    ],
    "collaboration": [
        "分工", "协作", "多agent", "agent间",
        "调度", "分发", "委托",
    ],
    "business": [
        "定价", "客户", "付费", "赚钱", "产品",
        "打包", "安装包", "用户",
    ],
}

ROUTE_TO_FILES = {
    "operations": ["operations.md"],
    "decision": [
        "critical-thinking.md",
        "systems-thinking.md",
        "game-theory.md",
    ],
    "rules": [
        "core-principles.md",
    ],
    "robustness": ["robustness.md"],
    "collaboration": ["collaboration.md"],
    "business": ["game-theory.md"],
}

DEFAULT_FILES = ["index.md"]

# ── Gate tid → 知识文件映射 ──────────────────
# Gate 判完类型后直接查表加载知识，不再跑关键词匹配
GATE_TID_TO_KNOWLEDGE = {
    "一": ["operations.md"],                            # CAD 制图
    "二": ["operations.md"],                            # 桌面 GUI
    "三A": ["critical-thinking.md"],                    # 内容创作
    "三B": ["critical-thinking.md"],                    # 视频脚本
    "三C": ["critical-thinking.md"],                    # 文案去 AI 味
    "四": ["core-principles.md", "robustness.md"],      # 编码 / 复杂任务
    "五": ["operations.md"],                            # 信息获取
    "六": ["game-theory.md"],                           # 打包 / 安装
    "七": ["core-principles.md"],                       # 规则进化
    "技术问答": ["core-principles.md"],                  # 技术问答兜底
}


def _gate_tid_to_files(tid: str) -> list[str]:
    """根据 gate 的 tid 直接决定加载哪些知识文件，不再跑关键词匹配。"""
    files = list(GATE_TID_TO_KNOWLEDGE.get(tid, DEFAULT_FILES))
    if "index.md" not in files:
        files.append("index.md")
    return files


def route(user_message: str) -> list[str]:
    """从用户消息中匹配知识文件。关键词匹配。"""
    # 防御：多模态 content 可能是 list 而非 str
    if not isinstance(user_message, str):
        return DEFAULT_FILES
    matched_routes: set[str] = set()
    msg_lower = user_message.lower()

    for route_name, keywords in KNOWLEDGE_ROUTING.items():
        for kw in keywords:
            if kw.lower() in msg_lower:
                matched_routes.add(route_name)
                break

    if not matched_routes:
        return DEFAULT_FILES

    files: list[str] = []
    for route_name in matched_routes:
        files.extend(ROUTE_TO_FILES.get(route_name, []))
    files = list(dict.fromkeys(files))
    if "index.md" not in files:
        files.append("index.md")
    return files


def load_knowledge(files: list[str]) -> str:
    """加载知识文件内容，拼接为上下文前缀。"""
    chunks: list[str] = []
    total_chars = 0
    max_chars = 8000

    for fname in files:
        fpath = os.path.join(KNOWLEDGE_DIR, fname)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            if len(content) > 3000:
                content = content[:3000] + "\n... (截断)"
            if total_chars + len(content) > max_chars:
                remaining = max_chars - total_chars
                content = content[:remaining] + "\n... (截断)"
            chunks.append(f"<!-- {fname} -->\n{content}")
            total_chars += len(content)
        except Exception:
            continue
        if total_chars >= max_chars:
            break

    return "\n\n".join(chunks)


def inject_knowledge(messages: list[dict], knowledge_text: str) -> list[dict]:
    """将知识注入到 system message 前缀。"""
    if not knowledge_text:
        return messages

    injected = list(messages)
    prefix = (
        "<!-- KNOWLEDGE INJECTION: 以下知识已自动匹配注入，不需自己搜索 -->\n"
        f"{knowledge_text}\n"
        "<!-- END KNOWLEDGE INJECTION -->"
    )

    for i, msg in enumerate(injected):
        if msg.get("role") == "system":
            injected[i] = {**msg, "content": f"{prefix}\n\n{msg['content']}"}
            return injected

    injected.insert(0, {"role": "system", "content": prefix})
    return injected


def _run_gate(user_msg: str) -> dict:
    """调用 gate.match() 判断任务类型。异常降级为空结果，不阻断请求。"""
    try:
        from gate import match
        return match(user_msg)
    except Exception:
        return {"tid": "—", "name": "Gate未加载",
                "skills": [], "first": None,
                "confidence": -1, "matched_keywords": [],
                "is_modify": False, "runners_up": []}


def _format_gate_hint(task_gate: dict) -> str:
    """格式化 gate 结果为 system message 注入前缀。"""
    if not task_gate or task_gate.get("confidence", 0) <= 0:
        return ""

    tid = task_gate["tid"]
    name = task_gate["name"]
    skills = " → ".join(task_gate["skills"]) if task_gate.get("skills") else "无"
    first = task_gate.get("first") or "无"
    confidence = task_gate.get("confidence", 0)

    lines = [
        f"<!-- GATE: 任务类型={tid}（{name}）-->",
        f"<!-- GATE: skill链={skills} | 第一动作=skill_view {first} | 置信度={confidence} -->",
    ]
    if task_gate.get("is_modify"):
        lines.append(
            "<!-- GATE: 检测到改代码意图 → "
            "改之前先列清单 + 跑 graphify affected -->"
        )
    runners = task_gate.get("runners_up", [])
    if runners:
        ru = ", ".join(f"{t}({k})" for t, k, _ in runners[:2])
        lines.append(f"<!-- GATE: 次选={ru} -->")

    return "\n".join(lines)


def _format_modify_constraint() -> str:
    """代码修改硬约束——is_modify 时强制插入 system message，不是建议。"""
    return (
        "⚠️ 代码修改约束（硬门——不过关不动手）\n"
        "\n"
        "检测到改代码意图。以下步骤必须严格按序执行，不得跳过：\n"
        "\n"
        "1. 列清单——列出所有需要改动的文件，说明每个文件的改动原因\n"
        "2. 跑影响分析——确认改动不会破坏其他模块\n"
        "3. 先确认再动手——列出清单后，等待用户确认再开始改\n"
        "\n"
        "违反以上任何一步，修改无效。"
    )


def _enforce_modify_constraint(messages: list[dict]) -> list[dict]:
    """将代码修改约束硬插入 system message 头部。"""
    constraint = _format_modify_constraint()
    result = list(messages)

    for i, msg in enumerate(result):
        if msg.get("role") == "system":
            result[i] = {**msg, "content": f"{constraint}\n\n{msg['content']}"}
            return result

    # 没有 system message，插入一条新的
    result.insert(0, {"role": "system", "content": constraint})
    return result


def _build_request(messages: list[dict], **kwargs) -> tuple[dict, dict]:
    """构建请求 headers 和 payload，stream 和非 stream 共用。"""
    key = _load_api_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": kwargs.get("model", DEEPSEEK_MODEL),
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.7),
        "max_tokens": kwargs.get("max_tokens", 8192),
        "stream": kwargs.get("stream", False),
    }
    return headers, payload


async def forward_to_deepseek(messages: list[dict], **kwargs) -> dict:
    """转发请求到 DeepSeek API（非 stream）。"""
    headers, payload = _build_request(messages, **kwargs)
    async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
        resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _forward_stream(messages: list[dict], **kwargs) -> any:
    """SSE 流式代理——逐块转发 DeepSeek 的 text/event-stream 响应。"""
    headers, payload = _build_request(messages, stream=True, **kwargs)
    async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
        async with client.stream("POST", DEEPSEEK_URL, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for chunk in resp.aiter_bytes():
                yield chunk


async def _stream_with_capture(messages: list[dict], body: dict,
                                user_msg: str, task_gate: dict):
    """Stream 响应 + 事后 Constitution 检查。

    每收到一个 chunk 立即 yield（不影响响应速度），同时收集完整文本。
    流结束后异步跑 Constitution 闸门，结果只写日志不拦截。
    """
    chunks: list[bytes] = []
    async for chunk in _forward_stream(
        messages,
        model=body.get("model", DEEPSEEK_MODEL),
        temperature=body.get("temperature", 0.7),
        max_tokens=body.get("max_tokens", 8192),
    ):
        chunks.append(chunk)
        yield chunk

    # 流结束 → fire-and-forget Constitution 检查
    import asyncio
    asyncio.create_task(_post_stream_check(chunks, user_msg, task_gate))


async def _post_stream_check(chunks: list[bytes], user_msg: str,
                              task_gate: dict):
    """事后 Constitution 检查——解析 SSE chunks，跑闸门，写日志。"""
    try:
        full_text = _extract_text_from_sse(chunks)
        if not full_text:
            return
        constitution_result = await _run_constitution_gate(full_text)
        _log_output(user_msg, full_text, constitution_result, task_gate)
    except Exception:
        pass  # 事后检查失败不连坐请求


def _extract_text_from_sse(chunks: list[bytes]) -> str:
    """从 SSE chunks 中提取 assistant 累积文本。"""
    import json as _json
    full = b"".join(chunks).decode("utf-8", errors="replace")
    text_parts: list[str] = []
    for line in full.split("\n"):
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        if data_str == "[DONE]":
            continue
        try:
            data = _json.loads(data_str)
            delta = data.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                text_parts.append(content)
        except Exception:
            continue
    return "".join(text_parts)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """主拦截端点 —— 兼容 OpenAI API 格式。

    管道：Gate判类型→路由→注入→转发→Constitution闸门（仅非stream）→返回
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)

    messages = body.get("messages", [])

    if not messages:
        return JSONResponse({"error": "no messages"}, status_code=400)

    # 防御：messages 必须为 list
    if not isinstance(messages, list):
        return JSONResponse({"error": "messages must be an array"}, status_code=400)

    stream = body.get("stream", False)

    # 提取最后一条 user 消息做路由
    user_msg = ""
    for m in reversed(messages):
        if not isinstance(m, dict):
            continue
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break

    # ── Gate: 任务类型前置判断 ──
    task_gate = _run_gate(user_msg)

    # ── 知识路由: gate tid 直接映射，不再跑关键词 ──
    tid = task_gate.get("tid", "—")
    if tid != "—" and task_gate.get("confidence", 0) > 0:
        files = _gate_tid_to_files(tid)
    else:
        files = DEFAULT_FILES  # gate 未识别时只加载索引
    knowledge = load_knowledge(files)
    # 拼接 gate 提示 + 知识上下文，一同注入 system message
    gate_hint = _format_gate_hint(task_gate)
    combined = f"{gate_hint}\n{knowledge}" if gate_hint else knowledge
    injected = inject_knowledge(messages, combined)

    # ── is_modify 硬约束 ——
    if task_gate.get("is_modify"):
        injected = _enforce_modify_constraint(injected)

    # 转发后端
    try:
        if stream:
            # SSE 流式——边传边捕获，流结束后异步跑 Constitution 检查
            return StreamingResponse(
                _stream_with_capture(injected, body, user_msg, task_gate),
                media_type="text/event-stream",
            )
        result = await forward_to_deepseek(
            injected,
            model=body.get("model", DEEPSEEK_MODEL),
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", 8192),
        )
    except Exception:
        # 不泄露后端异常细节给客户端
        return JSONResponse({"error": "backend request failed"}, status_code=502)

    # ── 输出闸门：Constitution Layer（stream 模式跳过语义检查）──
    if not stream:
        assistant_text = _extract_assistant_text(result)
        if assistant_text:
            gate_result = await _run_constitution_gate(assistant_text)
            if gate_result["blocked"]:
                warning = _format_gate_warning(gate_result)
                result = _prefix_assistant_text(result, warning)

            # 记录输出到日志（供 experience_engine 消费）
            _log_output(user_msg, assistant_text, gate_result, task_gate)

    return JSONResponse(result)


def _extract_assistant_text(result: dict) -> str:
    """从 OpenAI 格式响应中提取 assistant 文本。"""
    try:
        return result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return ""


def _prefix_assistant_text(result: dict, prefix: str) -> dict:
    """在 assistant 消息前插入前缀。"""
    try:
        msg = result["choices"][0]["message"]
        msg["content"] = prefix + "\n" + msg["content"]
    except (KeyError, IndexError, TypeError):
        pass
    return result


async def _run_constitution_gate(text: str) -> dict:
    """运行宪法闸门——正则 + 语义双层（异步，不阻塞 event loop）。"""
    import asyncio
    return await asyncio.to_thread(_run_constitution_gate_sync, text)


def _run_constitution_gate_sync(text: str) -> dict:
    """宪法闸门同步实现。sys.path 已在模块级初始化，不依赖 CWD。"""
    try:
        from constitution import Constitution  # type: ignore
        c = Constitution()
        return c.full_check(text, _load_api_key(), model=DEEPSEEK_MODEL)
    except Exception:
        # 宪法检查崩溃 → fail-open（不阻断正常对话）
        return {"blocked": False, "layer": "error", "violations": [],
                "semantic": {"verdict": "SKIP", "reason": "constitution check failed"}}


def _format_gate_warning(gate_result: dict) -> str:
    """格式化闸门警告前缀。"""
    layer = gate_result.get("layer", "?")
    if layer == "regex":
        count = len(gate_result.get("violations", []))
        return f"⚠️ [Constitution: {count}处正则违规]"
    elif layer == "semantic":
        sem = gate_result.get("semantic", {})
        return f"⚠️ [Constitution: 语义违规 {sem.get('rule_id','?')} — {sem.get('reason','')}]"
    return "⚠️ [Constitution: 违规]"


def _log_output(user_msg: str, assistant_text: str, constitution_result: dict,
                task_gate: dict | None = None):
    """写输出日志。异常静默跳过——日志崩了不应连坐请求。"""
    try:
        from datetime import datetime
        log_dir = os.path.join(HERMES_HOME, "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "BLOCKED" if constitution_result.get("blocked") else "PASS"
        layer = constitution_result.get("layer", "?")
        # gate 任务类型
        gate_type = task_gate.get("tid", "?") if task_gate else "?"
        gate_name = task_gate.get("name", "") if task_gate else ""
        gate_info = f" gate={gate_type}({gate_name})" if task_gate and task_gate.get("confidence", -1) > 0 else ""
        with open(os.path.join(log_dir, "output_gate.log"), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {status}:{layer}{gate_info} | "
                    f"user={user_msg[:100]} | ai={assistant_text[:200]}\n")
    except Exception:
        pass  # 日志写入失败不连坐请求


@app.get("/v1/models")
async def models():
    """透传模型列表（含 context_window）。"""
    try:
        key = _load_api_key()
        headers = {"Authorization": f"Bearer {key}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{DEEPSEEK_BASE}/models", headers=headers
            )
            data = resp.json()
            # 加 context_window
            for m in data.get("data", []):
                if "context_window" not in m:
                    m["context_window"] = 1048576
            return JSONResponse(data)
    except Exception:
        return JSONResponse({"data": []})


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    key = _load_api_key()
    host = os.environ.get("HERMES_ROUTER_HOST", "127.0.0.1")
    print(f"知识路由中间件启动 → http://{host}:8000")
    print(f"路由表 {len(KNOWLEDGE_ROUTING)} 个规则")
    print(f"后端 → {DEEPSEEK_URL}")
    print(f"模型 → {DEEPSEEK_MODEL}")
    # 安全警告：HTTP 明文传输 API key
    if DEEPSEEK_BASE.startswith("http://"):
        print("⚠️  警告: DEEPSEEK_BASE_URL 使用 HTTP，API key 将明文传输！")
    if not key:
        print("=" * 60)
        print("❌ DEEPSEEK_API_KEY 未找到！")
        print("")
        print("请用以下任一方式设置：")
        print("  1. 在当前目录创建 .env 文件，写入：")
        print("     DEEPSEEK_API_KEY=sk-你的key")
        print("  2. 设置环境变量：")
        print("     export DEEPSEEK_API_KEY=sk-你的key")
        print("  3. 在 ~/.hermes/.env 中写入同一行")
        print("=" * 60)
        exit(1)
    # 默认绑定 localhost——避免局域网内其他人用你的 API key
    # 如需局域网访问，设置环境变量 HERMES_ROUTER_HOST=0.0.0.0
    host = os.environ.get("HERMES_ROUTER_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=8000, log_level="info")
