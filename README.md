# 🚦 Distributed Rate Limiter

A distributed API rate limiter built with **FastAPI + Redis**. Several API
instances share one Redis, so a client's limit is enforced **across the whole
cluster** — not once per server.

📍 **Status:** Phases 1–5 done (setup → sliding window). See [ROADMAP.md](ROADMAP.md) for the full plan.

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
| `ALGORITHM` | `sliding` | `fixed` or `sliding` |

```bash
ALGORITHM=fixed RATE_LIMIT=5 WINDOW_SECONDS=10 uvicorn app.main:app --reload
```

---

## 🧠 The two algorithms

### 🪣 Fixed window — `ALGORITHM=fixed`

1. Time is chopped into buckets of `WINDOW_SECONDS`
2. Each request runs `INCR` on `rl:fixed:<client>:<bucket>`
3. `EXPIRE` makes the key clean itself up
4. Counter above the limit → `429`

⚠️ **The catch — boundary burst:** a client can send 10 requests at `0:59`
and 10 more at `1:01`. That's **20 requests in 2 seconds**, even though the
limit says 10 per minute 😱

### 🎚️ Sliding window — `ALGORITHM=sliding` (default)

Keeps a **log of timestamps** in a Redis sorted set, and always looks at the
last `WINDOW_SECONDS` — so the window moves with the clock:

1. `ZREMRANGEBYSCORE` drops timestamps older than the window
2. `ZCARD` counts what's left
3. Under the limit → `ZADD` this request, else `429`

All three steps run inside **one Lua script**, so Redis executes them
atomically ⚛️ Two API instances can never both read "9 used" and both let a
request through.

| | Fixed | Sliding |
|---|-------|---------|
| Redis memory | 1 integer per client | 1 entry per request in window |
| Boundary burst | ❌ up to 2x the limit | ✅ blocked |
| Redis commands | `INCR` + `EXPIRE` | 1 Lua script |

Because the state lives in **Redis**, every API instance shares one budget 🎯

---

## ✅ Tests

```bash
pytest -v
```

18 tests, using `fakeredis` — no running Redis needed. They cover both
algorithms, shared budgets across two limiter instances, and a
`test_sliding_window_stops_the_boundary_burst` test that fires a burst across
a bucket boundary: the fixed window lets **8** requests through where the
limit is 4, the sliding window lets exactly **4**.

---

## 📁 Layout

```
app/
├── main.py            # FastAPI app + rate limit middleware
├── config.py          # settings from environment variables
├── redis_client.py    # Redis connection
└── limiter/
    ├── base.py            # Decision + RateLimiter interface
    ├── fixed_window.py    # INCR + EXPIRE
    └── sliding_window.py  # sorted set + Lua script
tests/
```
