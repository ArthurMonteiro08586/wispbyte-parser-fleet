"""deploy.py — deploy parser fleet to Wispbyte free servers via client HTTP API.

Reads bank (accounts jsonl with cookies), uploads parsers/*.py + config.json to each
server via /client/api/server/write-file, restarts, verifies running.

Secrets NEVER live in this repo:
  --token-file PATH   file to regex-extract BOT_TOKEN from (e.g. your feed bot script)
  or env WISP_TG_TOKEN
  --chat CHAT_ID      telegram chat for parser output (default -1003927191915)

Usage:
  python deploy.py --bank wispbyte_accounts.jsonl [--only-python] [--no-restart]
"""
import argparse, json, os, re, sys, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = "https://wispbyte.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
PARSER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "parsers")


class Api:
    def __init__(self, cookies):
        self.cookies = cookies

    def _req(self, method, path, body=None, timeout=60):
        url = BASE + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("User-Agent", UA)
        req.add_header("Accept", "*/*")
        req.add_header("Origin", BASE)
        req.add_header("Referer", BASE + "/client/servers")
        if data:
            req.add_header("Content-Type", "application/json")
        ck = "; ".join("%s=%s" % (k, v) for k, v in self.cookies.items())
        req.add_header("Cookie", ck)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")[:300]
        except Exception as e:
            return -1, repr(e)[:200]

    def write_file(self, ident, name, content):
        return self._req("POST", "/client/api/server/write-file",
                         {"serverId": ident, "fileName": name, "content": content})

    def power(self, action, ident):
        return self._req("POST", "/client/api/server/%s" % action, {"serverId": ident})

    def status(self):
        return self._req("GET", "/client/api/servers/status")


def state_of(api, ident):
    code, body = api.status()
    if code != 200:
        return "?"
    try:
        for sv in json.loads(body).get("servers", []):
            if sv.get("identifier") == ident:
                return sv.get("current_state")
    except Exception:
        pass
    return "?"


def deploy_one(rec, cfg, files, do_restart=True):
    ident = (rec.get("server") or {}).get("identifier")
    if not ident:
        return ident, "no server"
    api = Api(rec["cookies"])
    c = dict(cfg)
    c["server_label"] = "wisp-%s" % ident
    uploads = list(files.items()) + [("config.json", json.dumps(c))]
    for name, content in uploads:
        code, body = api.write_file(ident, "/" + name, content)
        if code != 200:
            return ident, "write %s fail %s %s" % (name, code, body[:80])
    if not do_restart:
        return ident, "uploaded (no restart)"
    st = state_of(api, ident)
    if st == "running":
        code, body = api.power("restart", ident)
        if code != 200:
            api.power("stop", ident); time.sleep(6)
            code, body = api.power("start", ident)
        if code != 200 and "CAPTCHA" in body.upper():
            return ident, "uploaded, restart needs captcha"
    else:
        code, body = api.power("start", ident)
        if code != 200 and "CAPTCHA" in body.upper():
            return ident, "uploaded, start needs captcha"
    for _ in range(8):
        time.sleep(8)
        if state_of(api, ident) == "running":
            return ident, "DEPLOYED running"
    return ident, "uploaded, state=%s" % state_of(api, ident)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default="wispbyte_accounts.jsonl")
    ap.add_argument("--token-file", default=os.environ.get("WISP_TOKEN_FILE", ""))
    ap.add_argument("--chat", default=os.environ.get("WISP_TG_CHAT", "-1003927191915"))
    ap.add_argument("--thread", default=os.environ.get("WISP_TG_THREAD", ""))
    ap.add_argument("--only-python", action="store_true")
    ap.add_argument("--no-restart", action="store_true")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    token = os.environ.get("WISP_TG_TOKEN", "")
    if not token and a.token_file:
        m = re.search(r"BOT_TOKEN\s*=\s*['\"]([0-9]+:[A-Za-z0-9_\-]+)", open(a.token_file, encoding="utf-8", errors="ignore").read())
        if m:
            token = m.group(1)
    if not token:
        print("no TG token (env WISP_TG_TOKEN or --token-file)"); sys.exit(1)

    cfg = {"tg_bot_token": token, "tg_chat_id": int(a.chat),
           "tg_thread_id": int(a.thread) if a.thread else None}

    files = {}
    for fn in os.listdir(PARSER_DIR):
        if fn.endswith(".py"):
            files[fn] = open(os.path.join(PARSER_DIR, fn), encoding="utf-8").read()
    print("parser files:", sorted(files))

    bank = [json.loads(l) for l in open(a.bank, encoding="utf-8") if l.strip()]
    if a.only_python:
        bank = [r for r in bank if (r.get("server") or {}).get("type") == "python"]
    print("targets:", len(bank))

    # role assignment: server 0 = forum + proxy shard, rest = proxy shards only
    roles = {}
    n = len(bank)
    for i, rec in enumerate(bank):
        ident = (rec.get("server") or {}).get("identifier")
        roles[ident] = {"forum_enabled": i == 0, "proxy_enabled": True,
                        "proxy_shard_i": i, "proxy_shard_n": max(1, n - 1) if n > 1 else 1}
        # shard slices: forum server takes shard 0 of (n-1)? keep simple: i%n shards over all servers
        roles[ident]["proxy_shard_i"] = i
        roles[ident]["proxy_shard_n"] = n

    results = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(deploy_one, r, {**cfg, **roles[(r.get("server") or {}).get("identifier")]}, files, not a.no_restart) for r in bank]
        for f in futs:
            ident, msg = f.result()
            print(ident, "->", msg, flush=True)
            results.append((ident, msg))
    ok = sum(1 for _, m in results if "DEPLOYED" in m)
    print("== deployed %d/%d ==" % (ok, len(results)))


if __name__ == "__main__":
    main()
