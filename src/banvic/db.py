"""Persistencia das tabelas operacionais (schema ops).

Isola o SQL de auditoria e qualidade num modulo testavel, para que a DAG
fique com orquestracao e nao com string de SQL espalhada por task.

Todas as funcoes recebem uma conexao ja aberta e nao fazem commit: quem
controla a transacao e o chamador. Isso permite que a promocao e o registro
de metricas compartilhem a mesma transacao quando isso for desejavel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from banvic.contracts import Contracts, TableContract
from banvic.validation import CheckResult


class Connection(Protocol):
    """Interface minima de uma conexao DB-API 2.0."""

    def cursor(self) -> Any:  # noqa: D102
        ...


@dataclass(frozen=True)
class TableMetrics:
    """Metricas de ingestao de uma tabela numa execucao."""

    table_name: str
    source_file: str
    source_checksum: str
    row_count_source: int
    row_count_staging: int | None = None
    row_count_raw: int | None = None
    status: str = "SUCCESS"
    error_message: str | None = None


def start_run(
    conn: Connection, run_id: str, dag_id: str, pipeline_version: str
) -> None:
    """Registra o inicio de uma execucao em ops.pipeline_runs.

    Idempotente por run_id: reexecutar uma task no Airflow nao deve quebrar
    por chave duplicada.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.pipeline_runs (run_id, dag_id, pipeline_version, status)
                 VALUES (%(run_id)s, %(dag_id)s, %(version)s, 'RUNNING')
            ON CONFLICT (run_id) DO UPDATE
                    SET started_at = now(),
                        status = 'RUNNING',
                        finished_at = NULL,
                        error_message = NULL
            """,
            {"run_id": run_id, "dag_id": dag_id, "version": pipeline_version},
        )


def finish_run(
    conn: Connection, run_id: str, status: str, error_message: str | None = None
) -> None:
    """Fecha uma execucao em ops.pipeline_runs."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ops.pipeline_runs
               SET finished_at = now(),
                   status = %(status)s,
                   error_message = %(error)s
             WHERE run_id = %(run_id)s
            """,
            {"run_id": run_id, "status": status, "error": error_message},
        )


def record_table_metrics(
    conn: Connection, run_id: str, metrics: TableMetrics
) -> None:
    """Grava ou atualiza as metricas de uma tabela em ops.pipeline_table_metrics."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ops.pipeline_table_metrics (
                       run_id, table_name, source_file, source_checksum,
                       row_count_source, row_count_staging, row_count_raw,
                       finished_at, status, error_message)
                VALUES (%(run_id)s, %(table)s, %(file)s, %(checksum)s,
                       %(src)s, %(stg)s, %(raw)s, now(), %(status)s, %(error)s)
            ON CONFLICT (run_id, table_name) DO UPDATE
                   -- NULLIF + COALESCE: as etapas seguintes do pipeline
                   -- reescrevem a linha para acrescentar as contagens de
                   -- staging e raw, mas nao recalculam o checksum. Sem isso,
                   -- a string vazia que elas enviam apagaria o valor gravado
                   -- por audit_sources.
                   SET source_file      = COALESCE(NULLIF(EXCLUDED.source_file, ''),
                                                   ops.pipeline_table_metrics.source_file),
                       source_checksum  = COALESCE(NULLIF(EXCLUDED.source_checksum, ''),
                                                   ops.pipeline_table_metrics.source_checksum),
                       row_count_source = EXCLUDED.row_count_source,
                       row_count_staging = COALESCE(EXCLUDED.row_count_staging,
                                                    ops.pipeline_table_metrics.row_count_staging),
                       row_count_raw    = COALESCE(EXCLUDED.row_count_raw,
                                                    ops.pipeline_table_metrics.row_count_raw),
                       finished_at      = now(),
                       status           = EXCLUDED.status,
                       error_message    = EXCLUDED.error_message
            """,
            {
                "run_id": run_id,
                "table": metrics.table_name,
                "file": metrics.source_file,
                "checksum": metrics.source_checksum,
                "src": metrics.row_count_source,
                "stg": metrics.row_count_staging,
                "raw": metrics.row_count_raw,
                "status": metrics.status,
                "error": metrics.error_message,
            },
        )


def record_check_results(
    conn: Connection, run_id: str, results: list[CheckResult]
) -> None:
    """Grava resultados de Data Quality em ops.data_quality_results."""
    if not results:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ops.data_quality_results (
                        run_id, table_name, check_name, severity,
                        status, invalid_rows, details)
                 VALUES (%(run_id)s, %(table)s, %(check)s, %(severity)s,
                        %(status)s, %(invalid)s, %(details)s)
            """,
            [
                {
                    "run_id": run_id,
                    "table": r.table_name,
                    "check": r.check_name,
                    "severity": r.severity,
                    "status": r.status,
                    "invalid": r.invalid_rows,
                    "details": r.details or None,
                }
                for r in results
            ],
        )


def count_rows(conn: Connection, schema: str, table: str) -> int:
    """Conta registros de uma tabela.

    O nome vem dos contratos, nunca de entrada externa, mas ainda assim
    validamos o formato antes de interpolar: nomes de objeto nao podem ser
    passados como parametro em SQL.
    """
    if not _is_safe_identifier(schema) or not _is_safe_identifier(table):
        raise ValueError(f"identificador invalido: {schema}.{table}")
    with conn.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{schema}"."{table}"')  # noqa: S608
        return int(cur.fetchone()[0])


def count_distinct_key(
    conn: Connection, schema: str, table: str, key: tuple[str, ...]
) -> int:
    """Conta chaves primarias distintas de uma tabela."""
    for ident in (schema, table, *key):
        if not _is_safe_identifier(ident):
            raise ValueError(f"identificador invalido: {ident}")
    colunas = ", ".join(f'"{c}"' for c in key)
    with conn.cursor() as cur:
        cur.execute(
            f'SELECT count(*) FROM (SELECT DISTINCT {colunas} '  # noqa: S608
            f'FROM "{schema}"."{table}") AS chaves'
        )
        return int(cur.fetchone()[0])


def check_foreign_keys(
    conn: Connection, contracts: Contracts, schema: str = "staging"
) -> list[CheckResult]:
    """Verifica os relacionamentos declarados nos contratos.

    A severidade vem do contrato, nao de regra codificada aqui. E por isso
    que o cod_cliente 528 gera WARN em vez de FAIL: o contrato declara que
    aquele relacionamento e conhecido como imperfeito na origem (secao 7).
    """
    resultados: list[CheckResult] = []

    for contrato in contracts.tables:
        for rel in contrato.relationships:
            invalidas, amostra = _count_orphans(
                conn, schema, contrato, rel.column, rel.parent_table, rel.parent_column
            )
            nome = f"fk_{contrato.table}_{rel.parent_table}"

            if invalidas == 0:
                status = "PASS"
                detalhe = f"{rel.column} -> {rel.parent_table}.{rel.parent_column}"
            elif rel.severity == "WARN":
                status = "WARN"
                detalhe = (
                    f"{rel.column} -> {rel.parent_table}.{rel.parent_column}; "
                    f"valores orfaos: {amostra}. Inconsistencia conhecida da "
                    f"origem, preservada de proposito."
                )
            else:
                status = "FAIL"
                detalhe = (
                    f"{rel.column} -> {rel.parent_table}.{rel.parent_column}; "
                    f"valores orfaos: {amostra}"
                )

            resultados.append(
                CheckResult(
                    table_name=contrato.table,
                    check_name=nome,
                    severity=rel.severity,
                    status=status,
                    invalid_rows=invalidas,
                    details=detalhe,
                )
            )

    return resultados


def _count_orphans(
    conn: Connection,
    schema: str,
    contrato: TableContract,
    coluna: str,
    tabela_pai: str,
    coluna_pai: str,
) -> tuple[int, list[str]]:
    """Conta linhas cuja FK nao existe na tabela pai, com amostra de valores."""
    for ident in (schema, contrato.table, coluna, tabela_pai, coluna_pai):
        if not _is_safe_identifier(ident):
            raise ValueError(f"identificador invalido: {ident}")

    sql = (
        f'SELECT f."{coluna}"::text, count(*) '  # noqa: S608
        f'FROM "{schema}"."{contrato.table}" AS f '
        f'LEFT JOIN "{schema}"."{tabela_pai}" AS p '
        f'ON f."{coluna}"::text = p."{coluna_pai}"::text '
        f'WHERE p."{coluna_pai}" IS NULL '
        f'GROUP BY 1 ORDER BY 2 DESC LIMIT 10'
    )
    with conn.cursor() as cur:
        cur.execute(sql)
        linhas = cur.fetchall()

    total = sum(int(n) for _, n in linhas)
    amostra = [str(v) for v, _ in linhas[:5]]
    return total, amostra


def _is_safe_identifier(nome: str) -> bool:
    """Aceita apenas identificadores simples, sem aspas nem espacos."""
    return bool(nome) and all(c.isalnum() or c == "_" for c in nome)
