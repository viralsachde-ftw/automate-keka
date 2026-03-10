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
        """Pick redirect URI that actually returns callback to this app by default."""
        use_dynamic = os.environ.get('KEKA_USE_DYNAMIC_CALLBACK', '').lower() == 'true'
        use_static = os.environ.get('KEKA_USE_STATIC_REDIRECT', '').lower() == 'true'

        callback_url = self._callback_url()
        configured = (keka.redirect_uri or '').strip()

        if use_dynamic:
            return callback_url
        if use_static and configured:
            return configured

        # If explicitly configured callback URI exists, use it.
        if 'api/cron?action=oauth-callback' in configured:
            return configured

        # Default alchemy redirect never returns to this app callback; prefer callback URL.
        if configured in ('https://alchemy.keka.com', 'http://alchemy.keka.com', ''):
            return callback_url

        # Otherwise keep user-provided custom redirect.
        return configured

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
                status_msg = "loaded=False hint=run_auth_auto_or_set_env_tokens"
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
                # Avoid server-side 302 spam in logs; return one 200 response and redirect client-side.
                auth_url, _ = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
                html = f"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta http-equiv="refresh" content="0; url={auth_url}" />
    <title>Redirecting to Keka...</title>
  </head>
  <body>
    <p>Redirecting to Keka login...</p>
    <p>If not redirected, <a href="{auth_url}">click here</a>.</p>
  </body>
</html>
"""
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
                b"Available actions: in, out, status, auth-auto, auth-start, auth-url, oauth-callback\n"
            )
            return

        status = "Success" if success else "Failed/Skipped"
        self.wfile.write(f"{message}: {status}".encode('utf-8'))
        return
