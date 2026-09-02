#!/usr/bin/env python3
"""Demonstra falha controlada preservando a camada raw (secoes 13 e 22).

Dois cenarios, ambos reversiveis:

  A) Arquivo de origem ausente
     A validacao estrutural bloqueia antes de qualquer escrita no banco.
     Falha rapida, antes de a ingestao comecar.

  B) Valor invalido em staging
     A promocao aborta no cast. O rollback devolve inclusive os TRUNCATE,
     e a versao anterior de raw permanece intacta.

Uso:
    .venv/bin/python scripts/test_failure.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import psycopg2
import yaml

from banvic.contracts import load_contracts
from banvic.validation import validate_source

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_PATH = ROOT / "airflow" / "include" / "contracts" / "contracts.yml"
PROMOTION_SQL = ROOT / "sql" / "promotion" / "promote_raw.sql"
TABELAS = (
    "agencias",
    "clientes",
    "colaborador_agencia",
    "colaboradores",
    "contas",
    "propostas_credito",
    "transacoes",
)


def carregar_env() -> dict[str, str]:
    """Le o .env local em pares chave-valor."""
    arquivo = ROOT / ".env"
    if not arquivo.is_file():
        raise SystemExit(f"ERRO: {arquivo} nao encontrado")
    valores: dict[str, str] = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip()
    return valores


def conectar(env: dict[str, str]):
    """Abre conexao com o DW pelo NodePort."""
    return psycopg2.connect(
        host="localhost",
        port=15432,
        dbname=env["BANVIC_DW_DB"],
        user=env["BANVIC_DW_USER"],
        password=env["BANVIC_DW_PASSWORD"],
        connect_timeout=5,
    )


def contar_raw(env: dict[str, str]) -> dict[str, int]:
    """Contagem atual das sete tabelas em raw."""
    conn = conectar(env)
    try:
        with conn.cursor() as cur:
            resultado = {}
            for tabela in TABELAS:
                cur.execute(f'SELECT count(*) FROM raw."{tabela}"')  # noqa: S608
                resultado[tabela] = int(cur.fetchone()[0])
        return resultado
    finally:
        conn.close()


def cenario_a_arquivo_ausente(contracts) -> bool:
    """Move um arquivo de origem e confirma que a validacao bloqueia."""
    print("=" * 72)
    print("CENARIO A: arquivo de origem ausente")
    print("=" * 72)

    contrato = contracts.table("agencias")
    origem = ROOT / "data" / "incoming" / contrato.source_file

    if not origem.is_file():
        print(f"  fonte ja ausente: {origem}")
        return False

    with tempfile.TemporaryDirectory() as tmp:
        escondido = Path(tmp) / contrato.source_file
        shutil.move(str(origem), str(escondido))
        print(f"  arquivo temporariamente removido: {contrato.source_file}")

        try:
            relatorio = validate_source(contrato, origem)
            for r in relatorio.results:
                print(f"    [{r.status}] {r.check_name}: {r.details}")
            bloqueou = not relatorio.ok
        finally:
            shutil.move(str(escondido), str(origem))
            print(f"  arquivo restaurado: {contrato.source_file}")

    print(f"\n  validacao bloqueou a promocao: {bloqueou}")
    print("  nenhuma escrita no banco: a falha acontece antes da ingestao.\n")
    return bloqueou


def cenario_b_valor_invalido(env: dict[str, str]) -> bool:
    """Injeta um valor invalido em staging e confirma que raw sobrevive."""
    print("=" * 72)
    print("CENARIO B: valor invalido em staging, promocao deve abortar")
    print("=" * 72)

    antes = contar_raw(env)
    print("  contagens em raw ANTES:")
    for tabela, total in antes.items():
        print(f"    {tabela:<22}{total:>7}")

    conn = conectar(env)
    original = None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT data_abertura FROM staging.agencias WHERE cod_agencia = '1'"
            )
            linha = cur.fetchone()
            if not linha:
                print("\n  ERRO: staging vazio. Rode 'make meltano-run' antes.")
                return False
            original = linha[0]
            cur.execute(
                "UPDATE staging.agencias SET data_abertura = 'nao-e-uma-data' "
                "WHERE cod_agencia = '1'"
            )
        conn.commit()
        print(f"\n  valor invalido injetado (original: {original})")
    finally:
        conn.close()

    abortou = False
    conn = conectar(env)
    try:
        with conn.cursor() as cur:
            cur.execute(
                PROMOTION_SQL.read_text(encoding="utf-8"),
                {"run_id": "teste_falha_controlada", "pipeline_version": "0.0.0"},
            )
        conn.commit()
        print("  ATENCAO: a promocao NAO abortou. Isso e um problema.")
    except psycopg2.Error as exc:
        conn.rollback()
        abortou = True
        print(f"  promocao abortou como esperado: {str(exc).strip().splitlines()[0]}")
    finally:
        conn.close()

    conn = conectar(env)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE staging.agencias SET data_abertura = %s WHERE cod_agencia = '1'",
                (original,),
            )
        conn.commit()
        print(f"  staging restaurado (data_abertura = {original})")
    finally:
        conn.close()

    depois = contar_raw(env)
    print("\n  contagens em raw DEPOIS:")
    for tabela, total in depois.items():
        marca = "OK " if antes[tabela] == total else "MUDOU"
        print(f"    [{marca}] {tabela:<22}{total:>7}")

    intacta = antes == depois
    print(f"\n  raw preservada pelo rollback: {intacta}\n")
    return abortou and intacta


def main() -> int:
    """Roda os dois cenarios e resume o resultado."""
    env = carregar_env()
    contracts = load_contracts(CONTRACTS_PATH)

    with CONTRACTS_PATH.open(encoding="utf-8") as fh:
        yaml.safe_load(fh)  # valida o YAML antes de comecar

    a = cenario_a_arquivo_ausente(contracts)
    b = cenario_b_valor_invalido(env)

    print("=" * 72)
    print(f"  Cenario A (arquivo ausente bloqueia):        {'OK' if a else 'FALHOU'}")
    print(f"  Cenario B (rollback preserva raw):           {'OK' if b else 'FALHOU'}")
    print("=" * 72)
    return 0 if (a and b) else 1


if __name__ == "__main__":
    sys.exit(main())
