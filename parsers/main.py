"""main.py — supervisor for Wispbyte parser fleet (stdlib only, Python 3.11 egg).
Uploads sit next to this file: forum_lite.py, proxy_collector.py, config.json.
Boot message -> Telegram; then parser loops in threads; auto-restart loops on crash.
"""
import json, threading, time, socket, sys, urllib.request, traceback


def load_cfg():
    try:
        return json.load(open("config.json", encoding="utf-8"))
    except Exception:
        return {}


CFG = load_cfg()


def send_tg(text, tries=3):
    tok = CFG.get("tg_bot_token", "")
    chat = CFG.get("tg_chat_id")
    if not tok or not chat:
        print("[tg] not configured:", text[:120], flush=True)
        return False
    url = "https://api.telegram.org/bot%s/sendMessage" % tok
    payload = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML",
               "disable_web_page_preview": True}
    th = CFG.get("tg_thread_id")
    if th:
        payload["message_thread_id"] = th
    data = json.dumps(payload).encode()
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status == 200
        except Exception as e:
            print("[tg] err %r" % e, flush=True)
            time.sleep(5 + i * 5)
    return False


def loop_guard(name, fn):
    while True:
        try:
            fn()
        except Exception:
            print("[supervisor] %s crashed, restart in 30s\n%s" % (name, traceback.format_exc()[-600:]), flush=True)
            time.sleep(30)


def main():
    label = CFG.get("server_label", socket.gethostname())
    send_tg("<b>[fleet]</b> %s UP py=%s host=%s" % (label, sys.version.split()[0], socket.gethostname()))
    import forum_lite, proxy_collector
    t1 = threading.Thread(target=loop_guard, args=("forum", lambda: forum_lite.run(CFG, send_tg)), daemon=True)
    t2 = threading.Thread(target=loop_guard, args=("proxy", lambda: proxy_collector.run(CFG, send_tg)), daemon=True)
    t1.start(); t2.start()
    hb = 0
    while True:
        time.sleep(60)
        hb += 1
        if hb % (CFG.get("heartbeat_hours", 6) * 60) == 0:
            send_tg("<b>[fleet]</b> %s heartbeat ok (forum=%s proxy=%s)" % (
                label, t1.is_alive(), t2.is_alive()))


if __name__ == "__main__":
    main()
