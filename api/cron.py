from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, urljoin
import os
import sys
import time

# Add parent directory to path so we can import keka
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keka import KekaAttendance, run_clock_in, run_clock_out, run_token_refresh


def _html_result(ok, message):
    icon = "&#x2705;" if ok else "&#x274C;"
    color = "#1a7f37" if ok else "#cf222e"
    extra = "<p>You can close this tab.</p><script>setTimeout(function(){window.close();},3000);</script>" if ok else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Keka Auth</title>
<style>body{{font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:80vh;margin:0}}
.box{{text-align:center;padding:40px;border-radius:12px;border:2px solid {color};max-width:480px}}
h2{{color:{color}}} p{{color:#555}}</style></head>
<body><div class="box"><h2>{icon} {message}</h2>{extra}</div></body></html>"""

class handler(BaseHTTPRequestHandler):
    def _base_url(self):
        proto = self.headers.get('x-forwarded-proto', 'https')
        host = self.headers.get('host', '')
        return f"{proto}://{host}"

    def _callback_url(self):
        return f"{self._base_url()}/api/cron?action=oauth-callback"

    def _callback_url_with_verifier(self, verifier):
        """Embed verifier in redirect_uri so Keka redirects straight to our handler."""
        return f"{self._base_url()}/api/cron?action=oauth-callback&verifier={verifier}"

    def _oauth_redirect_uri(self, keka):
        """Use provider-safe redirect by default; dynamic callback only when explicitly enabled."""
        use_dynamic = os.environ.get('KEKA_USE_DYNAMIC_CALLBACK', '').lower() == 'true'
        configured = (keka.redirect_uri or '').strip()
        if use_dynamic:
            return self._callback_url()
        if configured:
            return configured
        return 'https://alchemy.keka.com'

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        action = query.get('action', [''])[0]
        
        success = False
        message = "No action specified"
        
        if action == 'in':
            success = run_clock_in()
            message = "Clock In Attempted"
        elif action == 'out':
            success = run_clock_out()
            message = "Clock Out Attempted"
        elif action == 'refresh':
            success = run_token_refresh()
            message = "Token Refresh Attempted"
        elif action == 'force-refresh':
            keka = KekaAttendance()
            if keka.load_tokens():
                success = keka.refresh_access_token()
                message = "Force Token Refresh"
            else:
                success = False
                message = "Force Token Refresh Failed — no tokens loaded"
        elif action == 'status':
            keka = KekaAttendance()
            if keka.load_tokens():
                now = int(time.time())
                expiry = int(keka.token_expiry) if keka.token_expiry else None
                seconds_left = (expiry - now) if expiry else None
                should_refresh = keka.should_refresh_token()
                status_msg = f"loaded=True expires_in_seconds={seconds_left} should_refresh={should_refresh}"
                success = True
            else:
                status_msg = "loaded=False hint=run_auth_auto_for_callback_or_set_env_tokens"
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(status_msg.encode('utf-8'))
            return
        elif action == 'auth-url':
            keka = KekaAttendance()
            try:
                auth_url, state, verifier, redirect_uri = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"open_url={auth_url}\nstate={state}\nredirect_uri={redirect_uri}".encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"Failed to create auth url: {e}".encode('utf-8'))
            return
        elif action == 'clear-tokens':
            keka = KekaAttendance()
            cleared = keka.clear_tokens()
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Tokens cleared from: {', '.join(cleared) if cleared else 'nothing to clear'}".encode('utf-8'))
            return
        elif action == 'auth-auto':
            keka = KekaAttendance()
            try:
                # Use the whitelisted redirect URI (alchemy.keka.com or KEKA_REDIRECT_URI).
                # Keka rejects our Vercel URL so we cannot use it as redirect_uri directly.
                # The verifier is kept in page JS; user pastes the redirect URL and we exchange.
                redirect_uri = self._oauth_redirect_uri(keka)
                auth_url, _, code_verifier, _ = keka.create_oauth_bootstrap(redirect_uri)
                auto_redirect_uri = redirect_uri  # used in manualComplete fetch

                base = f"{self._base_url()}/api/cron"
                html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Keka Auth Setup</title>
  <style>
    body{{font-family:sans-serif;max-width:640px;margin:50px auto;padding:0 20px;color:#333}}
    h2{{margin-bottom:4px}}
    .sub{{color:#666;margin-bottom:28px;font-size:14px}}
    .card{{border:1px solid #ddd;border-radius:10px;padding:22px;margin-bottom:16px}}
    .row{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}}
    button{{padding:11px 22px;font-size:14px;cursor:pointer;border:none;border-radius:6px;background:#0070f3;color:#fff}}
    button.sec{{background:#f0f0f0;color:#333}}
    button.danger{{background:#fff0f0;color:#cf222e;border:1px solid #fcc}}
    button.green{{background:#1a7f37;color:#fff}}
    button.orange{{background:#f57c00;color:#fff}}
    button:disabled{{opacity:.5;cursor:not-allowed}}
    #status{{margin-top:14px;font-size:15px;font-weight:600;min-height:22px}}
    textarea{{width:100%;box-sizing:border-box;padding:8px;font-size:13px;margin:10px 0 6px;border:1px solid #ccc;border-radius:6px}}
    .dot{{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ccc;margin-right:6px;vertical-align:middle}}
    .dot.spin{{background:#0070f3;animation:pulse 1s infinite}}
    .dot.ok{{background:#1a7f37}} .dot.err{{background:#cf222e}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
    code{{background:#f4f4f4;padding:2px 5px;border-radius:4px;font-size:12px}}
    small{{color:#888}}
  </style>
</head>
<body>
  <h2>Keka Auth Setup</h2>
  <p class="sub">Log in, copy the redirect URL, paste below — done.</p>

  <div class="card">
    <strong>Step 1 — Open login</strong> (do <em>not</em> refresh this page after clicking)
    <div class="row">
      <button onclick="openLogin()">&#x1F517; Open Keka Login</button>
      <button class="sec" onclick="checkNow()">Check Status</button>
      <button class="danger" onclick="clearTokens()">&#x1F5D1; Clear Tokens</button>
    </div>
    <div id="status"><span class="dot" id="dot"></span><span id="statusText">Ready.</span></div>
  </div>

  <div class="card">
    <strong>Manual Actions</strong><br>
    <small>Trigger clock-in, clock-out, or force a token refresh at any time.</small>
    <div class="row">
      <button class="green" id="btnIn" onclick="runAction('in', this)">&#x23F0; Clock In</button>
      <button class="orange" id="btnOut" onclick="runAction('out', this)">&#x23F1; Clock Out</button>
      <button class="sec" id="btnRefresh" onclick="runAction('force-refresh', this)">&#x1F504; Force Refresh Token</button>
    </div>
    <div id="actionMsg" style="margin-top:10px;font-weight:600;min-height:20px"></div>
  </div>

  <div class="card">
    <strong>Step 2 — Paste the redirect URL</strong><br>
    <small>After login your browser lands on <code>{redirect_uri}</code> — it may look blank or show an error, that is normal.<br>
    Copy the full URL from the address bar (it contains <code>?code=…</code>) and paste below.</small>
    <textarea id="redirectUrl" rows="2" placeholder="https://alchemy.keka.com/?code=...&state=..."></textarea>
    <button onclick="completeAuth()">Complete Setup</button>
    <div id="pasteMsg" style="margin-top:8px;font-weight:600"></div>
  </div>

  <script>
    var CODE_VERIFIER = {repr(code_verifier)};
    var AUTH_URL = {repr(auth_url)};
    var BASE = {repr(base)};
    var REDIRECT_URI = {repr(auto_redirect_uri)};
    var done = false;

    function setStatus(text, state) {{
      document.getElementById('statusText').textContent = text;
      var d = document.getElementById('dot');
      d.className = 'dot' + (state === 'spin' ? ' spin' : state === 'ok' ? ' ok' : state === 'err' ? ' err' : '');
    }}

    function openLogin() {{
      window.open(AUTH_URL, '_blank');
      setStatus('Waiting — log in, then paste the redirect URL below.', 'spin');
    }}

    function checkNow() {{
      fetch(BASE + '?action=status')
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{ setStatus(t, t.indexOf('loaded=True') !== -1 ? 'ok' : ''); }})
        .catch(function(e) {{ setStatus('Error: ' + e, 'err'); }});
    }}

    function clearTokens() {{
      if (!confirm('Clear stored tokens?')) return;
      fetch(BASE + '?action=clear-tokens')
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{ setStatus(t, ''); done = false; }})
        .catch(function(e) {{ setStatus('Error: ' + e, 'err'); }});
    }}

    function runAction(action, btn) {{
      var msg = document.getElementById('actionMsg');
      btn.disabled = true;
      msg.textContent = 'Running\u2026';
      fetch(BASE + '?action=' + action)
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{
          var ok = t.toLowerCase().indexOf('fail') === -1 && t.toLowerCase().indexOf('error') === -1;
          msg.style.color = ok ? '#1a7f37' : '#cf222e';
          msg.textContent = (ok ? '\u2705 ' : '\u274C ') + t;
          btn.disabled = false;
          if (action === 'force-refresh') checkNow();
        }})
        .catch(function(e) {{ msg.style.color = '#cf222e'; msg.textContent = 'Error: ' + e; btn.disabled = false; }});
    }}

    function extractCode(raw) {{
      var s = raw.trim().replace(/ /g, '%20');
      var tries = [s, 'https://' + s, 'https://x.x/?' + s.replace(/^[?&]/, '')];
      for (var i = 0; i < tries.length; i++) {{
        try {{
          var p = new URL(tries[i]);
          var c = p.searchParams.get('code') || p.searchParams.get('authorization_code');
          if (c) return c;
        }} catch(e) {{}}
      }}
      return null;
    }}

    function completeAuth() {{
      var raw = document.getElementById('redirectUrl').value;
      var msg = document.getElementById('pasteMsg');
      var code = extractCode(raw);
      if (!code) {{ msg.textContent = '\u274C Could not find code in that URL.'; return; }}
      msg.textContent = 'Exchanging\u2026';
      var url = BASE + '?action=oauth-callback'
        + '&code=' + encodeURIComponent(code)
        + '&verifier=' + encodeURIComponent(CODE_VERIFIER)
        + '&redirect_uri=' + encodeURIComponent(REDIRECT_URI);
      fetch(url)
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{
          if (t.toLowerCase().indexOf('complete') !== -1) {{
            msg.textContent = '\u2705 ' + t;
            setStatus('\u2705 Authentication complete! Cron jobs will run automatically.', 'ok');
            done = true;
          }} else {{
            msg.textContent = '\u274C ' + t;
          }}
        }})
        .catch(function(e) {{ msg.textContent = 'Error: ' + e; }});
    }}

    // Auto-check status on load
    checkNow();
  </script>
</body>
</html>"""
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"Failed to start automated oauth: {e}".encode('utf-8'))
            return
        elif action == 'auth-auto-static':
            keka = KekaAttendance()
            try:
                auth_url, _, _v, _r = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
                self.send_response(302)
                self.send_header('Location', auth_url)
                self.end_headers()
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"Failed to start static oauth: {e}".encode('utf-8'))
            return
        elif action == 'auth-start':
            keka = KekaAttendance()
            try:
                redirect_uri = self._oauth_redirect_uri(keka)
                auth_url, state, _v, _r = keka.create_oauth_bootstrap(redirect_uri)
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                msg = (
                    "OAuth start ready.\n"
                    f"redirect_uri={redirect_uri}\n"
                    f"state={state}\n"
                    "Open the URL below to continue login (copy/paste in browser):\n"
                    f"{auth_url}\n\n"
                    "If provider shows an error page, your redirect_uri is not whitelisted.\n"
                    "Then use local setup: python keka.py setup (with KV_URL) and skip web flow."
                )
                self.wfile.write(msg.encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"Failed to start oauth: {e}".encode('utf-8'))
            return
        elif action == 'oauth-callback':
            # Detect if this is a direct browser visit (Keka auto-redirect) vs a fetch() call
            accept = self.headers.get('Accept', '')
            is_browser = 'text/html' in accept

            if 'error' in query:
                err = query.get('error', ['unknown_error'])[0]
                desc = query.get('error_description', [''])[0]
                self.send_response(400)
                if is_browser:
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(_html_result(False, f"OAuth rejected: {err} — {desc}").encode('utf-8'))
                else:
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(f"OAuth rejected by provider: {err} {desc}".encode('utf-8'))
                return

            code = query.get('code', [''])[0] or query.get('authorization_code', [''])[0]
            verifier = query.get('verifier', [''])[0]
            redirect_uri = query.get('redirect_uri', [''])[0] or None
            if not code or not verifier:
                self.send_response(400)
                if is_browser:
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(_html_result(False, "Missing code or verifier. Try auth-auto again.").encode('utf-8'))
                else:
                    self.send_header('Content-type', 'text/plain')
                    self.end_headers()
                    self.wfile.write(b"Missing code or verifier parameter.")
                return

            # Reconstruct the redirect_uri that was registered with Keka.
            # When verifier is embedded in the redirect_uri, Keka echoes the base URI back;
            # we rebuild it so the token exchange matches exactly what was sent.
            if not redirect_uri and verifier:
                redirect_uri = self._callback_url_with_verifier(verifier)

            keka = KekaAttendance()
            result = keka.exchange_callback_code(code, verifier, redirect_uri=redirect_uri)
            ok = result is True
            self.send_response(200 if ok else 500)
            if is_browser:
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                msg = "Authentication complete! Tokens saved. You can close this tab." if ok else f"Authentication failed: {result}"
                self.wfile.write(_html_result(ok, msg).encode('utf-8'))
            else:
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                msg = "OAuth setup complete" if ok else f"OAuth setup failed: {result}"
                self.wfile.write(msg.encode('utf-8'))
            return
        
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()

        if not action:
            self.wfile.write(
                b"Available actions: in, out, refresh, force-refresh, status, auth-auto, auth-auto-static, auth-start, auth-url, oauth-callback\n"
            )
            return

        status = "Success" if success else "Failed/Skipped"
        self.wfile.write(f"{message}: {status}".encode('utf-8'))
        return
