import requests
import json
import time
import base64
import hashlib
import secrets
import random as _random_mod
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode, parse_qs
import schedule
import logging
import pytz
import os
import sys

# Redis import attempt
try:
    import redis
except ImportError:
    redis = None
    print("Warning: 'redis' package not found. Install it with 'pip install redis' to use Redis storage.")

# Constants (with environment variable support)
IST = pytz.timezone(os.environ.get('KEKA_TIMEZONE', 'Asia/Kolkata'))
TOKEN_FILE = os.environ.get('KEKA_TOKEN_FILE', 'keka_tokens.json')
REDIS_KEY = os.environ.get('KEKA_REDIS_KEY', 'keka_tokens')
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
TOKEN_EXPIRY_BUFFER = int(os.environ.get('TOKEN_EXPIRY_BUFFER', '300'))
TOKEN_REFRESH_INTERVAL = int(os.environ.get('TOKEN_REFRESH_INTERVAL', '10800'))  # 3 hours in seconds

# Configure logging (after LOG_LEVEL is defined)
log_level_map = {
    'DEBUG': logging.DEBUG,
    'INFO': logging.INFO,
    'WARNING': logging.WARNING,
    'ERROR': logging.ERROR,
    'CRITICAL': logging.CRITICAL
}
logging.basicConfig(
    level=log_level_map.get(LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# Redis connection
kv = None
redis_url = os.environ.get("KV_URL") or os.environ.get("REDIS_URL")
if redis_url:
    if redis is None:
        logging.error("REDIS_URL/KV_URL detected, but 'redis' package is not installed. Please run 'pip install redis'.")
    else:
        try:
            kv = redis.from_url(redis_url)
            # Verify connection
            kv.ping()
            logging.info("Connected to Redis/Vercel KV")
        except Exception as e:
            logging.error(f"Failed to connect to Redis: {e}")
            kv = None

class KekaAttendance:
    def __init__(self):
        self.base_url = os.environ.get('KEKA_BASE_URL', 'https://alchemy.keka.com')
        self.auth_url = os.environ.get('KEKA_AUTH_URL', 'https://app.keka.com')
        self.client_id = os.environ.get('KEKA_CLIENT_ID', '987cc971-fc22-4454-99f9-16c078fa7ff6')
        self.redirect_uri = os.environ.get('KEKA_REDIRECT_URI', 'https://alchemy.keka.com')
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.last_refresh_time = None
        self.user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
    def generate_pkce_pair(self):
        """Generate PKCE code verifier and challenge"""
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8')
        code_verifier = code_verifier.replace('=', '').replace('+', '-').replace('/', '_')
        return code_verifier, self._pkce_challenge_from_verifier(code_verifier)

    def _pkce_challenge_from_verifier(self, code_verifier):
        code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8')
        return code_challenge.replace('=', '').replace('+', '-').replace('/', '_')
    
    def get_authorization_url(self):
        """Generate OAuth authorization URL with PKCE"""
        code_verifier, code_challenge = self.generate_pkce_pair()
        
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code',
            'scope': 'openid kekahr.api hiro.api offline_access',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256'
        }
        
        auth_url = f"{self.auth_url}/connect/authorize?{urlencode(params)}"
        return auth_url, code_verifier
    
    def create_oauth_bootstrap(self, callback_url=None, code_verifier=None):
        """Create OAuth URL. Returns (auth_url, state, code_verifier, redirect_uri).
        Pass code_verifier to reuse an existing PKCE verifier (e.g. when the redirect_uri
        itself embeds the verifier and must be built before the auth URL)."""
        if code_verifier:
            code_challenge = self._pkce_challenge_from_verifier(code_verifier)
        else:
            code_verifier, code_challenge = self.generate_pkce_pair()
        state = secrets.token_urlsafe(24)
        redirect_uri = callback_url or self.redirect_uri or ''

        params = {
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': 'openid kekahr.api hiro.api offline_access',
            'code_challenge': code_challenge,
            'code_challenge_method': 'S256',
            'state': state
        }
        auth_url = f"{self.auth_url}/connect/authorize?{urlencode(params)}"
        return auth_url, state, code_verifier, redirect_uri

    def exchange_callback_code(self, code, code_verifier, redirect_uri=None):
        """Exchange auth code using the provided PKCE verifier. No Redis needed."""
        if not code_verifier:
            return "Missing code_verifier"
        return self.exchange_code_for_token(code, code_verifier, redirect_uri_override=redirect_uri or None)

    def exchange_code_for_token(self, authorization_code, code_verifier, redirect_uri_override=None):
        """Exchange authorization code for access token"""
        token_url = f"{self.auth_url}/connect/token"
        
        data = {
            'grant_type': 'authorization_code',
            'code': authorization_code,
            'redirect_uri': redirect_uri_override or self.redirect_uri,
            'code_verifier': code_verifier,
            'client_id': self.client_id,
            'client_secret': ''
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'User-Agent': self.user_agent
        }
        
        try:
            response = requests.post(token_url, data=data, headers=headers)
            if not response.ok:
                err_body = response.text[:500]
                logging.error(f"Token exchange HTTP {response.status_code}: {err_body}")
                return f"Keka token endpoint returned {response.status_code}: {err_body}"

            token_data = response.json()
            self.access_token = token_data.get('access_token')
            self.refresh_token = token_data.get('refresh_token')
            self.token_expiry = self.decode_jwt_expiry(self.access_token)
            self.last_refresh_time = time.time()

            self.save_tokens()
            return True
        except Exception as e:
            logging.error(f"Error exchange_code_for_token: {e}")
            return f"Exception during token exchange: {e}"
            
    def decode_jwt_expiry(self, token):
        """Decode JWT to get expiry time"""
        try:
            payload = token.split('.')[1]
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += '=' * padding
            decoded = base64.urlsafe_b64decode(payload)
            data = json.loads(decoded)
            return data.get('exp')
        except Exception as e:
            logging.error(f"Error decoding token: {e}")
            return None
    
    def is_token_expired(self):
        """Check if token is expired or expires soon"""
        if not self.token_expiry:
            return True
        return time.time() > (self.token_expiry - TOKEN_EXPIRY_BUFFER)
    
    def should_refresh_token(self):
        """Check if token should be refreshed (every 3 hours or before expiry)"""
        # Always refresh if expired or about to expire
        if self.is_token_expired():
            return True
        
        # Refresh if last refresh was more than 3 hours ago
        if self.last_refresh_time:
            time_since_refresh = time.time() - self.last_refresh_time
            if time_since_refresh >= TOKEN_REFRESH_INTERVAL:
                return True
        
        # If no last refresh time, refresh if token expires in less than 3 hours
        if self.token_expiry:
            time_until_expiry = self.token_expiry - time.time()
            if time_until_expiry < TOKEN_REFRESH_INTERVAL:
                return True
        
        return False
    
    def refresh_access_token(self):
        """Refresh access token using refresh token"""
        if not self.refresh_token:
            logging.error("No refresh token available")
            return False
        
        token_url = f"{self.auth_url}/connect/token"
        
        data = {
            'grant_type': 'refresh_token',
            'refresh_token': self.refresh_token,
            'client_id': self.client_id
        }
        
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'User-Agent': self.user_agent
        }
        
        try:
            response = requests.post(token_url, data=data, headers=headers)
            
            # Log detailed error information for debugging
            if response.status_code != 200:
                logging.error(f"Token refresh failed with status {response.status_code}")
                try:
                    error_data = response.json()
                    logging.error(f"Error response: {error_data}")
                except:
                    logging.error(f"Error response text: {response.text}")
            
            response.raise_for_status()
            
            token_data = response.json()
            self.access_token = token_data.get('access_token')
            # Always update refresh token if provided (some providers rotate refresh tokens)
            if 'refresh_token' in token_data and token_data['refresh_token']:
                self.refresh_token = token_data['refresh_token']
            self.token_expiry = self.decode_jwt_expiry(self.access_token)
            self.last_refresh_time = time.time()
            
            self.save_tokens()
            logging.info("Token refreshed successfully")
            return True
        except requests.exceptions.HTTPError as e:
            if hasattr(e, 'response') and e.response is not None:
                status_code = e.response.status_code
                if status_code == 403:
                    logging.error("403 Forbidden: Refresh token may be expired or invalid. Please re-authenticate.")
                    try:
                        error_data = e.response.json()
                        logging.error(f"Error details: {error_data}")
                    except:
                        logging.error(f"Error response: {e.response.text}")
                else:
                    logging.error(f"HTTP {status_code} error refreshing token: {e}")
                    try:
                        error_data = e.response.json()
                        logging.error(f"Error details: {error_data}")
                    except:
                        logging.error(f"Error response: {e.response.text}")
            else:
                logging.error(f"Error refreshing token: {e}")
            return False
        except Exception as e:
            logging.error(f"Error refreshing token: {e}")
            return False
    
    def save_tokens(self):
        """Save tokens to Redis (if available) or file"""
        tokens = {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'token_expiry': self.token_expiry,
            'last_refresh_time': self.last_refresh_time
        }

        if kv:
            try:
                kv.set(REDIS_KEY, json.dumps(tokens))
                logging.info("Tokens saved to Redis")
            except Exception as e:
                logging.error(f"Failed to save tokens to Redis: {e}")
        else:
            with open(TOKEN_FILE, 'w') as f:
                json.dump(tokens, f)
            logging.info("Tokens saved to file")

    def clear_tokens(self):
        """Delete stored tokens from Redis and file."""
        cleared = []
        if kv:
            try:
                kv.delete(REDIS_KEY)
                cleared.append('redis')
            except Exception as e:
                logging.warning(f"Failed to clear Redis tokens: {e}")
        try:
            import os as _os
            _os.remove(TOKEN_FILE)
            cleared.append('file')
        except FileNotFoundError:
            pass
        except Exception as e:
            logging.warning(f"Failed to clear token file: {e}")
        self.access_token = self.refresh_token = self.token_expiry = self.last_refresh_time = None
        return cleared
    
    def load_tokens(self):
        """Load tokens from Redis (if available) or file"""
        tokens = None
        
        if kv:
            try:
                data = kv.get(REDIS_KEY)
                if data:
                    # Handle both string and bytes responses (Vercel KV may return bytes)
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                    tokens = json.loads(data)
                    logging.info("Tokens loaded from Redis")
                else:
                    logging.warning("No tokens found in Redis")
            except Exception as e:
                logging.error(f"Failed to load tokens from Redis: {e}")
        
        if not tokens:
            try:
                with open(TOKEN_FILE, 'r') as f:
                    tokens = json.load(f)
                    logging.info("Tokens loaded from file")
                    # If we loaded from file but Redis is available, try to save to Redis for next time
                    if kv and tokens:
                        try:
                            kv.set(REDIS_KEY, json.dumps(tokens))
                            logging.info("Tokens from file saved to Redis")
                        except Exception as e:
                            logging.warning(f"Failed to save tokens to Redis: {e}")
            except FileNotFoundError:
                pass
            except Exception as e:
                 logging.error(f"Error loading tokens from file: {e}")

        # Last resort for serverless bootstrapping: allow env-based tokens.
        if not tokens:
            tokens = self._load_tokens_from_env()
            if tokens and kv:
                try:
                    kv.set(REDIS_KEY, json.dumps(tokens))
                    logging.info("Env tokens saved to Redis")
                except Exception as e:
                    logging.warning(f"Failed to save env tokens to Redis: {e}")

        if tokens:
            self.access_token = tokens.get('access_token')
            self.refresh_token = tokens.get('refresh_token')
            self.token_expiry = tokens.get('token_expiry')
            self.last_refresh_time = tokens.get('last_refresh_time')
            if not self.token_expiry and self.access_token:
                self.token_expiry = self.decode_jwt_expiry(self.access_token)
            # If old tokens don't have last_refresh_time, set it to now to start tracking
            if self.last_refresh_time is None and self.token_expiry:
                self.last_refresh_time = time.time()
                # Save updated tokens with last_refresh_time
                self.save_tokens()
            return True
        return False
    

    def _load_tokens_from_env(self):
        """Load tokens from env vars as last-resort bootstrap on serverless deployments."""
        raw_json = os.environ.get('KEKA_TOKENS_JSON')
        if raw_json:
            try:
                tokens = json.loads(raw_json)
                logging.info("Tokens loaded from KEKA_TOKENS_JSON")
                return tokens
            except Exception as e:
                logging.error(f"Invalid KEKA_TOKENS_JSON: {e}")

        refresh_token = os.environ.get('KEKA_REFRESH_TOKEN')
        access_token = os.environ.get('KEKA_ACCESS_TOKEN')
        token_expiry = os.environ.get('KEKA_TOKEN_EXPIRY')

        if refresh_token or access_token:
            tokens = {
                'access_token': access_token,
                'refresh_token': refresh_token,
                'token_expiry': int(token_expiry) if token_expiry and token_expiry.isdigit() else None,
                'last_refresh_time': time.time()
            }
            logging.info("Tokens loaded from KEKA_* environment variables")
            return tokens

        return None

    def clock_action(self, action_type="in", clock_type="web"):
        """Perform clock in or clock out
        
        Args:
            action_type: "in" or "out"
            clock_type: "web" (WFO, manualClockinType=1) or "remote" (WFH, manualClockinType=3)
        """
        # Proactively refresh tokens if needed (every 3 hours or before expiry)
        if self.should_refresh_token():
            logging.info("Token needs refresh (expired or 3+ hours old), refreshing proactively...")
            if not self.refresh_access_token():
                logging.error("Failed to refresh token. Please re-authenticate by running: python keka.py setup")
                logging.error("If running on Vercel, ensure KV_URL is set and run setup locally with KV_URL exported.")
                return False
        
        # Use web clock-in endpoint (for WFO) or remote clock-in (for WFH)
        clock_type = clock_type.lower()
        if clock_type == "web" or clock_type == "wfo":
            endpoint = "webclockin"
            manual_clockin_type = 1
        else:  # remote or wfh
            endpoint = "remoteclockin"
            manual_clockin_type = 3
        
        url = f"{self.base_url}/k/attendance/api/mytime/attendance/{endpoint}"
        
        original_punch_status = 0 if action_type.lower() == "in" else 1
        note = "In" if action_type.lower() == "in" else "Out"
        
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "attendanceLogSource": 1,
            "locationAddress": None,
            "manualClockinType": manual_clockin_type,
            "note": note,
            "originalPunchStatus": original_punch_status
        }

        clock_type_label = "WFO (Web)" if manual_clockin_type == 1 else "WFH (Remote)"
        logging.info(f"Attempting {clock_type_label} clock {action_type.upper()}...")

        # If server returns 401/403 for stale token, refresh and retry once automatically.
        for attempt in range(2):
            headers = {
                'Accept': 'application/json, text/plain, */*',
                'Authorization': f'Bearer {self.access_token}',
                'Content-Type': 'application/json; charset=utf-8',
                'Origin': self.base_url,
                'Referer': f'{self.base_url}/',
                'X-Requested-With': 'XMLHttpRequest',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0'
            }

            try:
                response = requests.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logging.info(f"Clock {action_type.upper()} successful ({clock_type_label}) at {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
                return True
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else None
                if attempt == 0 and status_code in (401, 403):
                    logging.warning("Clock API rejected current token. Attempting one forced refresh and retry...")
                    if self.refresh_access_token():
                        continue
                logging.error(f"Clock {action_type.upper()} failed with HTTP {status_code}: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logging.error(f"Response: {e.response.text}")
                return False
            except requests.exceptions.RequestException as e:
                logging.error(f"Clock {action_type.upper()} failed: {e}")
                if hasattr(e, 'response') and e.response is not None:
                    logging.error(f"Response: {e.response.text}")
                return False

        return False
    
    def clock_in(self, clock_type=None):
        """Clock in with optional clock type (web/WFO or remote/WFH)"""
        if clock_type is None:
            clock_type = os.environ.get('KEKA_CLOCK_TYPE', 'web').lower()
        return self.clock_action("in", clock_type)
    
    def clock_out(self, clock_type=None):
        """Clock out with optional clock type (web/WFO or remote/WFH)"""
        if clock_type is None:
            clock_type = os.environ.get('KEKA_CLOCK_TYPE', 'web').lower()
        return self.clock_action("out", clock_type)

# --- Scheduler / Run Logic ---

def is_weekday():
    """Check if today is a weekday in IST"""
    return datetime.now(IST).weekday() < 5  # Monday = 0, Friday = 4

def _should_run_action(action_key, window_key, start_h, start_m, end_h, end_m, slot=None, step_min=5):
    """Decide if a clock action should fire now, handling Vercel Hobby plan delays.

    Each cron in vercel.json carries its own &slot=HHMM param so we know which
    scheduled slot triggered this invocation. We pick today's random slot (date-seeded)
    and only proceed if this cron's slot matches — the right cron fires even if Hobby
    delays it by 30+ minutes. Redis NX prevents double-fire if the same cron is invoked
    twice in one day.
    """
    now_ist = datetime.now(IST)
    today = int(now_ist.strftime('%Y%m%d'))

    # Pick today's random slot (same value all day for the same window_key)
    rng = _random_mod.Random(today * 10 + window_key)
    start_total = start_h * 60 + start_m
    end_total   = end_h   * 60 + end_m
    slots  = list(range(start_total, end_total + 1, step_min))
    chosen = rng.choice(slots)
    chosen_hhmm = f"{chosen // 60:02d}:{chosen % 60:02d}"
    current = now_ist.hour * 60 + now_ist.minute

    if slot:
        # Cron embeds its own scheduled slot — match exactly against chosen
        slot_int     = int(slot)
        slot_minutes = (slot_int // 100) * 60 + (slot_int % 100)
        if slot_minutes != chosen:
            logging.info(f"{action_key}: cron slot {slot} != chosen {chosen_hhmm}. Skipping.")
            return False
    else:
        # No slot param (manual call without force) — fall back to >= check
        if current < chosen:
            logging.info(f"{action_key}: before chosen slot {chosen_hhmm}. Skipping.")
            return False

    # Safety: don't act if extremely late (Hobby delay > 90 min past window end)
    if current > end_total + 90:
        logging.info(f"{action_key}: >90 min past window end. Skipping.")
        return False

    # Atomically claim via Redis so duplicate invocations don't double-fire
    if kv:
        done_key = f"keka_{action_key}_done"
        try:
            claimed = kv.set(done_key, str(today), nx=True, ex=86400)
            if not claimed:
                existing = kv.get(done_key)
                if isinstance(existing, bytes):
                    existing = existing.decode('utf-8')
                if existing == str(today):
                    logging.info(f"{action_key}: already done today. Skipping.")
                    return False
                # Stale key from a previous day — overwrite and proceed
                kv.set(done_key, str(today), ex=86400)
        except Exception as e:
            logging.warning(f"Redis claim check failed for {action_key}: {e}")

    logging.info(f"{action_key}: chosen slot {chosen_hhmm} matched — proceeding.")
    return True

def run_clock_in(forced=False, slot=None):
    """Executed by Cron or manual button. forced=True bypasses weekday and time-window checks."""
    if not forced and not is_weekday():
        logging.info("Not a weekday. Skipping clock-in.")
        return False
    if not forced and not _should_run_action('clock_in', 0, 9, 0, 9, 30, slot=slot):
        return True  # Not a failure — just not the right slot or already done
    logging.info("Attempting clock in...")
    keka = KekaAttendance()
    if keka.load_tokens():
        return keka.clock_in()
    else:
        logging.error("No tokens found.")
        return False

def run_clock_out(forced=False, slot=None):
    """Executed by Cron or manual button. forced=True bypasses weekday and time-window checks."""
    if not forced and not is_weekday():
        logging.info("Not a weekday. Skipping clock-out.")
        return False
    if not forced and not _should_run_action('clock_out', 1, 18, 30, 19, 0, slot=slot):
        return True  # Not a failure — just not the right slot or already done
    logging.info("Attempting clock out...")
    keka = KekaAttendance()
    if keka.load_tokens():
        return keka.clock_out()
    else:
        logging.error("No tokens found.")
        return False

def run_token_refresh():
    """Proactively refresh tokens every 3 hours"""
    logging.info("Running proactive token refresh...")
    keka = KekaAttendance()
    if keka.load_tokens():
        if keka.should_refresh_token():
            logging.info("Tokens need refresh, refreshing now...")
            return keka.refresh_access_token()
        else:
            logging.info("Tokens are still fresh, no refresh needed.")
            return True
    else:
        logging.error("No tokens found. Cannot refresh.")
        return False

# --- CLI Setup Logic ---

def initial_setup():
    """Initial authentication setup"""
    keka = KekaAttendance()
    print("\n=== Keka Attendance Initial Setup ===\n")
    auth_url, code_verifier = keka.get_authorization_url()
    
    print(f"\n1. Open this URL in your browser:\n\n{auth_url}\n")
    print("2. Login and copy the 'code' parameter.")
    authorization_code = input("\nPaste the code here: ").strip()
    
    if keka.exchange_code_for_token(authorization_code, code_verifier):
        print("\n✓ Setup successful!")
        if kv:
            print("Tokens saved to Redis (Vercel KV).")
            # Also save to file for backup/verification if run locally
            with open(TOKEN_FILE, 'w') as f:
                 # Need to manually get from object as save_tokens handles dual logic
                 tokens = {
                    'access_token': keka.access_token,
                    'refresh_token': keka.refresh_token,
                    'token_expiry': keka.token_expiry
                 }
                 json.dump(tokens, f)
            print("Tokens also saved to local file 'keka_tokens.json'.")
        else:
            print("Tokens saved to local file 'keka_tokens.json'.")
    else:
        print("\n✗ Setup failed.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        if command == "setup":
            initial_setup()
        elif command == "test-in":
            run_clock_in()
        elif command == "test-out":
            run_clock_out()
        else:
            print("Commands: setup, test-in, test-out")
    else:
        print("Usage: python keka.py [setup|test-in|test-out]")