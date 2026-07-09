"""
Dashboard HTTP 服务器 — 内嵌单页 HTML，无需外部依赖。

访问: http://localhost:18500
"""

from __future__ import annotations

import http.server
import json
import queue
import threading
import webbrowser
from urllib.parse import urlparse

from agentos.dashboard.tracker import Tracker

PORT = 18500

# SSE 事件队列（线程安全，用于实时推送）
_sse_queues: list[queue.Queue] = []
_sse_lock = threading.Lock()


def _sse_broadcast(event_type: str, data: dict):
    """广播事件到所有 SSE 连接。"""
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    with _sse_lock:
        dead = []
        for q in _sse_queues:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_queues.remove(q)


# ============================================================
# 内嵌前端（纯 HTML/CSS/JS，零外部依赖）
# ============================================================

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgentOS Dashboard — 追踪面板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
  background:#0d1117;color:#c9d1d9;min-height:100vh;
}
.header{
  background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;
  display:flex;align-items:center;justify-content:space-between;
}
.header h1{
  font-size:20px;font-weight:600;
  background:linear-gradient(90deg,#58a6ff,#bc8cff);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
}
.header .stats{font-size:13px;color:#8b949e}
.main{padding:20px 24px;max-width:1200px;margin:0 auto}
.sessions{display:flex;flex-direction:column;gap:12px}
.session-card{
  background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:16px 20px;cursor:pointer;transition:border-color .15s;
}
.session-card:hover{border-color:#58a6ff}
.session-card .top{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.session-card .task{font-size:15px;font-weight:600;color:#e6edf3}
.session-card .id{font-size:11px;color:#484f58;font-family:monospace}
.session-card .meta{font-size:12px;color:#8b949e;display:flex;gap:16px}
.session-card .status{
  display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;
}
.status-completed{background:#1a3a2a;color:#3fb950}
.status-running{background:#1a2a3a;color:#58a6ff}
.status-error{background:#3a1a1a;color:#f85149}
.status-cancelled{background:#3a3a1a;color:#d29922}

/* 详情面板 */
.detail-panel{
  background:#161b22;border:1px solid #30363d;border-radius:8px;margin-top:16px;
}
.detail-header{
  display:flex;justify-content:space-between;align-items:center;
  padding:12px 20px;border-bottom:1px solid #30363d;
}
.detail-header h3{font-size:16px;color:#e6edf3}
.detail-header button{
  background:none;border:1px solid #30363d;color:#8b949e;padding:4px 12px;
  border-radius:6px;cursor:pointer;font-size:12px;
}
.detail-header button:hover{color:#e6edf3;border-color:#58a6ff}

/* 时间线 */
.timeline{position:relative;padding:16px 20px}
.timeline::before{
  content:'';position:absolute;left:26px;top:30px;bottom:30px;
  width:2px;background:#30363d;
}
.step{
  position:relative;padding:8px 0 8px 48px;display:flex;gap:12px;
}
.step-dot{
  position:absolute;left:20px;top:14px;width:14px;height:14px;
  border-radius:50%;border:2px solid #30363d;background:#0d1117;z-index:1;
}
.step-dot.thinking{border-color:#58a6ff;background:#0d2847}
.step-dot.tool_call{border-color:#d29922;background:#2a2010}
.step-dot.tool_result{border-color:#3fb950;background:#102a18}
.step-dot.final_answer{border-color:#bc8cff;background:#281a3a}
.step-content{flex:1}
.step-type{
  font-size:11px;font-weight:600;text-transform:uppercase;margin-bottom:4px;
}
.step-type.thinking{color:#58a6ff}
.step-type.tool_call{color:#d29922}
.step-type.tool_result{color:#3fb950}
.step-type.final_answer{color:#bc8cff}
.step-detail{font-size:13px;color:#c9d1d9;word-break:break-word}
.step-meta{font-size:11px;color:#484f58;margin-top:4px}

/* 统计卡片 */
.stat-row{display:flex;gap:16px;margin-bottom:20px}
.stat-card{
  flex:1;background:#161b22;border:1px solid #30363d;border-radius:8px;
  padding:16px;text-align:center;
}
.stat-card .value{font-size:28px;font-weight:700;color:#e6edf3}
.stat-card .label{font-size:12px;color:#8b949e;margin-top:4px}
.stat-card .value.cost{color:#3fb950}
.stat-card .value.tokens{color:#58a6ff}

.empty{
  text-align:center;padding:60px 20px;color:#484f58;
}
.empty p{font-size:14px;margin-bottom:8px}
.empty code{
  background:#161b22;border:1px solid #30363d;border-radius:4px;
  padding:2px 8px;font-size:13px;
}
.refresh-btn{
  background:#21262d;border:1px solid #30363d;color:#c9d1d9;
  padding:6px 16px;border-radius:6px;cursor:pointer;font-size:12px;
  margin-left:8px;
}
.refresh-btn:hover{border-color:#58a6ff}
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>AgentOS Dashboard</h1>
    <div class="stats" id="stats-bar">正在加载...</div>
  </div>
  <button class="refresh-btn" onclick="loadSessions()">刷新</button>
</div>
<div class="main">
  <div class="stat-row" id="stat-cards"></div>
  <div class="sessions" id="session-list"></div>
  <div id="detail-area"></div>
</div>
<script>
const API = '/api';

async function loadSessions() {
  const resp = await fetch(API + '/sessions');
  const data = await resp.json();
  renderStats(data.sessions || []);
  renderSessions(data.sessions || []);
}

function renderStats(sessions) {
  const total = sessions.length;
  const completed = sessions.filter(s => s.status === 'completed').length;
  let totalTokens = 0, totalCost = 0;
  sessions.forEach(s => { totalTokens += s.total_tokens || 0; totalCost += s.total_cost_usd || 0; });
  document.getElementById('stats-bar').textContent =
    `${total} 次运行 · ${completed} 完成`;
  document.getElementById('stat-cards').innerHTML =
    `<div class="stat-card"><div class="value">${total}</div><div class="label">总运行次数</div></div>
     <div class="stat-card"><div class="value">${completed}</div><div class="label">成功完成</div></div>
}

function renderSessions(sessions) {
  const el = document.getElementById('session-list');
  if (!sessions.length) {
    el.innerHTML = `<div class="empty">
      <p>尚无运行记录</p>
      <p>运行 <code>agentos "你的任务"</code> 后会自动记录到这里</p>
    </div>`;
    return;
  }
  el.innerHTML = sessions.map(s => {
    const dur = s.finished_at ? ((s.finished_at - s.started_at) / 1000).toFixed(1) + 's' : '进行中';
    const ts = new Date(s.started_at * 1000).toLocaleString('zh-CN');
    const statusClass = 'status-' + (s.status || 'running');
    const statusLabel = {completed:'已完成',running:'运行中',error:'错误',cancelled:'已取消'}[s.status] || s.status;
    return `<div class="session-card" onclick="showDetail('${s.session_id}')">
      <div class="top">
        <span class="task">${esc(s.task)}</span>
        <span class="id">${s.session_id.slice(0,12)}</span>
      </div>
      <div class="meta">
        <span>${dur}</span>
        <span>${s.total_tokens || 0} tokens</span>
        <span>$${(s.total_cost_usd || 0).toFixed(4)}</span>
        <span>${ts}</span>
        <span>${s.model || s.provider || ''}</span>
        <span class="status ${statusClass}">${statusLabel}</span>
      </div>
    </div>`;
  }).join('');
}

async function showDetail(sid) {
  const resp = await fetch(API + '/sessions/' + sid);
  const s = await resp.json();
  if (!s) return;
  const dur = s.finished_at ? ((s.finished_at - s.started_at) / 1000).toFixed(1) + 's' : '进行中';
  const steps = s.steps || [];
  const timeline = steps.length ? steps.map(st => {
    const dotClass = st.step_type || '';
    return `<div class="step">
      <div class="step-dot ${dotClass}"></div>
      <div class="step-content">
        <div class="step-type ${dotClass}">${st.step_type}</div>
        <div class="step-detail">${esc(st.detail)}</div>
        <div class="step-meta">#${st.step_index} · ${(st.duration_ms||0).toFixed(0)}ms · ${st.tokens||0} tokens</div>
      </div>
    </div>`;
  }).join('') : '<div class="empty"><p>无步骤记录</p></div>';

  document.getElementById('detail-area').innerHTML = `
    <div class="detail-panel">
      <div class="detail-header">
        <h3>${esc(s.task)}</h3>
        <button onclick="document.getElementById('detail-area').innerHTML=''">关闭</button>
      </div>
      <div class="stat-row" style="padding:16px 20px 0">
        <div class="stat-card"><div class="value">${dur}</div><div class="label">耗时</div></div>
        <div class="stat-card"><div class="value tokens">${s.total_tokens||0}</div><div class="label">Tokens</div></div>
        <div class="stat-card"><div class="value">${steps.length}</div><div class="label">步骤数</div></div>
      </div>
      <div class="timeline">${timeline}</div>
    </div>`;
}

loadSessions();

// SSE 实时推送
var es = new EventSource('/api/events');
es.addEventListener('connected', function(e) { console.log('[dashboard] SSE connected'); });
es.addEventListener('message', function(e) {
  try {
    var msg = JSON.parse(e.data);
    if (msg.type === 'step' || msg.type === 'session_done') {
      loadSessions();
    }
  } catch (_) {}
});
es.onerror = function() { console.log('[dashboard] SSE disconnected, retrying...'); };
</script>
</body>
</html>"""

# ============================================================
# HTTP Handler
# ============================================================


class DashboardHandler(http.server.BaseHTTPRequestHandler):
    """Dashboard HTTP 请求处理器。"""

    def log_message(self, format, *args):
        pass  # 静默日志

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # 主页
        if path == "/":
            self._html(200, DASHBOARD_HTML)
            return

        # API: 列出所有会话
        if path == "/api/sessions":
            tracker = Tracker.get()
            sessions = tracker.list_sessions()
            self._json({"sessions": sessions})
            return

        # API: 单个会话详情
        if path.startswith("/api/sessions/"):
            sid = path.split("/api/sessions/")[-1]
            tracker = Tracker.get()
            session = tracker.get_session(sid)
            if session is None:
                self._json({"error": "not found"}, 404)
            else:
                self._json(session)
            return

        # API: SSE 实时事件流
        if path == "/api/events":
            self._handle_sse()
            return

        # API: 健康检查
        if path == "/api/health":
            tracker = Tracker.get()
            self._json(
                {
                    "status": "ok",
                    "active_sessions": len(tracker._active),
                    "sse_clients": len(_sse_queues),
                }
            )
            return

        self._html(404, "<h1>404</h1>")

    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status, content):
        body = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_sse(self):
        """SSE (Server-Sent Events) 实时推送。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: queue.Queue = queue.Queue(maxsize=256)
        with _sse_lock:
            _sse_queues.append(q)

        try:
            # 发送初始连接事件
            self.wfile.write(b"event: connected\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                try:
                    payload = q.get(timeout=30)  # 30s 心跳
                    self.wfile.write(f"data: {payload}\n\n".encode())
                    self.wfile.flush()
                except queue.Empty:
                    # 心跳保活
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _sse_lock:
                if q in _sse_queues:
                    _sse_queues.remove(q)


class DashboardServer:
    """Dashboard HTTP 服务器。"""

    def __init__(self, port: int = PORT):
        self.port = port
        self._server: http.server.HTTPServer | None = None

    def start(self, open_browser: bool = True):
        self._server = http.server.HTTPServer(("0.0.0.0", self.port), DashboardHandler)
        # 注册 Tracker → SSE 桥接
        Tracker.get().subscribe(_sse_broadcast)
        url = f"http://localhost:{self.port}"
        print(f"AgentOS Dashboard → {url}")
        if open_browser:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard stopped.")


def start_dashboard(port: int = PORT, open_browser: bool = True):
    """便捷启动函数。"""
    srv = DashboardServer(port=port)
    srv.start(open_browser=open_browser)
