#!/usr/bin/env bash
# Aplica o DDL idempotente (ops e raw) no Data Warehouse.
#
# Separado do entrypoint da imagem PostgreSQL de proposito: aquele executa
# apenas na primeira inicializacao do volume, o que impediria evoluir o
# esquema sem destruir o banco. Aqui tudo usa IF NOT EXISTS e pode rodar
# quantas vezes for preciso.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NS="${K8S_NAMESPACE:-banvic}"
POD="banvic-postgres-0"

for arquivo in "$ROOT_DIR"/sql/ddl/*.sql; do
  echo "aplicando $(basename "$arquivo") ..."
  kubectl exec -i "$POD" -n "$NS" -- \
    sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' \
    < "$arquivo"
done

echo
echo "Estrutura resultante:"
kubectl exec -i "$POD" -n "$NS" -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT table_schema, table_name
  FROM information_schema.tables
 WHERE table_schema IN ('raw', 'ops')
 ORDER BY table_schema, table_name;
SQL
