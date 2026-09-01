-- Tabelas operacionais do pipeline (secoes 9 e 10).
--
-- Idempotente de proposito: roda a cada execucao da DAG sem destruir
-- historico. Nao fica no entrypoint do container, que executa apenas na
-- primeira inicializacao do volume e impediria evoluir o esquema.

CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS ops.pipeline_runs (
    run_id            text        PRIMARY KEY,
    dag_id            text        NOT NULL,
    pipeline_version  text        NOT NULL,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'RUNNING',
    error_message     text,
    CONSTRAINT ck_pipeline_runs_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
);

COMMENT ON TABLE ops.pipeline_runs IS
    'Uma linha por execucao da DAG. run_id vem do Airflow.';

CREATE TABLE IF NOT EXISTS ops.pipeline_table_metrics (
    id                bigserial   PRIMARY KEY,
    run_id            text        NOT NULL REFERENCES ops.pipeline_runs(run_id),
    table_name        text        NOT NULL,
    source_file       text,
    source_checksum   text,
    row_count_source  bigint,
    row_count_staging bigint,
    row_count_raw     bigint,
    started_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz,
    status            text        NOT NULL DEFAULT 'RUNNING',
    error_message     text,
    CONSTRAINT uq_metrics_run_table UNIQUE (run_id, table_name),
    CONSTRAINT ck_metrics_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED'))
);

COMMENT ON TABLE ops.pipeline_table_metrics IS
    'Metricas por tabela: checksum SHA-256 do arquivo e contagens em cada camada.';

CREATE TABLE IF NOT EXISTS ops.data_quality_results (
    id           bigserial   PRIMARY KEY,
    run_id       text        NOT NULL REFERENCES ops.pipeline_runs(run_id),
    table_name   text        NOT NULL,
    check_name   text        NOT NULL,
    severity     text        NOT NULL,
    status       text        NOT NULL,
    invalid_rows bigint      NOT NULL DEFAULT 0,
    details      text,
    checked_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dq_severity CHECK (severity IN ('CRITICAL', 'WARN', 'INFO')),
    CONSTRAINT ck_dq_status   CHECK (status   IN ('PASS', 'WARN', 'FAIL'))
);

COMMENT ON TABLE ops.data_quality_results IS
    'Resultados de Data Quality. Severidade separa falha tecnica (CRITICAL) '
    'de problema conhecido da origem (WARN), como o cod_cliente 528.';

CREATE INDEX IF NOT EXISTS ix_dq_run     ON ops.data_quality_results (run_id);
CREATE INDEX IF NOT EXISTS ix_dq_status  ON ops.data_quality_results (status);
CREATE INDEX IF NOT EXISTS ix_metrics_run ON ops.pipeline_table_metrics (run_id);
