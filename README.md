# 🚦 Distributed Rate Limiter

[![CI](https://github.com/shravani-36/distributed-rate-limiter/actions/workflows/ci.yml/badge.svg)](https://github.com/shravani-36/distributed-rate-limiter/actions/workflows/ci.yml)

API rate limiting that holds **across every server**, not once per server.

> Run your API on 3 instances with an in-memory limiter and "10 per minute"
> quietly becomes 30 per minute — each instance counts alone.
> This keeps the count in **Redis**, so the limit is shared.

**FastAPI · Redis · Docker · Kubernetes · Prometheus · Grafana · k6**

---

## 🏗️ How it works

```
   client ──▶ Nginx ──┬──▶ API 1 ──┐
                      ├──▶ API 2 ──┼──▶ Redis   ONE counter
                      └──▶ API 3 ──┘            = ONE limit
```

Each request runs an **atomic Lua script** in Redis: drop timestamps older
than the window, count what's left, admit or reject. Because the script runs
inside Redis, two instances can never both spend the same last slot ⚛️

---

## 🐳 Run it

```bash
docker compose up --build
```

| | |
|---|---|
| 🚦 API | http://localhost:8080 |
| 📈 Grafana | http://localhost:3000 |
| 🔍 Prometheus | http://localhost:9090 |

```bash
for i in $(seq 1 12); do
  curl -s -o /dev/null -w "%{http_code} " -H "X-API-Key: user1" localhost:8080/api/data
done
# 200 200 200 200 200 200 200 200 200 200 429 429
```

Requests land on **different instances** (see the `X-Instance` header) and the
limit still holds 🎯

```bash
./scripts/demo-load.sh    # drives traffic so the Grafana dashboard fills up
```

---

## 📊 Results

k6, 100 virtual users, 3 instances, limit 50/min/key:

| | |
|---|---|
| Throughput | **3,908 req/s** |
| Latency | **p95 27ms** · p99 45ms |
| Failures | **0.00%** |
| Allowed | **exactly 5,000** (100 keys × 50) |

Under 60-way concurrency on a single key it admits **exactly** the limit — no
overshoot. 📄 [Full results](loadtest/RESULTS.md)

---

## ⚙️ Config

| Variable | Default | |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | shared state |
| `RATE_LIMIT` | `10` | requests per window |
| `WINDOW_SECONDS` | `60` | window length |
| `ALGORITHM` | `sliding` | or `fixed` |
| `FAIL_OPEN` | `true` | behaviour when Redis is down |

Responses carry `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`
and `X-Instance`.

---

## 🧠 Design decisions

**Sliding window over fixed window.** A fixed window lets a client send the
full limit at `0:59` and again at `1:01` — double the limit in two seconds.
A load test caught exactly that: fixed allowed **10,000** where sliding
allowed **5,000**.

**Redis down → you choose.** During an outage there's no way to know if a
client is over its limit, so the policy is explicit: `FAIL_OPEN=true` keeps
serving (availability), `false` returns 429 (correctness). Either way it's
logged, counted, and flagged with `X-RateLimit-Degraded`.

**Liveness ≠ readiness.** Readiness uses `/health`; liveness is a TCP check.
A liveness probe on `/health` would restart every pod in a loop whenever
Redis blipped.

---

## 🧪 Tests

```bash
pytest        # 32 tests, no Redis needed (fakeredis)
```

CI also runs ruff, an integration job against a **real** Redis, a Docker
build, and strict validation of the Kubernetes manifests.

---

## ☸️ Kubernetes

```bash
eval $(minikube docker-env) && docker build -t rate-limiter:1.0 .
kubectl apply -f k8s/
```

3 pods + Redis + autoscaling 3 → 10 on CPU.
Or run `./scripts/demo-k8s.sh` to do the whole demo and save a transcript.
📄 [Runbook](k8s/README.md)

💡 More pods raise how much traffic the API can **handle** — not anyone's
rate limit. Capacity scales, permission doesn't.

---

## 📁 Layout

```
app/main.py      FastAPI + rate limit middleware
app/limiter/     fixed_window · sliding_window (Lua) · resilient
tests/           32 tests
loadtest/        k6 scripts + measured results
monitoring/      Prometheus config + provisioned Grafana dashboard
k8s/             Deployments, Service, ConfigMap, HPA
```

---

## ⚖️ Known limits

Redis is a single point of failure (real HA needs Sentinel or Cluster) · the
sliding window stores one entry per request in the window · single region ·
API keys come from the header and aren't authenticated.

**Next:** token bucket for controlled bursts, per-plan limits, Redis Sentinel.

📚 Step-by-step build notes: [ROADMAP.md](ROADMAP.md)
