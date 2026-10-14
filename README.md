# wispbyte-parser-fleet

Fleet tooling for [wispbyte.com](https://wispbyte.com) free Pterodactyl servers: mass registration (free-proxy rotation), parser deployment via pure HTTP client API, live dashboard. No browser needed — the whole lifecycle is HTTP + Cloudflare Turnstile tokens from any local solver.

## Free tier facts (measured)

- 1 free server per account: **512MB RAM / 1GB disk / 35% CPU**, 24/7, Python 3.11 / Node / Bun / Java / Rust / Lua
- Login to the client area every 14 days or the server is suspended
- Register rate-limit: ~5-8 attempts per **exit IP** per hour (429 + `retryAfterSeconds`); rotating ports of the same host does NOT help — use distinct exit IPs
- Email verification is mandatory (any temp-mail with API inbox access works)
- Server start is gated by Turnstile (`start-captcha/verify`, 5h session TTL after each solve)

## Layout

```
farm/wisp_farm2.py   account+server farm: temp inbox -> turnstile -> register -> verify -> create (proxy rotation, dedup by exit IP)
farm/start_all.py    boot every bank server: write entry file -> solve start-captcha -> start -> confirm running
deploy.py            upload parsers/*.py + config.json to each server (write-file API) -> restart -> verify
dashboard.py         stdlib HTML dashboard on :8700 (state/cpu/mem per server)
parsers/             the payload: main.py supervisor + forum_lite.py + proxy_collector.py (stdlib only)
config.example.json  parser config template (TG bot token/chat, intervals)
```

## Quick start

```bash
# 1. farm accounts+servers (turnstile solver must listen on 127.0.0.1:8877, /solve endpoint,
#    body: {"type":"turnstile","url":...,"sitekey":"0x4AAAAAABT6wll55Cy1WYrA","real_page":true})
python farm/wisp_farm2.py 10 python,nodejs

# 2. boot servers (writes entry file, solves start-captcha, starts)
python farm/start_all.py

# 3. deploy parsers (bot token via env or --token-file regex extraction; never committed)
export WISP_TG_TOKEN="***"
python deploy.py --bank farm/wispbyte_accounts.jsonl --only-python --chat -100xxxxxxxxxx

# 4. dashboard
python dashboard.py --bank farm/wispbyte_accounts.jsonl --port 8700
```

## Parser payload

- `forum_lite.py` — polls nodeloc.com `latest.json` + v2ex hot API, keyword filter (freebies/AI/proxy), dedup state on disk, new items -> Telegram
- `proxy_collector.py` — harvests TheSpeedX + proxyscrape free lists, concurrent liveness check, digest -> Telegram, appends `proxies_live.txt` on the server
- `main.py` — supervisor: boot message, threads, crash-restart, 6h heartbeat

Everything is Python stdlib — no pip installs on the free tier.

## Notes

- `serverId` in power/file APIs is the short **identifier** (e.g. `cc044323`), not the numeric id
- Bank file (`wispbyte_accounts.jsonl`) holds cookies = the only auth; keep it out of git (`.gitignore`d)
- Python egg entry is `main.py` (env `PY_FILE`); node/bun eggs need `index.js` + `package.json` instead

👻 [t.me/AlStack](https://t.me/AlStack)
