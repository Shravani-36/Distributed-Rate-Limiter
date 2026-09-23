#!/usr/bin/env bash
# Brings up the full stack and drives traffic through it, so the Grafana
# dashboard has something worth screenshotting.
#
#   ./scripts/demo-load.sh            # 2 minutes of load
#   DURATION=300 ./scripts/demo-load.sh
#
# Needs: docker compose. Uses k6 if installed, otherwise plain curl.
set -euo pipefail

DURATION=${DURATION:-120}
BASE_URL=${BASE_URL:-http://localhost:8080}

echo "=== Starting the stack ==============================================="
docker compose up --build -d

echo -n "waiting for the API"
for _ in $(seq 1 60); do
  if curl -sf "$BASE_URL/health" >/dev/null 2>&1; then break; fi
  echo -n "."
  sleep 1
done
echo " ready"

cat <<EOF

=== Open Grafana now ==================================================
  📈 http://localhost:3000   (the dashboard is already provisioned)
  🔍 http://localhost:9090   (Prometheus, if you want to check targets)

Traffic starts in 10 seconds and runs for ${DURATION}s.
EOF
sleep 10

echo "=== Generating load =================================================="
if command -v k6 >/dev/null 2>&1; then
  K6_NO_USAGE_REPORT=true BASE_URL="$BASE_URL" \
    k6 run --stage "20s:25" --stage "$((DURATION - 30))s:100" --stage "10s:0" \
    loadtest/load_test.js
else
  echo "(k6 not installed - using curl instead)"
  end=$((SECONDS + DURATION))
  while [ $SECONDS -lt $end ]; do
    # 20 keys in parallel: some stay under their limit, some blow through it,
    # so the dashboard shows both allowed and throttled traffic.
    seq 1 20 | xargs -P 20 -I{} curl -s -o /dev/null \
      -H "X-API-Key: user{}" "$BASE_URL/api/data" || true
  done
fi

cat <<'EOF'

=== Screenshot these =================================================
  1. The four tiles at the top  (allowed / throttled / share / p95)
  2. "Allowed vs throttled"     <- the money shot: allowed flattens at the
                                   limit while throttled climbs
  3. "Requests per instance"    <- proof all 3 instances served traffic

Set the time range to "Last 15 minutes" so the load is visible.
Save them into docs/images/ and link them from the README.

Stop everything with:  docker compose down
EOF
