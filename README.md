# 🚦 Distributed Rate Limiter

A distributed API rate limiter built with **FastAPI + Redis**. Several API
instances share one Redis, so a client's limit is enforced **across the whole
cluster** — not once per server.

📍 **Status:** Phases 1–4 done (setup → fixed window). See [ROADMAP.md](ROADMAP.md) for the full plan.

---

## ⚡ Quick start

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

docker run -d --name redis -p 6379:6379 redis:7   # start Redis
uvicorn app.main:app --reload
```

Open 👉 http://localhost:8000/docs

---

## 🧪 Try the limit

Default limit: **10 requests per 60 seconds**, per API key.

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: user1" localhost:8000/api/data
done
```

➡️ The first 10 return `200`, the rest return `429`.

Every response carries:

| Header | Meaning |
|--------|---------|
| `X-RateLimit-Limit` | requests allowed per window |
| `X-RateLimit-Remaining` | how many are left |
| `Retry-After` | seconds to wait (only on `429`) |

---

## 🔌 Endpoints

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/health` | never rate limited, reports Redis status |
| `GET` | `/api/data` | rate limited, returns which instance answered |

---

## ⚙️ Configuration

Set these as environment variables:

| Variable | Default | Meaning |
|----------|---------|---------|
| `REDIS_URL` | `redis://localhost:6379/0` | shared state store |
| `RATE_LIMIT` | `10` | requests per window |
| `WINDOW_SECONDS` | `60` | window length |
| `ALGORITHM` | `fixed` | `fixed` today, `sliding` in phase 5 |

```bash
RATE_LIMIT=5 WINDOW_SECONDS=10 uvicorn app.main:app --reload
```

---

## 🧠 How the fixed window works

1. Time is chopped into buckets of `WINDOW_SECONDS`
2. Each request runs `INCR` on `rl:fixed:<client>:<bucket>` in Redis
3. `EXPIRE` makes the key clean itself up
4. Counter above the limit → `429`

Because the key lives in **Redis**, every API instance sees the same counter 🎯

⚠️ **The catch:** a client can send 10 requests at `0:59` and 10 more at
`1:01` — 20 requests in 2 seconds. The **sliding window** (phase 5) fixes this.

---

## ✅ Tests

```bash
pytest -v
```

10 tests, using `fakeredis` — no running Redis needed.

---

## 📁 Layout

```
app/
├── main.py            # FastAPI app + rate limit middleware
├── config.py          # settings from environment variables
├── redis_client.py    # Redis connection
└── limiter/
    ├── base.py          # Decision + RateLimiter interface
    └── fixed_window.py  # phase 4 algorithm
tests/
```
