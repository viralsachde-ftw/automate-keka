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
        use_dynamic = os.environ.get('KEKA_USE_DYNAMIC_CALLBACK', 'false').lower() == 'true'
        return self._callback_url() if use_dynamic else keka.redirect_uri

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
                status_msg = "loaded=False"
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
        elif action == 'auth-start':
            keka = KekaAttendance()
            try:
                auth_url, _ = keka.create_oauth_bootstrap(self._oauth_redirect_uri(keka))
                self.send_response(302)
                self.send_header('Location', auth_url)
                self.end_headers()
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
        
        status = "Success" if success else "Failed/Skipped"
        self.wfile.write(f"{message}: {status}".encode('utf-8'))
        return
