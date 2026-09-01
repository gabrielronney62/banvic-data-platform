#!/usr/bin/env bash
# Verifica se a plataforma esta operacional. Rode apos reiniciar a maquina.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${K8S_NAMESPACE:-banvic}"
FALHA=0

ok()  { printf '  [ OK ]   %s\n' "$1"; }
bad() { printf '  [FAIL]   %s\n' "$1"; FALHA=1; }

echo "=== Ponte de dados ==="
n_host=$(ls -1 "$ROOT_DIR"/data/incoming/*.csv 2>/dev/null | wc -l)
[ "$n_host" -eq 7 ] && ok "host: 7 CSVs em data/incoming" \
                    || bad "host: $n_host CSVs (esperado 7)"

n_node=$(docker exec banvic-control-plane ls -1 /data/incoming 2>/dev/null | grep -c '\.csv$')
[ "${n_node:-0}" -eq 7 ] && ok "no do Kind: 7 CSVs em /data/incoming" \
                      || bad "no do Kind: ${n_node:-0} CSVs. extraMounts quebrou; rode make rebuild."

echo
echo "=== Cluster ==="
kubectl get nodes >/dev/null 2>&1 && ok "API do Kubernetes responde" || bad "cluster inacessivel"

pend=$(kubectl get pvc -n "$NS" --no-headers 2>/dev/null | grep -vc Bound)
[ "${pend:-0}" -eq 0 ] && ok "todos os PVCs Bound" || bad "${pend} PVC(s) fora de Bound"

nr=$(kubectl get pods -n "$NS" --no-headers 2>/dev/null | grep -vcE 'Running|Completed')
[ "${nr:-0}" -eq 0 ] && ok "todos os pods Running ou Completed" || bad "${nr} pod(s) em estado anormal"

echo
echo "=== Imagem do Meltano ==="
docker exec banvic-control-plane crictl images 2>/dev/null | grep -q banvic-meltano \
  && ok "banvic-meltano presente no no" \
  || bad "banvic-meltano ausente. Rode: make meltano-build"

echo
[ "$FALHA" -eq 0 ] && echo "Plataforma operacional." || echo "Plataforma com problemas."
exit "$FALHA"
