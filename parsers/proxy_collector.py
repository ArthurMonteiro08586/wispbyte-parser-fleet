"""proxy_collector.py — stdlib free-proxy harvester + liveness checker for Wispbyte servers.
Sources: TheSpeedX, proxyscrape. Checks sample concurrently, posts digest to Telegram,
keeps live list in proxies_live.txt on server disk.
"""
import json, time, urllib.request, re, os
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36"}
LIVE_FILE = "proxies_live.txt"

SOURCES = [
    ("thespeedx", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"),
    ("proxyscrape", "https://api.proxyscrape.com/v4/free-proxy/https-proxy/list?protocol=http&country=all&proxy_type=http&format=txt"),
]
IPPORT = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}:\d{2,5}$")


def fetch_text(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def candidates(limit_per_source=300):
    out = []
    for name, url in SOURCES:
        try:
            txt = fetch_text(url)
            got = [l.strip() for l in txt.splitlines() if IPPORT.match(l.strip())][:limit_per_source]
            out.extend(got)
            print("proxy src %s: %d" % (name, len(got)), flush=True)
        except Exception as e:
            print("proxy src %s err: %r" % (name, e), flush=True)
    return list(dict.fromkeys(out))


def check_one(px, timeout=7):
    proxy_handler = urllib.request.ProxyHandler({"http": "http://" + px, "https": "http://" + px})
    opener = urllib.request.build_opener(proxy_handler)
    t0 = time.time()
    try:
        r = opener.open("http://api.ipify.org/", timeout=timeout)
        body = r.read(64).decode().strip()
        if IPPORT.match(body) or re.match(r"^\d+\.\d+", body):
            return px, round(time.time() - t0, 2)
    except Exception:
        pass
    return None


def run(cfg, send_tg):
    if not cfg.get("proxy_enabled", True):
        print("proxy role disabled on this server", flush=True)
        return
    shard_i = int(cfg.get("proxy_shard_i", 0))
    shard_n = max(1, int(cfg.get("proxy_shard_n", 1)))
    sample_cap = cfg.get("proxy_sample", 150)
    while True:
        try:
            cands = candidates()
            cands = cands[shard_i::shard_n]  # disjoint slice per server
            sample = cands[:sample_cap] if cands else []
            live = []
            if sample:
                with ThreadPoolExecutor(max_workers=25) as ex:
                    futs = [ex.submit(check_one, p) for p in sample]
                    for f in as_completed(futs, timeout=180):
                        r = f.result()
                        if r:
                            live.append(r)
            live.sort(key=lambda x: x[1])
            if live:
                with open(LIVE_FILE, "a", encoding="utf-8") as f:
                    for px, lat in live:
                        f.write("%s\n" % px)
                top = "\n".join("%s (%.1fs)" % (px, lat) for px, lat in live[:30])
                send_tg("<b>PROXY DIGEST</b> (%s)\nlive %d/%d checked\n<pre>%s</pre>" % (
                    cfg.get("server_label", "?"), len(live), len(sample), top))
            else:
                print("no live proxies this cycle (%d candidates)" % len(sample), flush=True)
        except Exception as e:
            print("proxy loop err: %r" % e, flush=True)
        time.sleep(cfg.get("proxy_interval_min", 180) * 60)
