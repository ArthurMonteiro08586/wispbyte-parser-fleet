"""Wispbyte farm v2 — proxy rotation. Pulls alive proxies from proxy_bot proxies.db,
tests against wispbyte.com, registers via proxy (turnstile solved locally on :8877).
Usage: python wisp_farm2.py N [types]
"""
import requests, json, secrets, time, sys, re, sqlite3, os

BASE = "https://wispbyte.com"
SITEKEY = "0x4AAAAAABT6wll55Cy1WYrA"
SIDE = "http://127.0.0.1:8877/solve"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
BANK = "wispbyte_accounts.jsonl"
VOIDASH_API = "https://api.voidash.com/api/v1"
AUTHK = "Bea" + "rer "
DB = "C:/Users/User/Desktop/proxy_bot/proxies.db"

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
TYPES = (sys.argv[2].split(",") if len(sys.argv) > 2 else ["python", "nodejs"])
pat_verify = re.compile(r'https://wispbyte\.com/client/api/verify-email\?token=[a-f0-9]+')

def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)

def hdr_browser():
    return {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9", "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"', "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
    }

def get_proxies(limit=900):
    # one proxy per DISTINCT exit_ip (rate-limit is per exit IP, rotating ports of same host don't help)
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT proxy, exit_ip FROM pool WHERE alive=1 AND protocol='http'
           ORDER BY score DESC"""
    ).fetchall()
    con.close()
    seen = set()
    out = []
    for px, ip in rows:
        key = ip or px.split("//")[-1].split(":")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(px)
        if len(out) >= limit:
            break
    return out

def proxy_ok(px):
    try:
        r = requests.get(BASE + "/client/register", proxies={"http": px, "https": px},
                         headers=hdr_browser(), timeout=12)
        return r.status_code == 200
    except Exception:
        return False

def make_inbox():
    r = requests.post(VOIDASH_API + "/inboxes", json={"domain": "voidash.bond"}, timeout=30)
    r.raise_for_status()
    d = r.json()
    return d["address"], d["session_key"]

def solve_turnstile(url):
    r = requests.post(SIDE, json={"type": "turnstile", "url": url, "sitekey": SITEKEY, "real_page": True}, timeout=300)
    j = r.json()
    return j.get("token") or j.get("solution") or (j.get("data") or {}).get("token")

def register_one(idx, px_pool, used_px):
    stype = TYPES[idx % len(TYPES)]
    email = vkey = None
    for px in px_pool:
        if px in used_px:
            continue
        if not proxy_ok(px):
            used_px.add(px)
            continue
        try:
            email, vkey = make_inbox()
            username = "w" + secrets.token_hex(5)
            password = "Ws!" + secrets.token_hex(9) + "x7"
            tok = solve_turnstile(BASE + "/client/register")
            if not tok:
                log("  no token, next proxy")
                used_px.add(px)
                continue
            H = hdr_browser()
            H.update({"Content-Type": "application/json", "Origin": BASE, "Referer": BASE + "/client/register",
                      "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"})
            proxies = {"http": px, "https": px}
            r = requests.post(BASE + "/client/api/register", headers=H, proxies=proxies,
                              json={"email": email, "password": password, "cf_turnstile_response": tok, "username": username},
                              timeout=60)
            if r.status_code != 201:
                log(f"  reg via {px}: {r.status_code} {r.text[:120]}")
                used_px.add(px)
                continue
            used_px.add(px)
            log(f"  reg OK via {px}")
            cookies = dict(r.cookies)
            # verify (direct, no proxy needed for voidash; wispbyte click via proxy)
            HV = {"Authorization": AUTHK + vkey, "User-Agent": "Mozilla/5.0"}
            s = requests.Session()
            s.headers.update(hdr_browser())
            s.proxies = proxies
            for k, v in cookies.items():
                s.cookies.set(k, v)
            verified = False
            for t in range(12):
                rj = requests.get(VOIDASH_API + "/messages", headers=HV, timeout=30)
                msgs = rj.json() if rj.status_code == 200 else []
                if isinstance(msgs, dict):
                    msgs = msgs.get("messages", msgs.get("data", []))
                for m in msgs:
                    rr = requests.get(f"{VOIDASH_API}/messages/{m.get('id')}", headers=HV, timeout=30)
                    if rr.status_code == 200:
                        c = pat_verify.findall(rr.text)
                        if c:
                            rv = s.get(c[0], timeout=40, allow_redirects=True)
                            verified = rv.status_code == 200
                            break
                if verified:
                    break
                time.sleep(10)
            cookies = {k: v for k, v in s.cookies.items()}
            # create server
            r2 = s.post(BASE + "/client/api/servers/create", headers={"Content-Type": "application/json"},
                        json={"name": f"eni-worker-{secrets.token_hex(3)}", "description": "", "type": stype}, timeout=90)
            srv = {"error": f"{r2.status_code}: {r2.text[:150]}"}
            if r2.status_code == 200:
                at = r2.json().get("attributes", {})
                srv = {"server_id": at.get("id"), "identifier": at.get("identifier"), "uuid": at.get("uuid"),
                       "node": at.get("node"), "status": at.get("status"), "type": stype}
            log("  server:", json.dumps(srv)[:180])
            rec = {"ts": int(time.time()), "email": email, "password": password, "username": username,
                   "voidash_key": vkey, "cookies": cookies, "server": srv, "verified": verified, "proxy": px}
            with open(BANK, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            return "server_id" in srv
        except Exception as e:
            log("  EXC:", repr(e)[:200])
            used_px.add(px)
    return False

def main():
    px_pool = get_proxies(900)
    log("proxy pool:", len(px_pool))
    used = set()
    ok = 0
    for i in range(N):
        log(f"[{i+1}/{N}]")
        if register_one(i, px_pool, used):
            ok += 1
        time.sleep(20 + secrets.randbelow(20))
    log(f"DONE ok={ok}/{N}")

if __name__ == "__main__":
    main()
