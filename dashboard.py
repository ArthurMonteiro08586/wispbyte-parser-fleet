"""dashboard.py — stdlib fleet dashboard for Wispbyte parser servers.
Reads bank jsonl, polls each account's /client/api/servers/status, serves HTML on :8700.
Usage: python dashboard.py [--bank wispbyte_accounts.jsonl] [--port 8700]
"""
import argparse, json, threading, time
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE = "https://wispbyte.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"
BANK = "wispbyte_accounts.jsonl"
CACHE = {"ts": 0, "rows": []}


def poll():
    try:
        bank = [json.loads(l) for l in open(BANK, encoding="utf-8") if l.strip()]
    except Exception as e:
        return [{"err": repr(e)}]
    rows = []
    for rec in bank:
        srv = rec.get("server") or {}
        row = {"email": rec.get("email", "?"), "ident": srv.get("identifier"),
               "type": srv.get("type"), "node": srv.get("node"),
               "proxy": (rec.get("proxy") or "home")[:24], "state": "?", "verified": rec.get("verified")}
        if srv.get("identifier") and rec.get("cookies"):
            try:
                ck = "; ".join("%s=%s" % (k, v) for k, v in rec["cookies"].items())
                req = urllib.request.Request(BASE + "/client/api/servers/status")
                req.add_header("User-Agent", UA)
                req.add_header("Cookie", ck)
                with urllib.request.urlopen(req, timeout=25) as r:
                    data = json.loads(r.read().decode())
                for sv in data.get("servers", []):
                    if sv.get("identifier") == row["ident"]:
                        row["state"] = sv.get("current_state")
                        row["cpu"] = sv.get("cpu_absolute")
                        row["mem_mb"] = round((sv.get("memory_bytes") or 0) / 1048576, 1)
            except Exception as e:
                row["state"] = "err:%s" % repr(e)[:40]
        rows.append(row)
    return rows


def refresh_loop():
    while True:
        CACHE["rows"] = poll()
        CACHE["ts"] = time.time()
        time.sleep(90)


def render():
    rows = CACHE["rows"]
    n_run = sum(1 for r in rows if r.get("state") == "running")
    out = ["<html><head><meta charset='utf-8'><title>wispbyte fleet</title><style>",
           "body{background:#0d1117;color:#c9d1d9;font-family:monospace;padding:20px}",
           "table{border-collapse:collapse}td,th{border:1px solid #30363d;padding:6px 10px;text-align:left}",
           ".running{color:#3fb950}.offline{color:#f85149}.installing{color:#d29922}</style></head><body>",
           "<h2>WISPBYTE PARSER FLEET</h2><p>servers: %d | running: <b class='running'>%d</b> | updated: %s</p>" % (
               len(rows), n_run, time.strftime("%H:%M:%S", time.localtime(CACHE["ts"]))),
           "<table><tr><th>ident</th><th>type</th><th>state</th><th>cpu%</th><th>mem MB</th><th>node</th><th>proxy</th><th>email</th></tr>"]
    for r in rows:
        st = r.get("state", "?")
        out.append("<tr><td>%s</td><td>%s</td><td class='%s'>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            r.get("ident"), r.get("type"), st, st, r.get("cpu", ""), r.get("mem_mb", ""),
            r.get("node"), r.get("proxy"), r.get("email", "")[:38]))
    out.append("</table><p><a href='https://t.me/AlStack' style='color:#58a6ff'>t.me/AlStack</a></p></body></html>")
    return "\n".join(out)


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def main():
    global BANK
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", default=BANK)
    ap.add_argument("--port", type=int, default=8700)
    a = ap.parse_args()
    BANK = a.bank
    threading.Thread(target=refresh_loop, daemon=True).start()
    time.sleep(3)
    print("dashboard on http://127.0.0.1:%d (bank=%s)" % (a.port, BANK), flush=True)
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
