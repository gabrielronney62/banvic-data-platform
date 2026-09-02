#!/usr/bin/env python3
"""Executa a promocao de staging para raw fora do Airflow.

Usa exatamente o mesmo arquivo SQL que a DAG, para nao existirem duas
versoes da promocao divergindo com o tempo. Serve para depurar e para
demonstrar a atomicidade sem depender de uma execucao completa da DAG.

Uso:
    .venv/bin/python scripts/promote.py [run_id]

Conecta pelo NodePort exposto em localhost:15432, usando as credenciais
do .env local.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg2
import yaml

ROOT = Path(__file__).resolve().parent.parent
SQL_PATH = ROOT / "sql" / "promotion" / "promote_raw.sql"
CONTRACTS_PATH = ROOT / "airflow" / "include" / "contracts" / "contracts.yml"


def carregar_env(caminho: Path) -> dict[str, str]:
    """Le um arquivo .env simples em pares chave=valor."""
    if not caminho.is_file():
        raise SystemExit(f"ERRO: {caminho} nao encontrado")
    valores: dict[str, str] = {}
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip()
    return valores


def main() -> int:
    """Roda a promocao numa unica transacao."""
    env = carregar_env(ROOT / ".env")
    run_id = sys.argv[1] if len(sys.argv) > 1 else f"manual_{os.getpid()}"

    with CONTRACTS_PATH.open(encoding="utf-8") as fh:
        pipeline_version = yaml.safe_load(fh).get("pipeline_version", "0.0.0")

    print(f"run_id:           {run_id}")
    print(f"pipeline_version: {pipeline_version}\n")

    sql = SQL_PATH.read_text(encoding="utf-8")

    conn = psycopg2.connect(
        host="localhost",
        port=15432,
        dbname=env["BANVIC_DW_DB"],
        user=env["BANVIC_DW_USER"],
        password=env["BANVIC_DW_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, {"run_id": run_id, "pipeline_version": pipeline_version})
        conn.commit()
        print("Promocao concluida.\n")
    except psycopg2.Error as exc:
        conn.rollback()
        print(f"ERRO: {exc}", file=sys.stderr)
        print("Rollback aplicado: a versao anterior de raw esta intacta.", file=sys.stderr)
        return 1
    finally:
        conn.close()

    conn = psycopg2.connect(
        host="localhost",
        port=15432,
        dbname=env["BANVIC_DW_DB"],
        user=env["BANVIC_DW_USER"],
        password=env["BANVIC_DW_PASSWORD"],
    )
    try:
        with conn.cursor() as cur:
            cur.execute((ROOT / "sql" / "quality" / "raw_counts.sql").read_text())
            print(f"{'tabela':<22}{'linhas':>8}{'pks':>8}")
            for tabela, linhas, pks in cur.fetchall():
                print(f"{tabela:<22}{linhas:>8}{pks:>8}")
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
