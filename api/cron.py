from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import os
import sys
import time

# Add parent directory to path so we can import keka
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from keka import KekaAttendance, run_clock_in, run_clock_out, run_token_refresh

class handler(BaseHTTPRequestHandler):
    def _callback_url(self):
        proto = self.headers.get('x-forwarded-proto', 'https')
        host = self.headers.get('host', '')
        return f"{proto}://{host}/api/cron?action=oauth-callback"

    def _oauth_redirect_uri(self, keka):
        """Use provider-safe redirect by default; dynamic callback only when explicitly enabled."""
        use_dynamic = os.environ.get('KEKA_USE_DYNAMIC_CALLBACK', '').lower() == 'true'
        configured = (keka.redirect_uri or '').strip()

        if use_dynamic:
            return self._callback_url()

        # Default behavior: trust configured redirect URI to avoid provider whitelist errors.
        if configured:
            return configured

        # Final fallback
        return 'https://alchemy.keka.com'

    def _auth_auto_redirect_uri(self, keka):
        """auth-auto should try to complete setup, so prefer callback URL unless explicitly overridden."""
        if os.environ.get('KEKA_AUTH_AUTO_USE_STATIC', '').lower() == 'true':
            return self._oauth_redirect_uri(keka)
        return self._callback_url()

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
                auth_url, state = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                redirect_uri = self._oauth_redirect_uri(keka)
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
                # Use the whitelisted static redirect URI so Keka doesn't reject the request.
                # After login, Keka redirects to that URI with code+state; the user pastes
                # that URL back into the form below and JS calls our oauth-callback handler.
                redirect_uri = self._oauth_redirect_uri(keka)
                auth_url, _ = keka.create_oauth_bootstrap(redirect_uri)
                proto = self.headers.get('x-forwarded-proto', 'https')
                host = self.headers.get('host', '')
                callback_base = f"{proto}://{host}/api/cron" if host else '/api/cron'
                html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Keka Auth Setup</title>
  <style>
    body{{font-family:sans-serif;max-width:700px;margin:40px auto;padding:0 16px}}
    input,textarea{{width:100%;box-sizing:border-box;padding:8px;font-size:14px;margin:8px 0}}
    button{{padding:10px 20px;font-size:14px;cursor:pointer;margin-right:8px}}
    #msg{{margin-top:12px;font-weight:bold;white-space:pre-wrap}}
    .step{{margin:18px 0}}
    code{{background:#f4f4f4;padding:2px 5px;border-radius:3px;font-size:13px}}
    .tip{{color:#666;font-size:13px;margin-top:4px}}
  </style>
</head>
<body>
  <h2>Keka Authentication Setup</h2>
  <div class="step">
    <strong>Step 1:</strong>
    <a href="{auth_url}" target="_blank" rel="noopener">&#x1F517; Open Keka Login</a>
    &nbsp;(opens in a new tab — do <em>not</em> close this page)
  </div>
  <div class="step">
    <strong>Step 2:</strong> Log in with your Keka credentials.<br>
    After login, your browser will redirect to <code>{redirect_uri}</code>.<br>
    The page will look blank or show an error — that is normal.<br>
    <strong>Copy the entire URL from your browser address bar.</strong>
    <div class="tip">Example: <code>https://alchemy.keka.com/?code=ABC123&amp;state=XYZ&amp;...</code></div>
  </div>
  <div class="step">
    <strong>Step 3:</strong> Paste the URL below and click <em>Complete Setup</em>.<br>
    <div class="tip">Do this within ~60 seconds of being redirected — the code expires quickly.</div>
    <textarea id="redirectUrl" rows="3" placeholder="Paste the full redirect URL here&#10;e.g. https://alchemy.keka.com/?code=4D8C...&state=eGc1..."></textarea>
    <button onclick="completeAuth()">Complete Setup</button>
    <button onclick="checkStatus()">Check Status</button>
  </div>
  <div id="msg"></div>
  <script>
    function extractParams(raw) {{
      // Try various formats: full URL, URL without scheme, raw query string
      var attempts = [raw, 'https://' + raw, 'https://x.x/?' + raw.replace(/^[?&]/, '')];
      for (var i = 0; i < attempts.length; i++) {{
        try {{
          var p = new URL(attempts[i]);
          var code = p.searchParams.get('code') || p.searchParams.get('authorization_code');
          var state = p.searchParams.get('state');
          if (code && state) return {{code: code, state: state}};
        }} catch(e) {{}}
      }}
      return null;
    }}
    function completeAuth() {{
      var raw = document.getElementById('redirectUrl').value.trim();
      var msg = document.getElementById('msg');
      if (!raw) {{ msg.textContent = 'Please paste the redirect URL first.'; return; }}
      var params = extractParams(raw);
      if (!params) {{
        msg.textContent = 'Could not find code and state in what you pasted.\\nMake sure you copied the full URL from the browser address bar after logging in to Keka.\\nIt should look like: https://alchemy.keka.com/?code=...&state=...';
        return;
      }}
      msg.textContent = 'Exchanging code for tokens...';
      fetch('{callback_base}?action=oauth-callback&code=' + encodeURIComponent(params.code) + '&state=' + encodeURIComponent(params.state))
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{
          if (t.toLowerCase().indexOf('complete') !== -1) {{
            msg.textContent = '\\u2705 ' + t + '\\nTokens saved. Click Check Status to verify, then cron jobs will work automatically.';
          }} else {{
            msg.textContent = '\\u274C ' + t + '\\nThe code may have expired (>60s). Go back to Step 1 and try again immediately after login.';
          }}
        }})
        .catch(function(err) {{ msg.textContent = 'Request failed: ' + err; }});
    }}
    function checkStatus() {{
      var msg = document.getElementById('msg');
      msg.textContent = 'Checking...';
      fetch('{callback_base}?action=status')
        .then(function(r) {{ return r.text(); }})
        .then(function(t) {{ msg.textContent = t; }})
        .catch(function(err) {{ msg.textContent = 'Error: ' + err; }});
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
                # Static/provider-safe redirect (may login but not callback into this app)
                auth_url, _ = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
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
                auth_url, state = keka.create_oauth_bootstrap(redirect_uri)
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
            if 'error' in query:
                err = query.get('error', ['unknown_error'])[0]
                desc = query.get('error_description', [''])[0]
                self.send_response(400)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(f"OAuth rejected by provider: {err} {desc}".encode('utf-8'))
                return

            code = query.get('code', [''])[0] or query.get('authorization_code', [''])[0]
            state = query.get('state', [''])[0]
            if not code or not state:
                self.send_response(400)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                msg = (
                    "Missing code/state. Possible redirect_uri mismatch or direct callback hit. \
If you see 'An error occured while processing your request', your redirect URI is likely not whitelisted for this client. \
Use /api/cron?action=auth-url and confirm KEKA_REDIRECT_URI is allowed in Keka OAuth app settings."
                )
                self.wfile.write(msg.encode('utf-8'))
                return
            keka = KekaAttendance()
            success = keka.exchange_callback_code(code, state)
            self.send_response(200 if success else 500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(("OAuth setup complete" if success else "OAuth setup failed").encode('utf-8'))
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
