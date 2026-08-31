#!/usr/bin/env bash
# Cria os Secrets do Kubernetes a partir do .env local.
#
# O Terraform NAO gerencia estes Secrets de proposito: valores gerenciados
# por Terraform ficam em texto plano no terraform.tfstate. Aqui o segredo
# so existe no etcd do cluster e no .env local, ambos fora do Git.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"
NAMESPACE="${K8S_NAMESPACE:-banvic}"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERRO: $ENV_FILE nao encontrado. Copie de .env.example e preencha." >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

for var in BANVIC_DW_DB BANVIC_DW_USER BANVIC_DW_PASSWORD; do
  if [ -z "${!var:-}" ]; then
    echo "ERRO: variavel $var vazia no .env" >&2
    exit 1
  fi
done

if [ "$BANVIC_DW_PASSWORD" = "troque-esta-senha" ]; then
  echo "ERRO: senha do DW ainda e o placeholder do .env.example" >&2
  exit 1
fi

kubectl create secret generic banvic-dw-credentials \
  --namespace "$NAMESPACE" \
  --from-literal=POSTGRES_DB="$BANVIC_DW_DB" \
  --from-literal=POSTGRES_USER="$BANVIC_DW_USER" \
  --from-literal=POSTGRES_PASSWORD="$BANVIC_DW_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

echo
echo "Secret aplicado. Chaves presentes (valores nao exibidos):"
kubectl get secret banvic-dw-credentials -n "$NAMESPACE" \
  -o jsonpath='{range .data.*}{"  "}{@}{"\n"}{end}' >/dev/null 2>&1 || true
kubectl describe secret banvic-dw-credentials -n "$NAMESPACE" | tail -6
