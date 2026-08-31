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

required=(
  BANVIC_DW_DB BANVIC_DW_USER BANVIC_DW_PASSWORD
  AIRFLOW_METADATA_DB AIRFLOW_METADATA_USER AIRFLOW_METADATA_PASSWORD
  AIRFLOW_ADMIN_USER AIRFLOW_ADMIN_PASSWORD
)
for var in "${required[@]}"; do
  if [ -z "${!var:-}" ]; then
    echo "ERRO: variavel $var vazia no .env" >&2
    exit 1
  fi
  if [ "${!var}" = "troque-esta-senha" ]; then
    echo "ERRO: $var ainda e o placeholder do .env.example" >&2
    exit 1
  fi
done

apply_secret() {
  kubectl create secret generic "$1" --namespace "$NAMESPACE" \
    "${@:2}" --dry-run=client -o yaml | kubectl apply -f -
}

# Credenciais do Data Warehouse, consumidas pelo StatefulSet e pelo Meltano.
apply_secret banvic-dw-credentials \
  --from-literal=POSTGRES_DB="$BANVIC_DW_DB" \
  --from-literal=POSTGRES_USER="$BANVIC_DW_USER" \
  --from-literal=POSTGRES_PASSWORD="$BANVIC_DW_PASSWORD"

# Credenciais do banco de metadados, consumidas pelo StatefulSet do Airflow.
apply_secret airflow-metadata-credentials \
  --from-literal=POSTGRES_DB="$AIRFLOW_METADATA_DB" \
  --from-literal=POSTGRES_USER="$AIRFLOW_METADATA_USER" \
  --from-literal=POSTGRES_PASSWORD="$AIRFLOW_METADATA_PASSWORD"

# URI SQLAlchemy que o chart do Airflow espera na chave "connection".
METADATA_HOST="airflow-postgres.${NAMESPACE}.svc.cluster.local"
apply_secret airflow-metadata-connection \
  --from-literal=connection="postgresql://${AIRFLOW_METADATA_USER}:${AIRFLOW_METADATA_PASSWORD}@${METADATA_HOST}:5432/${AIRFLOW_METADATA_DB}"

# Conexao do Airflow com o Data Warehouse, exposta como AIRFLOW_CONN_*.
DW_HOST="banvic-postgres.${NAMESPACE}.svc.cluster.local"
apply_secret banvic-dw-connection \
  --from-literal=AIRFLOW_CONN_BANVIC_DW="postgresql://${BANVIC_DW_USER}:${BANVIC_DW_PASSWORD}@${DW_HOST}:5432/${BANVIC_DW_DB}"

# Usuario administrador da interface do Airflow.
apply_secret airflow-admin-credentials \
  --from-literal=username="$AIRFLOW_ADMIN_USER" \
  --from-literal=password="$AIRFLOW_ADMIN_PASSWORD"

echo
echo "Secrets no namespace ${NAMESPACE} (valores nunca exibidos):"
kubectl get secrets -n "$NAMESPACE" \
  --field-selector type=Opaque \
  -o custom-columns=NOME:.metadata.name,CHAVES:.data --no-headers 2>/dev/null \
  | sed 's/map\[/ /; s/\]//' || kubectl get secrets -n "$NAMESPACE"
