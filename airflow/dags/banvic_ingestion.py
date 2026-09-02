"""DAG de ingestao do ERP BanVic: CSV -> staging -> raw.

Fluxo (secao 15 do desafio):

    wait_for_sources      FileSensor por arquivo, modo reschedule
           v
    start_pipeline_run    abre ops.pipeline_runs
           v
    audit_sources         SHA-256 e row count -> ops.pipeline_table_metrics
           v
    validate_contracts    validacoes estruturais -> ops.data_quality_results
           v
    load_staging          KubernetesPodOperator: Meltano tap-csv/target-postgres
           v
    validate_staging      compara row count da origem com o de staging
           v
    run_data_quality      relacionamentos declarados nos contratos
           v
    promote_to_raw        transacao atomica com casts explicitos
           v
    validate_raw          contagens e unicidade de PK
           v
    finish_pipeline_run   fecha ops.pipeline_runs

A logica pesada vive no pacote `banvic`, coberto por testes unitarios. Esta
DAG orquestra: cada task chama funcoes que rodam fora do Airflow.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.providers.standard.sensors.filesystem import FileSensor
from airflow.sdk import dag, task, task_group
from kubernetes.client import models as k8s

from banvic.audit import audit_file
from banvic.contracts import load_contracts
from banvic.db import (
    TableMetrics,
    check_foreign_keys,
    count_distinct_key,
    count_rows,
    finish_run,
    record_check_results,
    record_table_metrics,
    start_run,
)
from banvic.validation import validate_source

log = logging.getLogger(__name__)

DAG_ID = "banvic_ingestion"
CONN_ID = "banvic_dw"
NAMESPACE = os.environ.get("BANVIC_NAMESPACE", "banvic")
MELTANO_IMAGE = os.environ.get("BANVIC_MELTANO_IMAGE", "banvic-meltano:0.1.0")
SOURCES_PVC = "banvic-sources-pvc"
DW_SECRET = "banvic-dw-credentials"

CONTRACTS_PATH = Path(
    os.environ.get(
        "BANVIC_CONTRACTS_PATH", "/opt/airflow/include/contracts/contracts.yml"
    )
)
PROMOTION_SQL = Path(
    os.environ.get(
        "BANVIC_PROMOTION_SQL", "/opt/airflow/include/sql/promote_raw.sql"
    )
)

CONTRACTS = load_contracts(CONTRACTS_PATH)


def _hook() -> PostgresHook:
    """Hook do Data Warehouse. A conexao vem do Secret banvic-dw-connection."""
    return PostgresHook(postgres_conn_id=CONN_ID)


@dag(
    dag_id=DAG_ID,
    description="Ingestao dos sete CSVs do ERP BanVic para o Data Warehouse",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    tags=["banvic", "ingestao", "meltano"],
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=30),
        "execution_timeout": timedelta(minutes=20),
    },
    doc_md=__doc__,
)
def banvic_ingestion() -> None:
    """Pipeline de ingestao do BanVic."""

    @task_group(group_id="wait_for_sources")
    def wait_for_sources() -> None:
        """Um sensor por arquivo, para o graph mostrar qual esta faltando.

        Modo reschedule libera o worker entre as verificacoes, em vez de
        manter um pod ocupado dormindo (evita o busy loop da secao 16).
        """
        for contrato in CONTRACTS.tables:
            FileSensor(
                task_id=f"wait_{contrato.table}",
                filepath=str(Path(CONTRACTS.source_dir) / contrato.source_file),
                fs_conn_id="fs_default",
                poke_interval=15,
                timeout=60 * 10,
                mode="reschedule",
                soft_fail=False,
            )

    @task
    def start_pipeline_run(**context) -> str:
        """Abre o registro da execucao em ops.pipeline_runs.

        run_id e chave reservada do contexto do Airflow, entao ela nao pode
        ser nome de parametro de task. Aqui ela e apenas uma variavel local
        lida do contexto, o que e permitido.
        """
        run_id = context["run_id"]
        conn = _hook().get_conn()
        try:
            start_run(conn, run_id, DAG_ID, CONTRACTS.pipeline_version)
            conn.commit()
        finally:
            conn.close()
        log.info("execucao %s registrada (pipeline %s)",
                 run_id, CONTRACTS.pipeline_version)
        return run_id

    @task
    def audit_sources(pipeline_run_id: str) -> dict[str, int]:
        """Calcula checksum e row count de cada fonte (secao 10).

        Retorna o mapa tabela -> row_count, usado adiante para comparar com
        o que chegou em staging.
        """
        contagens: dict[str, int] = {}
        conn = _hook().get_conn()
        try:
            for contrato in CONTRACTS.tables:
                caminho = CONTRACTS.source_path(contrato.table)
                auditoria = audit_file(caminho)
                contagens[contrato.table] = auditoria.row_count

                record_table_metrics(
                    conn,
                    pipeline_run_id,
                    TableMetrics(
                        table_name=contrato.table,
                        source_file=auditoria.filename,
                        source_checksum=auditoria.checksum_sha256,
                        row_count_source=auditoria.row_count,
                        status="RUNNING",
                    ),
                )
                log.info(
                    "%s: %d registros, sha256=%s",
                    contrato.table,
                    auditoria.row_count,
                    auditoria.checksum_sha256,
                )
            conn.commit()
        finally:
            conn.close()
        return contagens

    @task
    def validate_contracts(pipeline_run_id: str) -> None:
        """Valida as fontes contra os contratos declarativos (secao 21).

        Falha a task apenas quando ha resultado CRITICAL com status FAIL.
        Divergencia de row count e WARN e nao interrompe o pipeline.
        """
        todos = []
        for contrato in CONTRACTS.tables:
            relatorio = validate_source(contrato, CONTRACTS.source_path(contrato.table))
            todos.extend(relatorio.results)
            log.info("%s: %s", contrato.table, relatorio.summary())

        conn = _hook().get_conn()
        try:
            record_check_results(conn, pipeline_run_id, todos)
            conn.commit()
        finally:
            conn.close()

        bloqueantes = [r for r in todos if r.blocks_promotion]
        if bloqueantes:
            detalhes = "; ".join(
                f"{r.table_name}.{r.check_name}: {r.details}" for r in bloqueantes
            )
            raise ValueError(f"validacao estrutural falhou: {detalhes}")

        log.info("%d verificacoes estruturais, nenhuma bloqueante", len(todos))

    load_staging = KubernetesPodOperator(
        task_id="load_staging",
        name="meltano-load-staging",
        namespace=NAMESPACE,
        image=MELTANO_IMAGE,
        image_pull_policy="Never",
        cmds=["meltano"],
        arguments=["run", "tap-csv", "target-postgres"],
        env_vars=[
            k8s.V1EnvVar(
                name="TARGET_POSTGRES_HOST",
                value=f"banvic-postgres.{NAMESPACE}.svc.cluster.local",
            ),
            k8s.V1EnvVar(name="TARGET_POSTGRES_PORT", value="5432"),
            k8s.V1EnvVar(
                name="TARGET_POSTGRES_DATABASE",
                value_from=k8s.V1EnvVarSource(
                    secret_key_ref=k8s.V1SecretKeySelector(
                        name=DW_SECRET, key="POSTGRES_DB"
                    )
                ),
            ),
            k8s.V1EnvVar(
                name="TARGET_POSTGRES_USER",
                value_from=k8s.V1EnvVarSource(
                    secret_key_ref=k8s.V1SecretKeySelector(
                        name=DW_SECRET, key="POSTGRES_USER"
                    )
                ),
            ),
            k8s.V1EnvVar(
                name="TARGET_POSTGRES_PASSWORD",
                value_from=k8s.V1EnvVarSource(
                    secret_key_ref=k8s.V1SecretKeySelector(
                        name=DW_SECRET, key="POSTGRES_PASSWORD"
                    )
                ),
            ),
        ],
        volumes=[
            k8s.V1Volume(
                name="fontes",
                persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(
                    claim_name=SOURCES_PVC, read_only=True
                ),
            )
        ],
        volume_mounts=[
            k8s.V1VolumeMount(
                name="fontes", mount_path="/opt/banvic/incoming", read_only=True
            )
        ],
        get_logs=True,
        is_delete_operator_pod=True,
        in_cluster=True,
        startup_timeout_seconds=300,
    )

    @task
    def validate_staging(pipeline_run_id: str, contagens_origem: dict[str, int]) -> None:
        """Compara o row count da origem com o que chegou em staging.

        Divergencia aqui e falha tecnica, nao problema de negocio: significa
        que o Meltano perdeu ou duplicou registros. Bloqueia a promocao.
        """
        conn = _hook().get_conn()
        divergencias: list[str] = []
        try:
            for contrato in CONTRACTS.tables:
                na_origem = contagens_origem[contrato.table]
                em_staging = count_rows(conn, "staging", contrato.table)

                record_table_metrics(
                    conn,
                    pipeline_run_id,
                    TableMetrics(
                        table_name=contrato.table,
                        source_file=contrato.source_file,
                        source_checksum="",
                        row_count_source=na_origem,
                        row_count_staging=em_staging,
                        status="RUNNING",
                    ),
                )

                if na_origem != em_staging:
                    divergencias.append(
                        f"{contrato.table}: origem={na_origem} staging={em_staging}"
                    )
                log.info("%s: origem=%d staging=%d", contrato.table, na_origem, em_staging)
            conn.commit()
        finally:
            conn.close()

        if divergencias:
            raise ValueError(f"carga incompleta: {'; '.join(divergencias)}")

    @task
    def run_data_quality(pipeline_run_id: str) -> None:
        """Verifica os relacionamentos declarados nos contratos (secao 11).

        A severidade vem do contrato. O cod_cliente 528 gera WARN porque o
        contrato declara aquele relacionamento como imperfeito na origem;
        os demais relacionamentos sao CRITICAL e bloqueiam a promocao.
        """
        conn = _hook().get_conn()
        try:
            resultados = check_foreign_keys(conn, CONTRACTS, schema="staging")
            record_check_results(conn, pipeline_run_id, resultados)
            conn.commit()
        finally:
            conn.close()

        for r in resultados:
            log.info(
                "[%s] %s.%s invalid_rows=%d %s",
                r.status, r.table_name, r.check_name, r.invalid_rows, r.details,
            )

        bloqueantes = [r for r in resultados if r.blocks_promotion]
        if bloqueantes:
            detalhes = "; ".join(f"{r.check_name}: {r.details}" for r in bloqueantes)
            raise ValueError(f"integridade referencial violada: {detalhes}")

    @task
    def promote_to_raw(pipeline_run_id: str) -> None:
        """Substitui o conteudo de raw dentro de uma unica transacao (secao 13).

        psycopg2 abre transacao implicitamente e so confirma no commit. Se
        qualquer cast falhar, o rollback devolve inclusive os TRUNCATE, e a
        versao anterior de raw permanece intacta.
        """
        sql = PROMOTION_SQL.read_text(encoding="utf-8")
        conn = _hook().get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    {
                        "run_id": pipeline_run_id,
                        "pipeline_version": CONTRACTS.pipeline_version,
                    },
                )
            conn.commit()
            log.info("promocao concluida para run_id=%s", pipeline_run_id)
        except Exception:
            conn.rollback()
            log.exception("promocao falhou; raw preservada por rollback")
            raise
        finally:
            conn.close()

    @task
    def validate_raw(pipeline_run_id: str, contagens_origem: dict[str, int]) -> None:
        """Confere contagens e unicidade de PK em raw (secao 29)."""
        conn = _hook().get_conn()
        problemas: list[str] = []
        try:
            for contrato in CONTRACTS.tables:
                linhas = count_rows(conn, "raw", contrato.table)
                distintas = count_distinct_key(
                    conn, "raw", contrato.table, contrato.primary_key
                )
                na_origem = contagens_origem[contrato.table]

                record_table_metrics(
                    conn,
                    pipeline_run_id,
                    TableMetrics(
                        table_name=contrato.table,
                        source_file=contrato.source_file,
                        source_checksum="",
                        row_count_source=na_origem,
                        row_count_staging=linhas,
                        row_count_raw=linhas,
                        status="SUCCESS",
                    ),
                )

                if linhas != na_origem:
                    problemas.append(
                        f"{contrato.table}: origem={na_origem} raw={linhas}"
                    )
                if linhas != distintas:
                    problemas.append(
                        f"{contrato.table}: {linhas} linhas mas {distintas} PKs distintas"
                    )
                log.info(
                    "%s: %d linhas, %d PKs distintas", contrato.table, linhas, distintas
                )
            conn.commit()
        finally:
            conn.close()

        if problemas:
            raise ValueError(f"validacao de raw falhou: {'; '.join(problemas)}")

    @task(trigger_rule="all_success")
    def finish_success(pipeline_run_id: str) -> None:
        """Fecha ops.pipeline_runs como SUCCESS quando tudo passou."""
        conn = _hook().get_conn()
        try:
            finish_run(conn, pipeline_run_id, "SUCCESS")
            conn.commit()
        finally:
            conn.close()
        log.info("execucao %s encerrada com SUCCESS", pipeline_run_id)

    @task(trigger_rule="one_failed")
    def finish_failed(pipeline_run_id: str) -> None:
        """Fecha ops.pipeline_runs como FAILED se qualquer task falhou.

        Sem isso, um run com erro ficaria eternamente em RUNNING na tabela
        de auditoria, o que mascararia o problema na secao de evidencias.
        """
        conn = _hook().get_conn()
        try:
            finish_run(conn, pipeline_run_id, "FAILED",
                       "uma ou mais tasks falharam; ver logs no Airflow")
            conn.commit()
        finally:
            conn.close()
        log.info("execucao %s encerrada com FAILED", pipeline_run_id)

    sensores = wait_for_sources()
    run_id = start_pipeline_run()
    contagens = audit_sources(run_id)
    contratos_ok = validate_contracts(run_id)
    staging_ok = validate_staging(run_id, contagens)
    dq = run_data_quality(run_id)
    promocao = promote_to_raw(run_id)
    raw_ok = validate_raw(run_id, contagens)
    ok = finish_success(run_id)
    falha = finish_failed(run_id)

    (
        sensores
        >> run_id
        >> contagens
        >> contratos_ok
        >> load_staging
        >> staging_ok
        >> dq
        >> promocao
        >> raw_ok
        >> ok
    )

    # one_failed olha apenas os upstreams diretos, entao a task de falha
    # precisa depender de todas as etapas, e nao so da ultima.
    for etapa in (sensores, contagens, contratos_ok, load_staging,
                  staging_ok, dq, promocao, raw_ok):
        etapa >> falha


banvic_ingestion()
