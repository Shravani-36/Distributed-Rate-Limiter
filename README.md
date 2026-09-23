# 🚦 Distributed Rate Limiter

A distributed API rate limiter built with **FastAPI + Redis**. Several API
instances share one Redis, so a client's limit is enforced **across the whole
cluster** — not once per server.

📍 **Status:** Phases 1–11 done (setup → Kubernetes). See [ROADMAP.md](ROADMAP.md) for the full plan.

---

## 🐳 Run the full cluster (recommended)

Three API instances + Nginx + Redis + Prometheus + Grafana, in one command:

```bash
docker compose up --build
```

| What | Where |
|------|-------|
| 🚦 API (via Nginx) | http://localhost:8080 |
| 📈 Grafana dashboard | http://localhost:3000 |
| 🔍 Prometheus | http://localhost:9090 |

Then hit the load balancer 👉 http://localhost:8080

```bash
for i in $(seq 1 12); do
  curl -s -D- -o /dev/null -H "X-API-Key: user1" localhost:8080/api/data \
    | grep -Ei "^HTTP|x-instance" | tr -d '\r' | paste -sd' '
done
```

➡️ Watch `x-instance` change every request — **but the limit still holds**,
because all three instances share one Redis 🎯 That's what makes this
*distributed*.

---

## ⚡ Run a single instance (for development)

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
| `X-RateLimit-Algorithm` | `fixed` or `sliding` |
| `X-Instance` | which API instance answered |
| `X-RateLimit-Degraded` | `true` when Redis was down and the limit wasn't checked |
| `Retry-After` | seconds to wait (only on `429`) |

---

## 🔌 Endpoints

| Method | Path | Notes |
|--------|------|-------|
| `GET` | `/health` | never rate limited, reports Redis status |
| `GET` | `/metrics` | Prometheus metrics, never rate limited |
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
| `INSTANCE_NAME` | hostname | name shown in `X-Instance` |
| `FAIL_OPEN` | `true` | what to do when Redis is down (see below) |

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

## 🛡️ What happens when Redis dies?

Redis holds the shared counters, so during an outage there is **no way to know**
if a client is over its limit. There's no correct answer — only a trade-off you
pick in advance with `FAIL_OPEN`:

| | `FAIL_OPEN=true` (default) | `FAIL_OPEN=false` |
|---|---|---|
| Request | ✅ served | ❌ `429` |
| Priority | availability | correctness |
| Risk | an abuser is unlimited during the outage | your API is down |
| `/health` | `200` — keep sending traffic | `503` — pull me from rotation |
| Use for | public APIs | limits guarding payments or a paid upstream |

Either way, the outage is **logged and counted** (never silently swallowed),
and responses carry `X-RateLimit-Degraded: true` so you can see the limit
wasn't really checked.

🧪 **Try it** (kill Redis while the API runs):

```bash
docker compose stop redis     # API keeps answering 200, marked degraded
curl -s localhost:8080/health # {"status":"degraded","redis":false,...}
docker compose start redis    # limits come back on their own
```

Real run, limit 2:

```
Redis UP     200 remaining: 1
             200 remaining: 0
             429                        ⬅️ limit works
Redis KILLED 200 remaining: -1 degraded: true   ⬅️ still serving
             200 remaining: -1 degraded: true
Redis BACK   200 remaining: 1
             200 remaining: 0
             429                        ⬅️ limit back, no restart needed
```

---

## ✅ Tests

```bash
pytest -v
```

32 tests, using `fakeredis` — no running Redis needed. They cover both
algorithms, shared budgets across two limiter instances, and a
`test_sliding_window_stops_the_boundary_burst` test that fires a burst across
a bucket boundary: the fixed window lets **8** requests through where the
limit is 4, the sliding window lets exactly **4**.

### 🏁 Verified under concurrency

60 requests fired **in parallel** at 3 instances sharing one Redis, limit 20:

```
     20 200
     40 429
```

Exactly 20 got through — no overshoot. That's the Lua script doing
trim → count → add atomically ⚛️

---

## 📊 Load testing (k6)

```bash
# throughput and latency
BASE_URL=http://localhost:8080 k6 run loadtest/load_test.js

# does the limit hold when 50 VUs hit the same key at once?
BASE_URL=http://localhost:8080 RATE_LIMIT=10 k6 run loadtest/accuracy_test.js
```

Headline numbers from a real run (100 VUs, 3 instances, limit 50/min/key):

| | |
|---|---|
| Requests | **175,873** at **3,908 req/s** |
| Failures | **0.00%** — no 5xx, ever |
| Latency | **p95 27ms**, p99 45ms |
| Allowed | **exactly 5,000** = 100 keys × 50 🎯 |

And the fixed window's boundary burst showed up **in the load test itself** —
it allowed **10,000** where the limit implies 5,000, while the sliding window
allowed exactly 5,000 💥

📄 Full methodology, the algorithm comparison and how to reproduce:
**[loadtest/RESULTS.md](loadtest/RESULTS.md)**

---

## 📈 Monitoring

`docker compose up` brings up Prometheus and Grafana with the datasource and
dashboard **already provisioned** — open http://localhost:3000 and the
dashboard is there, nothing to click 🎉

The API exposes at `/metrics`:

| Metric | What it tells you |
|--------|-------------------|
| `rl_requests_total{result}` | allowed vs throttled traffic |
| `rl_check_duration_seconds` | histogram of the limit check itself |
| `rl_redis_errors_total` | Redis failures while checking a limit |
| `rl_degraded_requests_total{policy}` | decisions made blind during an outage |

The dashboard has four headline tiles (allowed, throttled, throttled share,
p95) plus allowed-vs-throttled, per-instance traffic, latency percentiles and
Redis health.

📸 **For your README:** run `k6 run loadtest/load_test.js` with Grafana open
and screenshot the moment `allowed` flattens at the limit while `throttled`
climbs — that's the whole project in one picture.

💡 Each API process keeps its own counters, so Prometheus scrapes all three
instances and the queries sum across them. If you run one instance with
`uvicorn --workers N`, each worker has a separate registry and a scrape hits
only one of them — use one process per container instead.

⏱️ Measured cost of a limit check: **0.81ms average** (20ms across 25
requests), so metrics add no meaningful overhead.

---

## ☸️ Kubernetes

```bash
minikube start && minikube addons enable metrics-server
eval $(minikube docker-env) && docker build -t rate-limiter:1.0 .
kubectl apply -f k8s/
```

3 API pods + Redis + an HPA that scales 3 → 10 on CPU. `X-Instance` shows the
**pod name**, so you can watch requests land on different pods while the limit
still holds 🎯

💡 More pods raise how much traffic the API can **handle** — they do not raise
anyone's rate limit. The limit lives in Redis and is shared. Capacity scales,
permission doesn't.

📄 Full runbook, probe design and the reasoning:
**[k8s/README.md](k8s/README.md)**

---

## 📁 Layout

```
app/
├── main.py            # FastAPI app + rate limit middleware
├── config.py          # settings from environment variables
├── redis_client.py    # Redis connection
├── metrics.py         # Prometheus counters and histogram
└── limiter/
    ├── base.py            # Decision + RateLimiter interface
    ├── fixed_window.py    # INCR + EXPIRE
    ├── sliding_window.py  # sorted set + Lua script
    └── resilient.py       # fail-open / fail-closed when Redis is down
tests/                 # 32 tests
loadtest/              # k6 scripts + measured RESULTS.md
monitoring/            # prometheus.yml + provisioned Grafana dashboard
k8s/                   # Deployments, Services, ConfigMap, HPA
nginx/nginx.conf       # load balancer across the 3 instances
Dockerfile
docker-compose.yml     # redis + 3 api + nginx + prometheus + grafana
```
