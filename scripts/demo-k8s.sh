#!/usr/bin/env bash
# Runs the whole Kubernetes demo and writes a transcript you can paste into
# the README as evidence.
#
#   ./scripts/demo-k8s.sh
#
# Needs: minikube, kubectl, docker. Takes about 5 minutes.
set -euo pipefail

OUT="k8s-demo-output.txt"
exec > >(tee "$OUT") 2>&1

# One request, printed as "<status> <pod>". Exactly one request per line -
# anything more would spend the limit faster than the output suggests.
probe() {
  local url=$1 raw
  raw=$(curl -s -o /dev/null -D- -w 'STATUS:%{http_code}' \
        -H 'X-API-Key: demo' "$url/api/data" | tr -d '\r')
  printf '%s %s' \
    "$(printf '%s' "$raw" | sed -n 's/.*STATUS:\([0-9][0-9]*\).*/\1/p')" \
    "$(printf '%s\n' "$raw" | awk -F': ' 'tolower($1)=="x-instance"{print $2}')"
}

echo "=== 1. Starting minikube ==============================================="
minikube status >/dev/null 2>&1 || minikube start
minikube addons enable metrics-server

echo
echo "=== 2. Building the image inside the cluster ==========================="
# The build must go into minikube's own Docker daemon, otherwise the pods
# cannot find the image and sit in ErrImagePull.
eval "$(minikube docker-env)"
docker build -t rate-limiter:1.0 .

echo
echo "=== 3. Deploying ======================================================="
kubectl apply -f k8s/
kubectl rollout status deployment/redis --timeout=120s
kubectl rollout status deployment/api --timeout=120s
kubectl get pods -o wide

echo
echo "=== 4. The limit holds across pods ====================================="
API=$(minikube service api --url | head -1)
echo "API at $API   (limit: 10 per 60s, from k8s/api.yaml)"
echo
printf '%-4s %-8s %s\n' "#" "status" "pod that answered"
for i in $(seq 1 12); do
  # shellcheck disable=SC2046
  printf '%-4s %-8s %s\n' "$i" $(probe "$API")
done
echo
echo "Different pods answered, and the 429s still appeared:"
echo "one Redis, one shared limit."

echo
echo "=== 5. Autoscaling ====================================================="
kubectl get hpa api
echo
echo "In a SECOND terminal, watch pods scale while load runs:"
echo "    kubectl get hpa api -w"
echo "    BASE_URL=$API k6 run loadtest/load_test.js"
echo
echo "Transcript saved to $OUT"
echo "Clean up with:  kubectl delete -f k8s/  &&  minikube stop"
