#!/usr/bin/env bash
# Prepara o ambiente Python local para desenvolvimento e testes.
#
# Ubuntu 24.04 marca o Python do sistema como externally-managed (PEP 668)
# e recusa pip install fora de um venv. Isso e correto: dependencias do
# projeto nao devem se misturar com as do sistema operacional.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d .venv ]; then
  echo "criando .venv ..."
  python3 -m venv .venv
fi

# shellcheck disable=SC1091
source .venv/bin/activate

python3 -m pip install --quiet --upgrade pip
python3 -m pip install --quiet -e ".[dev]"

echo
echo "Ambiente pronto. Ative com:"
echo "  source .venv/bin/activate"
python3 -m pytest --version
