"""forum_lite.py — stdlib forum/JSON feed parser for Wispbyte free servers.
Sources: nodeloc.com latest.json, v2ex hot.json. Keyword filter (freebies/AI/abuse).
Dedup via state file, new items -> Telegram.
"""
import json, time, urllib.request, urllib.error, os, re

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}
STATE = "forum_state.json"
KEYWORDS = re.compile(r"免费|白嫖|福利|羊毛|AI|GPT|Claude|Gemini|proxy|VPN|VPS|api|key|注册|羊毛党|free|credit", re.I)

SOURCES = {
    "nodeloc": "https://www.nodeloc.com/latest.json",
    "v2ex": "https://www.v2ex.com/api/topics/hot.json",
}


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".tmp"
    json.dump(st, open(tmp, "w", encoding="utf-8"))
    os.replace(tmp, STATE)


def parse_nodeloc(data):
    out = []
    for t in (data.get("topic_list") or {}).get("topics", [])[:40]:
        out.append({
            "id": "nl-%s" % t.get("id"),
            "title": t.get("title", ""),
            "url": "https://www.nodeloc.com/t/%s" % t.get("slug", t.get("id")),
            "src": "nodeloc",
        })
    return out


def parse_v2ex(data):
    out = []
    if not isinstance(data, list):
        return out
    for t in data[:40]:
        out.append({
            "id": "vx-%s" % t.get("id"),
            "title": t.get("title", ""),
            "url": t.get("url", ""),
            "src": "v2ex",
        })
    return out


PARSERS = {"nodeloc": parse_nodeloc, "v2ex": parse_v2ex}


def collect():
    st = load_state()
    seen = set(st.get("seen", []))
    fresh = []
    for name, url in SOURCES.items():
        try:
            data = fetch(url)
            for it in PARSERS[name](data):
                if it["id"] in seen:
                    continue
                seen.add(it["id"])
                if KEYWORDS.search(it["title"]):
                    fresh.append(it)
        except Exception as e:
            print("forum src %s err: %r" % (name, e), flush=True)
    st["seen"] = list(seen)[-4000:]
    st["last_run"] = int(time.time())
    save_state(st)
    return fresh


def run(cfg, send_tg):
    first = True
    while True:
        try:
            fresh = collect()
            if fresh and not first:
                lines = ["<b>FORUM LITE</b> (%s)" % cfg.get("server_label", "?")]
                for it in fresh[:10]:
                    lines.append('- <a href="%s">%s</a> <i>%s</i>' % (it["url"], it["title"][:90].replace("<", "&lt;"), it["src"]))
                send_tg("\n".join(lines))
            elif fresh and first:
                print("first run: seeded %d items (silent)" % len(fresh), flush=True)
            first = False
        except Exception as e:
            print("forum loop err: %r" % e, flush=True)
        time.sleep(cfg.get("forum_interval_min", 20) * 60)
