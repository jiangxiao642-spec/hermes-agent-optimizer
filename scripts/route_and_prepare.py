#!/usr/bin/env python3
"""知识路由中间件 — 在 Hermes Gateway 和后端 API 之间拦截请求，自动注入知识库上下文。

架构：Hermes Gateway → localhost:8000 → 本脚本 → 后端 API
对 Hermes 透明，不需要改核心代码。

启动：python3 route_and_prepare.py
"""

import json
import re
import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

HERMES_HOME = os.path.expanduser("~/.hermes")
KNOWLEDGE_DIR = os.path.join(HERMES_HOME, "knowledge")
DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_URL = f"{DEEPSEEK_BASE}/chat/completions"
DEEPSEEK_TIMEOUT = 300.0


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


DEEPSEEK_KEY = _get_api_key()

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


def route(user_message: str) -> list[str]:
    """从用户消息中匹配知识文件。关键词匹配。"""
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


async def forward_to_deepseek(messages: list[dict], **kwargs) -> dict:
    """转发请求到 DeepSeek API。"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": kwargs.get("model", "deepseek-v4-pro"),
        "messages": messages,
        "temperature": kwargs.get("temperature", 0.7),
        "max_tokens": kwargs.get("max_tokens", 8192),
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=DEEPSEEK_TIMEOUT) as client:
        resp = await client.post(DEEPSEEK_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """主拦截端点 —— 兼容 OpenAI API 格式。

    管道：路由→注入→转发→Constitution闸门→返回
    """
    body = await request.json()
    messages = body.get("messages", [])

    if not messages:
        return JSONResponse({"error": "no messages"}, status_code=400)

    # 提取最后一条 user 消息做路由
    user_msg = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break

    # 路由 → 加载 → 注入
    files = route(user_msg)
    knowledge = load_knowledge(files)
    injected = inject_knowledge(messages, knowledge)

    # 转发后端
    try:
        result = await forward_to_deepseek(
            injected,
            model=body.get("model", "deepseek-v4-pro"),
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", 8192),
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)

    # ── 输出闸门：Constitution Layer ──
    assistant_text = _extract_assistant_text(result)
    if assistant_text:
        gate_result = _run_constitution_gate(assistant_text)
        if gate_result["blocked"]:
            warning = _format_gate_warning(gate_result)
            result = _prefix_assistant_text(result, warning)

        # 记录输出到日志（供 experience_engine 消费）
        _log_output(user_msg, assistant_text, gate_result)

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


def _run_constitution_gate(text: str) -> dict:
    """运行宪法闸门——正则 + 语义双层。"""
    try:
        from scripts.constitution import Constitution
        c = Constitution()
        return c.full_check(text, DEEPSEEK_KEY)
    except Exception as e:
        return {"blocked": False, "layer": "error", "violations": [],
                "semantic": {"verdict": "SKIP", "reason": str(e)[:50]}}


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


def _log_output(user_msg: str, assistant_text: str, gate_result: dict):
    """写输出日志。"""
    from datetime import datetime
    log_dir = os.path.join(HERMES_HOME, "logs")
    os.makedirs(log_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status = "BLOCKED" if gate_result.get("blocked") else "PASS"
    layer = gate_result.get("layer", "?")
    with open(os.path.join(log_dir, "output_gate.log"), "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {status}:{layer} | user={user_msg[:100]} | ai={assistant_text[:200]}\n")


@app.get("/v1/models")
async def models():
    """透传模型列表（含 context_window）。"""
    try:
        headers = {"Authorization": f"Bearer {DEEPSEEK_KEY}"}
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
    return {"status": "ok", "routes": list(KNOWLEDGE_ROUTING.keys())}


if __name__ == "__main__":
    import uvicorn
    print("知识路由中间件启动 → http://0.0.0.0:8000")
    print(f"路由表 {len(KNOWLEDGE_ROUTING)} 个规则")
    print(f"后端 → {DEEPSEEK_URL}")
    if not DEEPSEEK_KEY:
        print("=" * 60)
        print("❌ DEEPSEEK_API_KEY 未找到！")
        print("")
        print("请用以下任一方式设置：")
        print("  1. 在当前目录创建 .env 文件，写入：")
        print("     DEEPSEEK_API_KEY=sk-你的key")
        print("  2. 设置 Windows 用户环境变量：")
        print("     setx DEEPSEEK_API_KEY sk-你的key")
        print("  3. 在 ~/.hermes/.env 中写入同一行")
        print("=" * 60)
        exit(1)
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
