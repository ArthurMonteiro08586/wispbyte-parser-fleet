"""Start all bank servers: write main.py + solve start-captcha + start + status check."""
import requests, json, time, sys

SITEKEY = "0x4AAAAAABT6wll55Cy1WYrA"
SIDE = "http://127.0.0.1:8877/solve"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
MAIN_PY = "import time, socket, datetime\nprint('eni-worker up on', socket.gethostname(), flush=True)\nwhile True:\n    print(datetime.datetime.utcnow().isoformat(), 'alive', flush=True)\n    time.sleep(30)\n"

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def session_for(acc):
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
                      "Origin": "https://wispbyte.com", "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
    for k, v in acc["cookies"].items():
        s.cookies.set(k, v)
    return s

def solve(url):
    for att in range(3):
        r = requests.post(SIDE, json={"type": "turnstile", "url": url, "sitekey": SITEKEY, "real_page": True}, timeout=300)
        j = r.json()
        tok = j.get("token") or j.get("solution") or (j.get("data") or {}).get("token")
        if tok:
            return tok
        time.sleep(5)
    return None

def start_server(acc, ident):
    s = session_for(acc)
    ref = {"Referer": f"https://wispbyte.com/client/servers/{ident}/console"}
    # write main.py (harmless if exists)
    r = s.post("https://wispbyte.com/client/api/server/write-file", headers={"Content-Type": "application/json", **ref},
               json={"serverId": ident, "fileName": "/main.py", "content": MAIN_PY}, timeout=60)
    log(" write:", r.status_code, r.text[:80])
    # captcha verify
    st = s.get("https://wispbyte.com/client/api/server/start-captcha/status", params={"serverId": ident}, headers=ref, timeout=30)
    need = st.json().get("required", True) if st.status_code == 200 else True
    if need:
        tok = solve(f"https://wispbyte.com/client/servers/{ident}/console")
        if not tok:
            log(" NO TOKEN")
            return False
        rv = s.post("https://wispbyte.com/client/api/server/start-captcha/verify", headers={"Content-Type": "application/json", **ref},
                    json={"cf_turnstile_response": tok, "fallback": False}, timeout=60)
        log(" captcha verify:", rv.status_code, rv.text[:120])
    r1 = s.post("https://wispbyte.com/client/api/server/start", headers={"Content-Type": "application/json", **ref},
                json={"serverId": ident}, timeout=60)
    log(" start:", r1.status_code, r1.text[:150])
    if r1.status_code != 200:
        return False
    for i in range(6):
        time.sleep(8)
        try:
            r2 = s.get("https://wispbyte.com/client/api/servers/status", headers=ref, timeout=60).json()
            for sv in r2.get("servers", []):
                if sv["identifier"] == ident:
                    log(" state:", sv["current_state"])
                    if sv["current_state"] == "running":
                        return True
        except Exception as e:
            log(" status err", repr(e)[:100])
    return False

def main():
    bank = [json.loads(l) for l in open("wispbyte_accounts.jsonl", encoding="utf-8")]
    results = []
    for acc in bank:
        srv = acc.get("server") or {}
        ident = srv.get("identifier")
        if not ident:
            log(acc["email"], "no server")
            continue
        log("==", acc["email"], ident)
        ok = start_server(acc, ident)
        results.append((ident, ok))
        time.sleep(10)
    log("RESULTS:", results)

if __name__ == "__main__":
    main()
