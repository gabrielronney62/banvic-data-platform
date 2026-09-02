"""Testes do modulo banvic.db.

Usam uma conexao falsa que registra o SQL executado, sem precisar de banco.
O objetivo e garantir que a montagem de SQL e a decisao de severidade
estejam corretas; a integracao real com PostgreSQL fica nos testes marcados
com `integration`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from banvic.contracts import load_contracts
from banvic.db import (
    TableMetrics,
    _is_safe_identifier,
    check_foreign_keys,
    count_distinct_key,
    count_rows,
    finish_run,
    record_check_results,
    record_table_metrics,
    start_run,
)
from banvic.validation import CheckResult

FIXTURES = Path(__file__).parent.parent / "fixtures"


class FakeCursor:
    """Cursor falso que guarda as chamadas e devolve valores programados."""

    def __init__(self, resultados: list) -> None:
        self.resultados = list(resultados)
        self.executadas: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        self.executadas.append((sql, params))

    def executemany(self, sql, seq):
        self.executadas.append((sql, list(seq)))

    def fetchone(self):
        return self.resultados.pop(0) if self.resultados else (0,)

    def fetchall(self):
        return self.resultados.pop(0) if self.resultados else []


class FakeConn:
    """Conexao falsa que devolve sempre o mesmo cursor."""

    def __init__(self, resultados: list | None = None) -> None:
        self._cursor = FakeCursor(resultados or [])

    def cursor(self):
        return self._cursor

    @property
    def executadas(self):
        return self._cursor.executadas


# ------------------------------------------------------- identificadores


@pytest.mark.parametrize("nome", ["raw", "staging", "cod_cliente", "tabela_1"])
def test_identificador_valido(nome):
    assert _is_safe_identifier(nome)


@pytest.mark.parametrize(
    "nome", ["", 'a"; DROP TABLE x', "com espaco", "traco-no-meio", "aspas'"]
)
def test_identificador_invalido(nome):
    assert not _is_safe_identifier(nome)


def test_count_rows_recusa_identificador_perigoso():
    conn = FakeConn()
    with pytest.raises(ValueError, match="identificador invalido"):
        count_rows(conn, "raw", 'clientes"; DROP TABLE raw.clientes; --')


def test_count_distinct_key_recusa_coluna_perigosa():
    conn = FakeConn()
    with pytest.raises(ValueError, match="identificador invalido"):
        count_distinct_key(conn, "raw", "clientes", ("cod; DROP",))


# --------------------------------------------------------------- contagens


def test_count_rows_monta_sql_com_aspas():
    conn = FakeConn([(998,)])
    assert count_rows(conn, "raw", "clientes") == 998
    sql, _ = conn.executadas[0]
    assert '"raw"."clientes"' in sql


def test_count_distinct_key_com_pk_composta():
    conn = FakeConn([(100,)])
    total = count_distinct_key(conn, "raw", "colaborador_agencia",
                               ("cod_colaborador", "cod_agencia"))
    assert total == 100
    sql, _ = conn.executadas[0]
    assert '"cod_colaborador", "cod_agencia"' in sql


# ------------------------------------------------------------------- ops


def test_start_run_usa_on_conflict():
    conn = FakeConn()
    start_run(conn, "run_1", "banvic_ingestion", "0.1.0")
    sql, params = conn.executadas[0]
    assert "ON CONFLICT (run_id)" in sql
    assert params["run_id"] == "run_1"


def test_finish_run_grava_status():
    conn = FakeConn()
    finish_run(conn, "run_1", "FAILED", "erro X")
    sql, params = conn.executadas[0]
    assert "UPDATE ops.pipeline_runs" in sql
    assert params["status"] == "FAILED"
    assert params["error"] == "erro X"


def test_record_table_metrics_preserva_contagens_anteriores():
    conn = FakeConn()
    record_table_metrics(
        conn, "run_1",
        TableMetrics("clientes", "clientes.csv", "abc", 998, row_count_staging=998),
    )
    sql, params = conn.executadas[0]
    assert "ON CONFLICT (run_id, table_name)" in sql
    assert "COALESCE" in sql
    assert params["checksum"] == "abc"


def test_record_check_results_vazio_nao_executa_sql():
    conn = FakeConn()
    record_check_results(conn, "run_1", [])
    assert conn.executadas == []


def test_record_check_results_grava_todos():
    conn = FakeConn()
    resultados = [
        CheckResult("clientes", "pk_unique", "CRITICAL", "PASS"),
        CheckResult("contas", "fk_clientes", "WARN", "WARN", 1, "528"),
    ]
    record_check_results(conn, "run_1", resultados)
    _, linhas = conn.executadas[0]
    assert len(linhas) == 2
    assert linhas[1]["severity"] == "WARN"


# -------------------------------------------------------- foreign keys


@pytest.fixture
def contratos():
    return load_contracts(FIXTURES / "contracts_teste.yml")


def test_fk_sem_orfaos_passa(contratos):
    conn = FakeConn([[]])
    resultados = check_foreign_keys(conn, contratos, schema="staging")
    assert len(resultados) == 1
    assert resultados[0].status == "PASS"
    assert resultados[0].invalid_rows == 0


def test_fk_com_orfaos_e_severidade_warn_nao_bloqueia(contratos):
    # contas.cod_cliente -> clientes.cod_cliente esta declarado como WARN,
    # que e o caso do cod_cliente 528 da secao 7.
    conn = FakeConn([[("528", 1)]])
    resultados = check_foreign_keys(conn, contratos, schema="staging")
    r = resultados[0]
    assert r.severity == "WARN"
    assert r.status == "WARN"
    assert r.invalid_rows == 1
    assert "528" in r.details
    assert not r.blocks_promotion


def test_severidade_vem_do_contrato_nao_do_codigo(contratos):
    rel = contratos.table("contas").relationships[0]
    assert rel.severity == "WARN"
    conn = FakeConn([[("999", 3)]])
    resultado = check_foreign_keys(conn, contratos, schema="staging")[0]
    assert resultado.severity == rel.severity


def test_sql_de_promocao_so_tem_marcadores_conhecidos():
    """O psycopg2 varre a string inteira, inclusive comentarios.

    Um `%(algo)s` escrito num comentario vira parametro esperado e quebra a
    execucao com KeyError. Este teste impede a recorrencia.
    """
    import re

    sql = (Path(__file__).parent.parent.parent
           / "sql" / "promotion" / "promote_raw.sql").read_text(encoding="utf-8")
    marcadores = set(re.findall(r"%\((\w+)\)s", sql))
    assert marcadores == {"run_id", "pipeline_version"}, marcadores


def test_metrics_preserva_checksum_quando_reescrita():
    """Etapas posteriores reescrevem a linha sem recalcular o checksum.

    audit_sources grava o SHA-256; validate_staging e validate_raw so
    acrescentam contagens. O UPSERT nao pode apagar o checksum com a string
    vazia que essas etapas enviam.
    """
    conn = FakeConn()
    record_table_metrics(
        conn, "run_1",
        TableMetrics("clientes", "clientes.csv", "", 998, row_count_raw=998),
    )
    sql, _ = conn.executadas[0]
    assert "NULLIF(EXCLUDED.source_checksum, '')" in sql
    assert "NULLIF(EXCLUDED.source_file, '')" in sql
