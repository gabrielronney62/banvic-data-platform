#!/usr/bin/env bash
# Prova que executar a ingestao duas vezes nao altera as contagens.
# Requisito da secao 12 do desafio.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${K8S_NAMESPACE:-banvic}"

contar() {
  kubectl exec -i banvic-postgres-0 -n "$NAMESPACE" -- \
    sh -c 'psql -tA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' \
    < "$ROOT_DIR/sql/quality/staging_counts.sql"
}

executar() {
  kubectl delete job meltano-carga-inicial -n "$NAMESPACE" --ignore-not-found >/dev/null
  kubectl apply -f "$ROOT_DIR/meltano/k8s/job-carga-standalone.yaml" >/dev/null
  kubectl wait --for=condition=complete --timeout=10m \
    job/meltano-carga-inicial -n "$NAMESPACE" >/dev/null
}

echo "Execucao 1 de 2..."
executar
PRIMEIRA="$(contar)"
echo "$PRIMEIRA"

echo
echo "Execucao 2 de 2..."
executar
SEGUNDA="$(contar)"
echo "$SEGUNDA"

echo
if [ "$PRIMEIRA" = "$SEGUNDA" ]; then
  echo "IDEMPOTENCIA: OK -- contagens identicas nas duas execucoes."
  exit 0
fi

echo "IDEMPOTENCIA: FALHOU -- as contagens divergem." >&2
diff <(echo "$PRIMEIRA") <(echo "$SEGUNDA") >&2 || true
exit 1
