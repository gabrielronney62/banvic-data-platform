#!/usr/bin/env bash
# Executa a promocao atomica de staging para raw.
#
# Uso:
#   bash scripts/promote.sh [run_id]
#
# Sem argumento, gera um run_id local com prefixo manual_. Quando a DAG
# assumir esta etapa, o run_id vem do Airflow.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${K8S_NAMESPACE:-banvic}"
POD="banvic-postgres-0"

RUN_ID="${1:-manual_$(date -u +%Y%m%dT%H%M%SZ)}"
PIPELINE_VERSION="$(python3 -c "
import yaml
print(yaml.safe_load(open('$ROOT_DIR/airflow/include/contracts/contracts.yml'))['pipeline_version'])
")"

echo "run_id:           $RUN_ID"
echo "pipeline_version: $PIPELINE_VERSION"
echo

kubectl exec -i "$POD" -n "$NS" -- \
  sh -c "psql -v ON_ERROR_STOP=1 \
              -v run_id='$RUN_ID' \
              -v pipeline_version='$PIPELINE_VERSION' \
              -U \"\$POSTGRES_USER\" -d \"\$POSTGRES_DB\" -f -" \
  < "$ROOT_DIR/sql/promotion/promote_raw.sql"

echo
echo "Promocao concluida. Contagens em raw:"
kubectl exec -i "$POD" -n "$NS" -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' \
  < "$ROOT_DIR/sql/quality/raw_counts.sql"
