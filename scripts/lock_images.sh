#!/usr/bin/env bash
# Resolve tags moveis para digests imutaveis e grava em versions.lock.
# versions.lock E versionado no Git: e ele que garante reprodutibilidade.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$ROOT_DIR/versions.env"

LOCK="$ROOT_DIR/versions.lock"

resolve() {
  local ref="$1" var="$2" digest
  echo "resolvendo $ref ..." >&2
  docker pull --quiet "$ref" >/dev/null
  digest="$(docker inspect --format '{{index .RepoDigests 0}}' "$ref")"
  echo "${var}=${digest}"
}

{
  echo "# Gerado por scripts/lock_images.sh — nao editar a mao."
  echo "# Regenere com: make lock-images"
  resolve "${PG_IMAGE_REPO}:${PG_IMAGE_TAG}" "PG_IMAGE_DIGEST"
  resolve "${AIRFLOW_BASE_IMAGE}"            "AIRFLOW_BASE_DIGEST"
} > "$LOCK"

echo >&2
cat "$LOCK"
