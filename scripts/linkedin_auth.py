"""
BİR DƏFƏLİK QURULUM SKRİPTİ - bunu GitHub Actions-da yox, öz kompüterində çalışdır.

Məqsəd: LinkedIn-dən refresh_token almaq (bu, ~365 gün etibarlıdır və GitHub
Actions-ın hər gün sənin adından yeni access_token almasına imkan verir).

İşlətməzdən əvvəl:
  pip install requests
  python scripts/linkedin_auth.py

LinkedIn Developer App-ında (Auth bölməsi) Redirect URL kimi mütləq
http://localhost:8765/callback əlavə edilmiş olmalıdır.
"""

import http.server
import urllib.parse
import webbrowser

import requests

REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "openid profile w_member_social"


def main():
    client_id = input("LinkedIn Client ID: ").strip()
    client_secret = input("LinkedIn Client Secret: ").strip()

    auth_url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    })

    received = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            received["code"] = params.get("code", [None])[0]
            received["error"] = params.get("error_description", [None])[0]
            self.send_response(200)
            self.end_headers()
            msg = "Tamamdır, bu pəncərəni bağlaya bilərsən." if received.get("code") else "Xəta baş verdi, terminala bax."
            self.wfile.write(msg.encode("utf-8"))

        def log_message(self, *args):
            pass

    print(f"\nBrauzer açılır, LinkedIn-ə icazə ver: {auth_url}\n")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", 8765), Handler)
    server.handle_request()

    code = received.get("code")
    if not code:
        raise SystemExit(f"Kod alınmadı ({received.get('error')}). Redirect URL-in dəqiq eyni olduğunu yoxla.")

    resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=15,
    )
    resp.raise_for_status()
    tokens = resp.json()

    print("\n--- Bunları GitHub repo-nda Settings > Secrets and variables > Actions bölməsinə əlavə et ---\n")
    print(f"LINKEDIN_CLIENT_ID = {client_id}")
    print(f"LINKEDIN_CLIENT_SECRET = {client_secret}")
    print(f"LINKEDIN_REFRESH_TOKEN = {tokens.get('refresh_token')}")
    print("\naccess_token saxlamağa ehtiyac yoxdur - hər workflow işə düşəndə refresh_token-dan təzədən alınır.")
    print("refresh_token təxminən 365 gün etibarlıdır - bir ildən sonra bu skripti yenidən çalışdırmalı olacaqsan.")


if __name__ == "__main__":
    main()
