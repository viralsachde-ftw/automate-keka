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
        elif action == 'auth-auto':
            keka = KekaAttendance()
            try:
                # Generate verifier first, embed it in redirect_uri, then build auth_url
                # using that same verifier so the PKCE pair stays consistent.
                _, _, code_verifier, _ = keka.create_oauth_bootstrap('placeholder')
                auto_redirect_uri = self._callback_url_with_verifier(code_verifier)
                auth_url, _, _, _ = keka.create_oauth_bootstrap(auto_redirect_uri, code_verifier=code_verifier)

                base = f"{self._base_url()}/api/cron"
                html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Keka Auth Setup</title>
  <style>
    body{{font-family:sans-serif;max-width:640px;margin:60px auto;padding:0 20px;color:#333}}
    h2{{margin-bottom:4px}}
    .sub{{color:#666;margin-bottom:32px;font-size:14px}}
    .card{{border:1px solid #ddd;border-radius:10px;padding:24px;margin-bottom:20px}}
    button{{padding:12px 28px;font-size:15px;cursor:pointer;border:none;border-radius:6px;background:#0070f3;color:#fff;margin-right:10px}}
    button:disabled{{background:#aaa;cursor:default}}
    button.sec{{background:#f0f0f0;color:#333}}
    #status{{margin-top:20px;font-size:15px;font-weight:600;min-height:24px}}
    #fallback{{display:none;margin-top:20px}}
    textarea{{width:100%;box-sizing:border-box;padding:8px;font-size:13px;margin:8px 0;border:1px solid #ccc;border-radius:6px}}
    .dot{{display:inline-block;width:10px;height:10px;border-radius:50%;background:#ccc;margin-right:6px}}
    .dot.spin{{background:#0070f3;animation:pulse 1s infinite}}
    .dot.ok{{background:#1a7f37}} .dot.err{{background:#cf222e}}
    @keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
    code{{background:#f4f4f4;padding:2px 5px;border-radius:4px;font-size:12px}}
  </style>
</head>
<body>
  <h2>Keka Auth Setup</h2>
  <p class="sub">Automatic mode — just log in and this page handles the rest.</p>

  <div class="card">
    <strong>Step 1 — Log in</strong><br><br>
    <button id="loginBtn" onclick="openLogin()">&#x1F517; Open Keka Login</button>
    <button class="sec" onclick="checkNow()">Check Status</button>
    <div id="status"><span class="dot" id="dot"></span><span id="statusText">Click the button above to begin.</span></div>
  </div>

  <div id="fallback" class="card">
    <strong>Manual fallback</strong> — if the popup was blocked or login went to a different tab:<br>
    <small>Copy the full URL from your browser address bar after logging in (the one with <code>?code=...</code>) and paste it below.</small>
    <textarea id="redirectUrl" rows="2" placeholder="https://alchemy.keka.com/?code=..."></textarea>
    <button onclick="manualComplete()">Complete Setup</button>
    <div id="fallbackMsg" style="margin-top:8px;font-weight:600"></div>
  </div>

  <script>
    var CODE_VERIFIER = {repr(code_verifier)};
    var AUTH_URL = {repr(auth_url)};
    var BASE = {repr(base)};
    var AUTO_REDIRECT_URI = {repr(auto_redirect_uri)};
    var pollTimer = null;
    var popup = null;
    var done = false;

    function setStatus(text, state) {{
      document.getElementById('statusText').textContent = text;
      var d = document.getElementById('dot');
      d.className = 'dot' + (state === 'spin' ? ' spin' : state === 'ok' ? ' ok' : state === 'err' ? ' err' : '');
    }}

    function openLogin() {{
      popup = window.open(AUTH_URL, 'kekaLogin', 'width=520,height=680,left=200,top=100');
      setStatus('Waiting for login\u2026', 'spin');
      document.getElementById('loginBtn').disabled = true;
      // Show fallback after 5s in case popup was blocked
      setTimeout(function() {{
        if (!done) document.getElementById('fallback').style.display = 'block';
      }}, 5000);
      startPolling();
    }}

    function startPolling() {{
      if (pollTimer) return;
      pollTimer = setInterval(function() {{
        fetch(BASE + '?action=status')
          .then(function(r) {{ return r.text(); }})
          .then(function(t) {{
            if (t.indexOf('loaded=True') !== -1) {{
              clearInterval(pollTimer); pollTimer = null;
              done = true;
              setStatus('\u2705 Authentication complete! Tokens saved. Cron jobs will run automatically.', 'ok');
              document.getElementById('fallback').style.display = 'none';
              if (popup && !popup.closed) popup.close();
            }}
          }})
          .catch(function() {{}});
      }}, 2000);
    }}

    function checkNow() {{
      fetch(BASE + '?action=status')
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{ setStatus(t, t.indexOf('loaded=True') !== -1 ? 'ok' : ''); }})
        .catch(function(e) {{ setStatus('Error: ' + e, 'err'); }});
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

    function manualComplete() {{
      var raw = document.getElementById('redirectUrl').value;
      var msg = document.getElementById('fallbackMsg');
      var code = extractCode(raw);
      if (!code) {{ msg.textContent = '\u274C Could not find code in that URL.'; return; }}
      msg.textContent = 'Exchanging\u2026';
      var url = BASE + '?action=oauth-callback'
        + '&code=' + encodeURIComponent(code)
        + '&verifier=' + encodeURIComponent(CODE_VERIFIER)
        + '&redirect_uri=' + encodeURIComponent(AUTO_REDIRECT_URI);
      fetch(url)
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{
          if (t.toLowerCase().indexOf('complete') !== -1) {{
            msg.textContent = '\u2705 ' + t;
            setStatus('\u2705 Authentication complete! Cron jobs will run automatically.', 'ok');
            done = true;
            if (pollTimer) {{ clearInterval(pollTimer); pollTimer = null; }}
          }} else {{
            msg.textContent = '\u274C ' + t;
          }}
        }})
        .catch(function(e) {{ msg.textContent = 'Error: ' + e; }});
    }}
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
                b"Available actions: in, out, status, auth-auto, auth-auto-static, auth-start, auth-url, oauth-callback\n"
            )
            return

        status = "Success" if success else "Failed/Skipped"
        self.wfile.write(f"{message}: {status}".encode('utf-8'))
        return
