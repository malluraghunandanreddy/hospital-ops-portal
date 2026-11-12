"""Web server for the Sunrise Hospital operations layer.

Run:  python app/server.py
Runs the same way on the hospital laptop or on a cloud server. Settings come
from environment variables so nothing in the code changes between the two:

  HOSPITAL_PORT        port to listen on (default 8080)
  HOSPITAL_HOST        address to listen on (default 0.0.0.0 = this machine and its Wi-Fi/LAN)
  HOSPITAL_DATA        folder for the database, prescription photos and backups (default ./data)
  HOSPITAL_DEMO=0      first run without demo patients
  HOSPITAL_HTTPS=1     set when served behind HTTPS (cloud) so the login cookie is HTTPS-only
  HOSPITAL_NO_BROWSER=1  do not open a browser window on start
  HOSPITAL_PATIENT_PORT  port of the patients' door (default: HOSPITAL_PORT + 1). It serves ONLY the
                        "My token" page, so it can be opened to a guest Wi-Fi or the internet
                        without exposing the staff portal. 0 turns it off.
  HOSPITAL_TUNNEL=1    put ONLY the patients' door on the internet (needs Cloudflare's free "cloudflared"
                        on this laptop), so patients use their own mobile data and never get the
                        hospital Wi-Fi password. The staff portal stays on the staff Wi-Fi only.
"""
import atexit
import json
import re
import shutil
import subprocess
import mimetypes
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core  # noqa: E402
import access  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(BASE, 'app', 'static')
MAX_BODY = 12 * 1024 * 1024
HTTPS = os.environ.get('HOSPITAL_HTTPS') == '1'
APP = None


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'Sunrise'
    sys_version = ''

    def log_message(self, *args):  # no request logs: URLs must not leak into log files
        pass

    def do_GET(self):
        self.go('GET')

    def do_POST(self):
        self.go('POST')

    def do_PUT(self):
        self.go('PUT')

    def token(self):
        for part in (self.headers.get('Cookie') or '').split(';'):
            k, _, v = part.strip().partition('=')
            if k == 'hs':
                return v
        return None

    def send(self, status, body, ctype, extra=None):
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store' if ctype.startswith('application/json') else 'no-cache')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, data, extra=None):
        self.send(status, json.dumps(data).encode(), 'application/json; charset=utf-8', extra)

    def go(self, method):
        url = urlsplit(self.path)
        path = url.path
        try:
            length = int(self.headers.get('Content-Length') or 0)
            if length > MAX_BODY:
                raise core.ApiError(413, 'File is too large')
            raw = self.rfile.read(length) if length else b''
            if path.startswith('/api/') or path.startswith('/files/'):
                self.api(method, path, dict(parse_qsl(url.query)), raw)
            elif method == 'GET':
                self.static(path)
            else:
                raise core.ApiError(405, 'Not allowed')
        except core.ApiError as e:
            self.send_json(e.status, {'error': e.message})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # never show a stack trace to staff; never print patient data
            sys.stderr.write('Server error: %s in %s %s\n' % (type(e).__name__, method, path.split('?')[0]))
            self.send_json(500, {'error': 'Something went wrong. Please try again.'})

    def api(self, method, path, params, raw):
        ctype = (self.headers.get('Content-Type') or '').split(';')[0].strip().lower()
        body = {}
        if method != 'GET':
            # Only our own pages send these content types, which blocks cross-site form posts.
            if ctype == 'application/json':
                try:
                    body = json.loads(raw.decode() or '{}')
                except ValueError:
                    raise core.ApiError(400, 'Bad request')
                if not isinstance(body, dict):
                    raise core.ApiError(400, 'Bad request')
            elif ctype in core.IMAGE_TYPES or ctype in ('application/pdf', 'text/csv', 'text/plain'):
                body = {'_raw': raw, '_ctype': ctype}
            else:
                raise core.ApiError(415, 'Bad request')
        tok = self.token()
        if method != 'GET':
            body['_ip'] = self.client_address[0]
        res = APP.handle(method, path, params, body, APP.staff_for(tok), tok)
        if '_bytes' in res:
            return self.send(200, res['_bytes'], res['_ctype'], {'Cache-Control': 'private, no-store',
                                                                'Content-Disposition': 'attachment; filename="%s"' % res['_name']})
        if '_file' in res:
            with open(res['_file'], 'rb') as fh:
                data = fh.read()
            return self.send(200, data, res['_ctype'], {'Cache-Control': 'private, no-store'})
        extra = {}
        flags = 'Path=/; HttpOnly; SameSite=Strict' + ('; Secure' if HTTPS else '')
        new_token = res.pop('_set_cookie', None)
        remember = res.pop('_remember', False)
        if new_token:
            # Without "keep me signed in" the cookie ends when the browser is closed (shared computers).
            extra['Set-Cookie'] = 'hs=%s; %s%s' % (new_token, 'Max-Age=%d; ' % access.SESSION_LONG if remember else '', flags)
        if res.pop('_clear_cookie', None):
            extra['Set-Cookie'] = 'hs=; Max-Age=0; ' + flags
        self.send_json(200, res, extra)

    def static(self, path):
        name = {'/': 'index.html', '/display': 'display.html', '/t': 'token.html'}.get(path, path.lstrip('/'))
        full = os.path.realpath(os.path.join(STATIC, name))
        if not full.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(full):
            raise core.ApiError(404, 'Not found')
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        if ctype.startswith('text/') or ctype.endswith('javascript'):
            ctype += '; charset=utf-8'
        with open(full, 'rb') as fh:
            self.send(200, fh.read(), ctype)


class PatientHandler(Handler):
    """The patients' door: only the "My token" page and its numbers. No logins, no staff screens,
    no patient names. Safe to open to a guest Wi-Fi or, through a tunnel, to the internet."""
    ALLOWED = {'/t', '/api/token'}
    LIMIT = 40          # requests per minute from one phone (the page itself asks about 5 times a minute)
    hits = {}
    lock = threading.Lock()

    def do_POST(self):
        self.send_json(405, {'error': 'Not allowed'})

    do_PUT = do_POST

    def client_key(self):
        # Behind a tunnel every request comes from this laptop; the tunnel passes the phone's address.
        return self.headers.get('CF-Connecting-IP') or self.headers.get('X-Forwarded-For', '').split(',')[0].strip() \
            or self.client_address[0]

    def too_many(self):
        now_m = int(time.time() // 60)
        key = self.client_key()
        with self.lock:
            if len(self.hits) > 5000:
                self.hits.clear()
            m, n = self.hits.get(key, (now_m, 0))
            n = n + 1 if m == now_m else 1
            self.hits[key] = (now_m, n)
            return n > self.LIMIT

    def go(self, method):
        path = urlsplit(self.path).path
        if path == '/':
            return self.send(200, ('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">'
                                   '<p style="font:16px system-ui;padding:24px">Scan the QR code on your token slip to see your turn.<br>'
                                   'మీ టోకెన్ స్లిప్‌లోని QR కోడ్‌ను స్కాన్ చేయండి.</p>').encode(), 'text/html; charset=utf-8')
        if path not in self.ALLOWED:
            return self.send_json(404, {'error': 'Not found'})
        if self.too_many():
            return self.send_json(429, {'error': 'Too many requests. Please wait a minute.'})
        super().go(method)

    def api(self, method, path, params, raw):
        # Never look at staff cookies on this door.
        res = APP.handle('GET', path, params, {}, None, None)
        self.send_json(200, res)


def lan_ip():
    """This computer's address on the local Wi-Fi. Prefers home/office ranges (192.168.x) over VPN tunnels."""
    found = []
    for probe in ('192.168.255.255', '172.31.255.255', '10.255.255.255'):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 1))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith('127.') and ip not in found:
                found.append(ip)
        except OSError:
            pass
        finally:
            sock.close()
    try:   # Windows and most Linux: every address of this computer
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith('127.') and ip not in found:
                found.append(ip)
    except OSError:
        pass
    if sys.platform == 'darwin':   # Mac: Wi-Fi / Ethernet adapters
        import subprocess
        for dev in ('en0', 'en1'):
            try:
                ip = subprocess.run(['ipconfig', 'getifaddr', dev], capture_output=True, text=True, timeout=2).stdout.strip()
                if ip and ip not in found:
                    found.append(ip)
            except (OSError, subprocess.SubprocessError):
                pass
    for prefix in ('192.168.', '172.', '10.'):
        for ip in found:
            if ip.startswith(prefix):
                return ip
    return found[0] if found else None


def start_tunnel(port):
    """Open an internet address that leads only to the patients' door. Without an account Cloudflare gives a
    new random address each start; with a fixed one, set it in Settings › Hospital and leave this off."""
    exe = shutil.which('cloudflared') or next((p for p in ('/opt/homebrew/bin/cloudflared', '/usr/local/bin/cloudflared') if os.path.exists(p)), None)
    if not exe:
        print('  Internet door: "cloudflared" is not installed on this laptop, so patients need the Wi-Fi.')
        return
    proc = subprocess.Popen([exe, 'tunnel', '--no-autoupdate', '--url', 'http://127.0.0.1:%d' % port],
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    atexit.register(proc.terminate)

    def watch():
        for line in proc.stderr:
            m = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', line)
            if m and APP.public_base != m.group(0):
                APP.public_base = m.group(0)
                print('  Patients on mobile data:   %s   (token page only)' % m.group(0))
    threading.Thread(target=watch, daemon=True).start()


def background(app):
    """Daily backup, daily summary and sending queued Telegram messages."""
    last_backup = 0
    while True:
        try:
            if time.time() - last_backup > 2 * 3600:
                app.backup()
                last_backup = time.time()
            app.daily_summary_if_due()
            app.flush_outbox()
        except Exception as e:
            sys.stderr.write('Background task problem: %s\n' % type(e).__name__)
        time.sleep(20)


def reset_password(app, username):
    """For a forgotten full-access password: only possible by someone sitting at this laptop."""
    row = app.one('SELECT id, name FROM staff WHERE username=? AND active=1', (username.strip().lower(),))
    if not row:
        print('\n  No active login called "%s". Logins:' % username)
        for r in app.q("SELECT username, name FROM staff WHERE active=1 AND username IS NOT NULL ORDER BY username"):
            print('    %-14s %s' % (r['username'], r['name']))
        return
    pw = access.new_temp_password(app, row['id'])
    app.audit(None, 'staff.password_reset_at_laptop', 'staff', row['id'])
    print('\n  New one-time password for %s (%s):  %s' % (row['name'], username, pw))
    print('  They must choose their own password after logging in.\n')


def main():
    global APP
    data = os.environ.get('HOSPITAL_DATA') or os.path.join(BASE, 'data')
    APP = core.App(data, demo=os.environ.get('HOSPITAL_DEMO', '1') != '0')
    _ip = lan_ip()
    port = int(os.environ.get('HOSPITAL_PORT', '8080'))
    patient_port = int(os.environ.get('HOSPITAL_PATIENT_PORT', port + 1))
    APP.public_base = 'http://%s:%s' % (_ip, patient_port or port) if _ip else ''
    if len(sys.argv) == 3 and sys.argv[1] == '--reset-password':
        return reset_password(APP, sys.argv[2])
    host = os.environ.get('HOSPITAL_HOST', '0.0.0.0')
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    if patient_port:
        tunnel = os.environ.get('HOSPITAL_TUNNEL') == '1'
        # With the internet door, nothing on the Wi-Fi needs this port, so it listens only inside the laptop.
        pd = ThreadingHTTPServer((os.environ.get('HOSPITAL_PATIENT_HOST', '127.0.0.1' if tunnel else host), patient_port), PatientHandler)
        pd.daemon_threads = True
        threading.Thread(target=pd.serve_forever, daemon=True).start()
        if tunnel and not APP.setting('public_url'):
            start_tunnel(patient_port)
    threading.Thread(target=background, args=(APP,), daemon=True).start()
    ip = lan_ip()
    print('\n  Sunrise Hospital is running. Keep this window open.\n')
    print('  On this laptop:            http://localhost:%d' % port)
    if ip:
        print('  On phones (same Wi-Fi):    http://%s:%d' % (ip, port))
        print('  Waiting-hall TV:           http://%s:%d/display' % (ip, port))
    if patient_port:
        print('  Patients\' door (token page only, safe for guest Wi-Fi): port %d' % patient_port)
    for name, user, pw in getattr(APP, 'first_passwords', []):
        print('  First login for %s:  username %s   one-time password %s' % (name, user, pw))
    print('\n  To stop: close this window.\n')
    if os.environ.get('HOSPITAL_NO_BROWSER') != '1':
        threading.Timer(1.0, lambda: webbrowser.open('http://localhost:%d' % port)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
