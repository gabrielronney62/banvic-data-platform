#!/usr/bin/env bash
# Instala ou atualiza o Airflow via Helm.
#
# A senha do admin vem do .env e e passada por --set, jamais do values.yaml
# versionado. Ela fica apenas no Secret do release, dentro do cluster.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/versions.env"
NAMESPACE="${K8S_NAMESPACE:-banvic}"
CHART="${AIRFLOW_CHART_REPO_NAME:-apache-airflow}/${AIRFLOW_CHART_NAME}"

if [ ! -f "$ROOT_DIR/.env" ]; then
  echo "ERRO: .env nao encontrado." >&2
  exit 1
fi
# shellcheck disable=SC1091
set -a; source "$ROOT_DIR/.env"; set +a

for var in AIRFLOW_ADMIN_USER AIRFLOW_ADMIN_PASSWORD; do
  if [ -z "${!var:-}" ] || [ "${!var}" = "troque-esta-senha" ]; then
    echo "ERRO: $var ausente ou ainda no placeholder." >&2
    exit 1
  fi
done

# Os --set precisam ser identicos na validacao e na instalacao.
# Validar apenas o values.yaml nao cobre o que de fato sera aplicado.
HELM_ARGS=(
  --version "$AIRFLOW_CHART_VERSION"
  --namespace "$NAMESPACE"
  --values "$ROOT_DIR/infra/helm/airflow-values.yaml"
  --set "createUserJob.defaultUser.username=${AIRFLOW_ADMIN_USER}"
  --set "createUserJob.defaultUser.password=${AIRFLOW_ADMIN_PASSWORD}"
)

echo "Validando values e overrides contra o schema do chart..."
helm template airflow "$CHART" "${HELM_ARGS[@]}" > /dev/null
echo "Validacao OK."
echo

# --no-hooks nao: precisamos dos jobs. Mas o NOTES.txt do chart imprime a
# senha do admin em texto plano, o que a deixaria no historico do shell.
helm upgrade --install airflow "$CHART" "${HELM_ARGS[@]}" \
  --timeout 15m \
  --wait > /dev/null

echo "Release aplicado. Credenciais estao no .env, nao exibidas aqui." 

echo
helm status airflow -n "$NAMESPACE" | head -8
