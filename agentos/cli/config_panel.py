"""
AgentOS 配置面板 — Web GUI，一键浏览器配置 API Key。

启动: agentos config-panel
访问: http://localhost:18480
"""

from __future__ import annotations

import http.server
import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse, parse_qs


CONFIG_DIR = Path.home() / ".agentos"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                 "Microsoft YaHei", "Helvetica Neue", sans-serif;
    background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
    min-height: 100vh; color: #e0e0e0; padding: 24px;
}
.container { max-width: 720px; margin: 0 auto; }
.header {
    text-align: center; padding: 40px 0 32px;
}
.header h1 {
    font-size: 28px; font-weight: 700;
    background: linear-gradient(90deg, #667eea, #764ba2);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.header p { color: #a0a0b8; margin-top: 8px; font-size: 14px; }
.card {
    background: rgba(255,255,255,0.06);
    backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 16px; padding: 28px; margin-bottom: 20px;
    transition: border-color 0.2s;
}
.card:hover { border-color: rgba(102,126,234,0.4); }
.card h3 {
    font-size: 17px; font-weight: 600; margin-bottom: 6px;
    display: flex; align-items: center; gap: 10px;
}
.card h3 .badge {
    font-size: 11px; font-weight: 500; padding: 2px 8px; border-radius: 10px;
}
.badge-recommend { background: #667eea22; color: #667eea; }
.badge cheap { background: #4caf5022; color: #4caf50; }
.badge strong { background: #ff980022; color: #ff9800; }
.card .desc { color: #9090a8; font-size: 13px; margin-bottom: 14px; line-height: 1.6; }
.card .info-row {
    display: flex; gap: 20px; margin-bottom: 14px; flex-wrap: wrap;
}
.card .info-item {
    font-size: 12px; color: #808098;
}
.card .info-item strong { color: #c0c0d0; font-weight: 600; }
.input-row { display: flex; gap: 10px; }
.input-row input {
    flex: 1; padding: 10px 14px;
    background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; color: #e0e0e0; font-size: 14px;
    outline: none; transition: border-color 0.2s;
}
.input-row input:focus { border-color: #667eea; }
.input-row input::placeholder { color: #555; }
.btn {
    padding: 10px 20px; border-radius: 10px; border: none;
    font-size: 14px; font-weight: 600; cursor: pointer;
    transition: all 0.2s;
}
.btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; }
.btn-primary:hover { filter: brightness(1.1); transform: translateY(-1px); }
.btn-outline {
    background: transparent; border: 1px solid rgba(255,255,255,0.15);
    color: #c0c0d8;
}
.btn-outline:hover { background: rgba(255,255,255,0.06); }
.btn-success { background: #4caf50; color: #fff; }
.status { font-size: 12px; margin-top: 8px; height: 20px; }
.status-ok { color: #4caf50; }
.status-err { color: #f44336; }
.status-checking { color: #ff9800; }
.status-bar {
    text-align: center; margin-top: 24px; padding: 16px;
    background: rgba(76,175,80,0.10); border-radius: 12px;
    font-size: 14px; color: #81c784;
}
.status-bar.warning {
    background: rgba(255,152,0,0.10); color: #ffb74d;
}
.footer { text-align: center; padding: 24px; color: #606078; font-size: 12px; }
"""

HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AgentOS 配置面板</title>
<style>{css}</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🔧 AgentOS 配置面板</h1>
    <p>选择一个 AI 服务商，填入 API Key，30 秒完成配置</p>
  </div>

  <!-- OpenAI -->
  <div class="card" id="card-openai">
    <h3>
      <span>🔵 OpenAI</span>
      <span class="badge badge-recommend">推荐</span>
    </h3>
    <div class="desc">
      最成熟的 AI 服务商，提供 GPT-4o、GPT-4o-mini 等模型。
      适合日常对话、代码生成、文档处理，中英文均出色。响应快、稳定性高。
    </div>
    <div class="info-row">
      <div class="info-item">默认模型: <strong>gpt-4o-mini</strong></div>
      <div class="info-item">费用: <strong>低 ~ 中（约 $0.15/百万token）</strong></div>
      <div class="info-item">注册: <a href="https://platform.openai.com/api-keys" target="_blank" style="color:#667eea">platform.openai.com</a></div>
    </div>
    <div class="input-row">
      <input type="password" id="key-openai" placeholder="粘贴你的 OpenAI API Key（以 sk- 开头）">
      <button class="btn btn-primary" onclick="save('openai')">保存并验证</button>
      <button class="btn btn-outline" onclick="verify('openai')">仅验证</button>
    </div>
    <div class="status" id="status-openai"></div>
  </div>

  <!-- DeepSeek -->
  <div class="card" id="card-deepseek">
    <h3>
      <span>🟢 DeepSeek</span>
      <span class="badge cheap">最实惠</span>
    </h3>
    <div class="desc">
      国产高性价比 AI 服务商，deepseek-chat 模型在中文理解和代码生成方面表现突出。
      价格极低（约为 OpenAI 的 1/10），适合高频调用和预算敏感的场景。
    </div>
    <div class="info-row">
      <div class="info-item">默认模型: <strong>deepseek-chat</strong></div>
      <div class="info-item">费用: <strong>极低（约 ¥1/百万token）</strong></div>
      <div class="info-item">注册: <a href="https://platform.deepseek.com/api_keys" target="_blank" style="color:#667eea">platform.deepseek.com</a></div>
    </div>
    <div class="input-row">
      <input type="password" id="key-deepseek" placeholder="粘贴你的 DeepSeek API Key（以 sk- 开头）">
      <button class="btn btn-primary" onclick="save('deepseek')">保存并验证</button>
      <button class="btn btn-outline" onclick="verify('deepseek')">仅验证</button>
    </div>
    <div class="status" id="status-deepseek"></div>
  </div>

  <!-- Anthropic -->
  <div class="card" id="card-anthropic">
    <h3>
      <span>🟣 Anthropic (Claude)</span>
      <span class="badge strong">最强推理</span>
    </h3>
    <div class="desc">
      Claude 系列擅长深度推理、长篇分析和安全对齐，创意写作和复杂逻辑任务表现顶级。
      适合需要深度思考的场景，如研究分析、合规审查、长文生成。
    </div>
    <div class="info-row">
      <div class="info-item">默认模型: <strong>claude-sonnet-4</strong></div>
      <div class="info-item">费用: <strong>中 ~ 高（约 $3/百万token）</strong></div>
      <div class="info-item">注册: <a href="https://console.anthropic.com/keys" target="_blank" style="color:#667eea">console.anthropic.com</a></div>
    </div>
    <div class="input-row">
      <input type="password" id="key-anthropic" placeholder="粘贴你的 Anthropic API Key（以 sk-ant- 开头）">
      <button class="btn btn-primary" onclick="save('anthropic')">保存并验证</button>
      <button class="btn btn-outline" onclick="verify('anthropic')">仅验证</button>
    </div>
    <div class="status" id="status-anthropic"></div>
  </div>

  <!-- 整体状态 -->
  <div id="global-status" class="status-bar">
    未配置任何服务商。选择一个并填入 API Key 开始使用。
  </div>

  <div class="footer">
    <p>API Key 安全保存在本地 <code>~/.agentos/</code> 目录中，不会上传到任何服务器。</p>
    <p>配置完成后可在终端运行 <code>agentos "你的任务"</code> 开始使用。</p>
  </div>
</div>

<script>
// 页面加载时检查当前配置
async function checkStatus() {{
    const resp = await fetch('/api/status');
    const data = await resp.json();
    for (const p of ['openai', 'deepseek', 'anthropic']) {{
        if (data[p] && data[p].configured) {{
            setStatus(p, 'ok', '已配置 ✅');
            document.getElementById('key-' + p).value = data[p].preview || '';
        }}
    }}
    updateGlobalStatus(data);
}}

async function save(provider) {{
    const key = document.getElementById('key-' + provider).value.trim();
    if (!key) {{ setStatus(provider, 'err', '请输入 API Key'); return; }}
    setStatus(provider, 'checking', '正在验证...');
    const resp = await fetch('/api/save', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{provider, key}})
    }});
    const data = await resp.json();
    if (data.ok) {{
        setStatus(provider, 'ok', '配置成功 ✅  — ' + (data.model || ''));
    }} else {{
        setStatus(provider, 'err', '失败: ' + (data.error || '未知错误'));
    }}
    updateGlobalStatus(data);
}}

async function verify(provider) {{
    const key = document.getElementById('key-' + provider).value.trim();
    if (!key) {{ setStatus(provider, 'err', '请先输入 API Key'); return; }}
    setStatus(provider, 'checking', '正在验证...');
    const resp = await fetch('/api/verify', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{provider, key}})
    }});
    const data = await resp.json();
    if (data.valid) {{
        setStatus(provider, 'ok', 'Key 有效 ✅');
    }} else {{
        setStatus(provider, 'err', 'Key 无效: ' + (data.error || ''));
    }}
}}

function setStatus(provider, cls, msg) {{
    const el = document.getElementById('status-' + provider);
    el.className = 'status status-' + cls;
    el.textContent = msg;
}}

async function updateGlobalStatus(data) {{
    const el = document.getElementById('global-status');
    const configured = [];
    if (data.openai && data.openai.configured) configured.push('OpenAI');
    if (data.deepseek && data.deepseek.configured) configured.push('DeepSeek');
    if (data.anthropic && data.anthropic.configured) configured.push('Anthropic');

    if (configured.length > 0) {{
        el.className = 'status-bar';
        el.innerHTML = '✅ 已配置: ' + configured.join('、') +
            ' 。在终端运行 <code>agentos "你的任务"</code> 开始使用。';
    }} else {{
        el.className = 'status-bar warning';
        el.textContent = '未配置任何服务商。选择一个并填入 API Key 完成配置。';
    }}
}}

checkStatus();
</script>
</body>
</html>
"""

API_TEMPLATE = {
    "openai": {
        "env_var": "OPENAI_API_KEY",
        "label": "OpenAI",
        "default_model": "gpt-4o-mini",
        "website": "https://platform.openai.com/api-keys",
        "key_prefix": "sk-",
    },
    "deepseek": {
        "env_var": "DEEPSEEK_API_KEY",
        "label": "DeepSeek",
        "default_model": "deepseek-chat",
        "website": "https://platform.deepseek.com/api_keys",
        "key_prefix": "sk-",
    },
    "anthropic": {
        "env_var": "ANTHROPIC_API_KEY",
        "label": "Anthropic",
        "default_model": "claude-sonnet-4",
        "website": "https://console.anthropic.com/keys",
        "key_prefix": "sk-ant-",
    },
}


def _get_status_dict() -> dict:
    """获取所有 Provider 的配置状态。"""
    status = {}
    for name, info in API_TEMPLATE.items():
        key = os.environ.get(info["env_var"], "")
        if not key and ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                if line.startswith(info["env_var"] + "="):
                    val = line.split("=", 1)[1].strip()
                    if val and val != "sk-xxx":
                        key = val
                    break
        preview = ""
        if key:
            preview = key[:8] + "..." + key[-4:] if len(key) > 20 else key
        status[name] = {
            "configured": bool(key),
            "preview": preview,
        }
    return status


def _test_connection(provider: str, api_key: str) -> tuple[bool, str]:
    """测试 API 连接。"""
    try:
        import httpx
        if provider == "openai":
            resp = httpx.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                return True, ""
            elif resp.status_code == 401:
                return False, "API Key 无效（401 未授权）"
            elif resp.status_code == 429:
                return False, "请求过于频繁，请稍后重试"
            else:
                return False, f"返回状态码 {resp.status_code}，请检查 Key 是否有对应权限"
        elif provider == "deepseek":
            resp = httpx.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return True, ""
            elif resp.status_code == 401:
                return False, "API Key 无效（401 未授权）"
            elif resp.status_code == 402:
                return False, "账户余额不足，请充值"
            else:
                return False, f"返回状态码 {resp.status_code}，请检查"
        elif provider == "anthropic":
            resp = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "hi"}],
                },
                timeout=10,
            )
            if resp.status_code == 200:
                return True, ""
            elif resp.status_code == 401:
                return False, "API Key 无效（401 未授权）"
            else:
                return False, f"返回状态码 {resp.status_code}，请检查"
    except Exception as e:
        return False, f"网络连接失败: {str(e)}"


def _save_config(provider: str, api_key: str):
    """保存配置到 ~/.agentos/。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    info = API_TEMPLATE[provider]

    # Update .env
    env_lines = []
    if ENV_FILE.exists():
        env_lines = ENV_FILE.read_text().splitlines()
    found = False
    new_env = []
    for line in env_lines:
        if line.startswith(info["env_var"] + "="):
            new_env.append(f"{info['env_var']}={api_key}")
            found = True
        else:
            new_env.append(line)
    if not found:
        new_env.append(f"{info['env_var']}={api_key}")
    ENV_FILE.write_text("\n".join(new_env) + "\n")

    # Update config.yaml
    config = {"version": "1.4.1", "active_provider": provider}
    import yaml
    if CONFIG_FILE.exists():
        existing = yaml.safe_load(CONFIG_FILE.read_text())
        if existing and "providers" in existing:
            config["providers"] = existing["providers"]
    if "providers" not in config:
        config["providers"] = {}
    config["providers"][provider] = {"env_var": info["env_var"]}
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    # Set env var for current process
    os.environ[info["env_var"]] = api_key


class PanelHandler(http.server.BaseHTTPRequestHandler):
    """HTTP 请求处理。"""

    def log_message(self, format, *args):
        pass  # 静默

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            html = HTML.format(css=CSS)
            self._send_html(html)
        elif self.path == "/api/status":
            status = _get_status_dict()
            self._send_json(status)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/save":
            body = self._read_body()
            provider = body.get("provider", "")
            key = body.get("key", "")
            if provider not in API_TEMPLATE:
                self._send_json({"ok": False, "error": "未知服务商"})
                return
            ok, err = _test_connection(provider, key)
            if ok:
                _save_config(provider, key)
                info = API_TEMPLATE[provider]
                self._send_json({
                    "ok": True,
                    "model": info["default_model"],
                })
            else:
                self._send_json({"ok": False, "error": err})
        elif self.path == "/api/verify":
            body = self._read_body()
            provider = body.get("provider", "")
            key = body.get("key", "")
            if provider not in API_TEMPLATE:
                self._send_json({"valid": False, "error": "未知服务商"})
                return
            ok, err = _test_connection(provider, key)
            self._send_json({"valid": ok, "error": err})
        else:
            self.send_error(404)

    def _send_html(self, html: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _send_json(self, data: dict):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else "{}"
        return json.loads(raw)


def start_panel(port: int = 18480, open_browser: bool = True):
    """启动配置面板 HTTP 服务。"""
    server = http.server.HTTPServer(("127.0.0.1", port), PanelHandler)
    url = f"http://127.0.0.1:{port}"

    print(f"""
  ╔══════════════════════════════════════════════╗
  ║     AgentOS 配置面板已启动               ║
  ╠══════════════════════════════════════════════╣
  ║                                              ║
  ║  访问地址: {url}                  ║
  ║                                              ║
  ║  按 Ctrl+C 停止服务                          ║
  ╚══════════════════════════════════════════════╝
""")

    if open_browser:
        try:
            webbrowser.open(url)
            print("  已自动打开浏览器。如未打开，请手动访问上方地址。\n")
        except Exception:
            print("  请手动在浏览器中打开上方地址。\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  配置面板已关闭。\n")
        server.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18480
    start_panel(port)
