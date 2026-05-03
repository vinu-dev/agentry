"""Small local configuration/status dashboard for Agentry."""

# ruff: noqa: E501

from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from agentry.config import load_target_config, target_logs_dir
from agentry.configure import apply_recommended_options, read_raw_config, summarize_config
from agentry.session import list_sessions, read_log_tail, stop_all_sessions, stop_session


def run_dashboard(target_path: Path, *, host: str = "127.0.0.1", port: int = 4783) -> None:
    target_path = target_path.resolve()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send_html(_HTML)
                return
            if parsed.path == "/api/status":
                self._send_json(build_status_payload(target_path))
                return
            if parsed.path == "/api/config":
                try:
                    self._send_json(summarize_config(read_raw_config(target_path)))
                except (FileNotFoundError, ValueError) as e:
                    self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/api/config":
                payload = self._read_json()
                try:
                    updated = apply_recommended_options(
                        target_path,
                        mode=str(payload.get("mode", "pipeline")),
                        enable_researcher=bool(payload.get("enable_researcher", False)),
                        enable_release=bool(payload.get("enable_release", False)),
                        model_profile=str(payload.get("model_profile", "balanced")),
                        auto_merge=bool(payload.get("auto_merge", False)),
                        stop_when_queue_empty=bool(payload.get("stop_when_queue_empty", False)),
                    )
                except (FileNotFoundError, ValueError) as e:
                    self._send_json({"error": str(e)}, status=HTTPStatus.BAD_REQUEST)
                    return
                self._send_json(summarize_config(updated))
                return
            if parsed.path == "/api/stop":
                payload = self._read_json()
                role = payload.get("role")
                if isinstance(role, str) and role:
                    self._send_json({"stopped": {role: stop_session(target_path, role)}})
                else:
                    self._send_json({"stopped": stop_all_sessions(target_path)})
                return
            self.send_error(HTTPStatus.NOT_FOUND, "not found")

        def log_message(self, fmt: str, *args) -> None:
            return

        def _read_json(self) -> dict:
            length = int(self.headers.get("content-length", "0") or "0")
            if length <= 0:
                return {}
            body = self.rfile.read(length)
            try:
                data = json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return data if isinstance(data, dict) else {}

        def _send_json(self, payload: object, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Agentry dashboard: http://{host}:{port}")
    print(f"Target: {target_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def build_status_payload(target_path: Path) -> dict:
    cfg = load_target_config(target_path)
    log_root = target_logs_dir(target_path)
    sessions = {record.get("role"): record for record in list_sessions(target_path)}
    roles = []
    for role, agent in cfg.agents.items():
        latest_log = _latest_log(log_root / role)
        roles.append(
            {
                "role": role,
                "enabled": agent.enabled,
                "mode_allowed": _mode_allows(cfg.mode, role, cfg.research.allow_create_issues),
                "cli": agent.cli,
                "args": agent.args,
                "token_budget": agent.token_budget,
                "session": sessions.get(role),
                "latest_log": str(latest_log) if latest_log else None,
                "latest_log_tail": read_log_tail(latest_log, max_lines=40) if latest_log else "",
            }
        )
    return {
        "target_repo": cfg.target_repo,
        "mode": cfg.mode,
        "automation": cfg.automation.model_dump(),
        "research": cfg.research.model_dump(),
        "roles": roles,
    }


def _latest_log(role_log_dir: Path) -> Path | None:
    if not role_log_dir.is_dir():
        return None
    logs = sorted(role_log_dir.glob("*.log"))
    return logs[-1] if logs else None


def _mode_allows(mode: str, role: str, research_allowed: bool) -> bool:
    if mode == "manual":
        return False
    if role == "researcher":
        return mode == "autonomous" and research_allowed
    return True


_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Agentry Dashboard</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg: #f7f8fa;
      --ink: #111827;
      --muted: #667085;
      --line: #d9dee7;
      --panel: #ffffff;
      --good: #166534;
      --warn: #a15c00;
      --bad: #b42318;
      --accent: #255e91;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    body { margin: 0; background: var(--bg); color: var(--ink); }
    header { padding: 18px 24px; border-bottom: 1px solid var(--line); background: var(--panel); }
    h1 { margin: 0; font-size: 20px; font-weight: 700; }
    main { padding: 20px 24px; max-width: 1180px; margin: 0 auto; }
    .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
    button, select, input { font: inherit; }
    button { border: 1px solid var(--line); background: var(--panel); color: var(--ink); padding: 8px 12px; border-radius: 6px; cursor: pointer; }
    button.primary { background: var(--accent); color: white; border-color: var(--accent); }
    button.danger { color: var(--bad); }
    .tab[aria-selected="true"] { background: var(--ink); color: var(--panel); }
    section { display: none; }
    section.active { display: block; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
    .panel { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
    .row { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0; border-bottom: 1px solid var(--line); }
    .row:last-child { border-bottom: 0; }
    label { display: block; font-size: 13px; color: var(--muted); margin: 10px 0 4px; }
    select, input[type="number"] { width: 100%; box-sizing: border-box; border: 1px solid var(--line); border-radius: 6px; padding: 8px; background: var(--panel); color: var(--ink); }
    .switch { display: flex; align-items: center; gap: 8px; margin: 12px 0; }
    .badge { border-radius: 999px; padding: 2px 8px; font-size: 12px; border: 1px solid var(--line); color: var(--muted); white-space: nowrap; }
    .good { color: var(--good); }
    .warn { color: var(--warn); }
    .bad { color: var(--bad); }
    pre { white-space: pre-wrap; overflow: auto; max-height: 260px; margin: 8px 0 0; padding: 10px; border: 1px solid var(--line); border-radius: 6px; background: color-mix(in srgb, var(--panel), var(--bg) 55%); }
  </style>
</head>
<body>
  <header><h1>Agentry Dashboard</h1></header>
  <main>
    <nav class="tabs">
      <button class="tab" data-tab="status" aria-selected="true">Status</button>
      <button class="tab" data-tab="configure" aria-selected="false">Configure</button>
    </nav>
    <section id="status" class="active">
      <div class="panel">
        <div class="row"><strong id="repo">Loading...</strong><span id="mode" class="badge"></span></div>
        <div class="row"><span>Refresh</span><button id="refresh">Refresh Now</button></div>
        <div class="row"><span>Stop sessions</span><button class="danger" id="stop-all">Stop All</button></div>
      </div>
      <div id="roles" class="grid" style="margin-top:12px"></div>
    </section>
    <section id="configure">
      <div class="panel">
        <label for="mode-select">Run mode</label>
        <select id="mode-select">
          <option value="pipeline">pipeline - process existing labels only</option>
          <option value="manual">manual - do not auto-run roles</option>
          <option value="autonomous">autonomous - allow research when enabled</option>
        </select>
        <label for="model-profile">Model profile</label>
        <select id="model-profile">
          <option value="balanced">balanced</option>
          <option value="cheap">cheap</option>
          <option value="strong">strong</option>
        </select>
        <label class="switch"><input id="enable-researcher" type="checkbox"> Enable Researcher</label>
        <label class="switch"><input id="enable-release" type="checkbox"> Enable Release Engineer</label>
        <label class="switch"><input id="auto-merge" type="checkbox"> Auto-merge agent-approved PRs</label>
        <label class="switch"><input id="stop-empty" type="checkbox"> Stop when queue is empty</label>
        <button class="primary" id="save">Save Configuration</button>
        <span id="save-status" class="badge"></span>
      </div>
    </section>
  </main>
  <script>
    const tabs = document.querySelectorAll('.tab');
    tabs.forEach(tab => tab.addEventListener('click', () => {
      tabs.forEach(t => t.setAttribute('aria-selected', 'false'));
      tab.setAttribute('aria-selected', 'true');
      document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
      document.getElementById(tab.dataset.tab).classList.add('active');
    }));

    async function loadConfig() {
      const cfg = await (await fetch('/api/config')).json();
      document.getElementById('mode-select').value = cfg.mode || 'pipeline';
      document.getElementById('enable-researcher').checked = !!cfg.roles?.researcher?.enabled;
      document.getElementById('enable-release').checked = !!cfg.roles?.release?.enabled;
      document.getElementById('auto-merge').checked = !!cfg.automation?.auto_merge;
      document.getElementById('stop-empty').checked = !!cfg.automation?.stop_when_queue_empty;
    }

    async function loadStatus() {
      const data = await (await fetch('/api/status')).json();
      document.getElementById('repo').textContent = data.target_repo;
      document.getElementById('mode').textContent = data.mode;
      const roles = document.getElementById('roles');
      roles.innerHTML = '';
      for (const role of data.roles) {
        const s = role.session || {};
        const state = s.state || 'no session';
        const cls = state === 'running' ? 'warn' : (state === 'completed' ? 'good' : (state === 'failed' || state === 'stopped' ? 'bad' : ''));
        const div = document.createElement('div');
        div.className = 'panel';
        div.innerHTML = `
          <div class="row"><strong>${role.role}</strong><span class="badge ${cls}">${state}</span></div>
          <div class="row"><span>Enabled</span><span>${role.enabled && role.mode_allowed}</span></div>
          <div class="row"><span>PID</span><span>${s.pid || ''}</span></div>
          <div class="row"><span>Tokens</span><span>${s.tokens_used || ''} / ${role.token_budget || ''}</span></div>
          <div class="row"><span>Started</span><span>${s.started_at || ''}</span></div>
          <button class="danger" data-stop="${role.role}">Stop</button>
          <pre>${escapeHtml(role.latest_log_tail || '')}</pre>`;
        roles.appendChild(div);
      }
      document.querySelectorAll('[data-stop]').forEach(btn => btn.addEventListener('click', async () => {
        await fetch('/api/stop', { method: 'POST', body: JSON.stringify({ role: btn.dataset.stop }) });
        await loadStatus();
      }));
    }

    function escapeHtml(s) {
      return s.replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    document.getElementById('refresh').addEventListener('click', loadStatus);
    document.getElementById('stop-all').addEventListener('click', async () => {
      await fetch('/api/stop', { method: 'POST', body: '{}' });
      await loadStatus();
    });
    document.getElementById('save').addEventListener('click', async () => {
      const payload = {
        mode: document.getElementById('mode-select').value,
        model_profile: document.getElementById('model-profile').value,
        enable_researcher: document.getElementById('enable-researcher').checked,
        enable_release: document.getElementById('enable-release').checked,
        auto_merge: document.getElementById('auto-merge').checked,
        stop_when_queue_empty: document.getElementById('stop-empty').checked,
      };
      await fetch('/api/config', { method: 'POST', body: JSON.stringify(payload) });
      document.getElementById('save-status').textContent = 'saved';
      await loadConfig();
      await loadStatus();
    });
    loadConfig();
    loadStatus();
    setInterval(loadStatus, 5000);
  </script>
</body>
</html>"""


__all__ = ["build_status_payload", "run_dashboard"]
