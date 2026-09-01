-- Camada raw: copia centralizada da origem, com tipos nativos.
--
-- Decisoes deliberadas:
--
-- 1. NENHUMA FOREIGN KEY. A origem tem 1 conta e 4 propostas apontando para
--    o cod_cliente 528, que nao existe em clientes.csv (secao 7). Uma FK
--    rejeitaria esses registros, e a raw deve reproduzir fielmente a origem.
--    A integridade referencial e verificada por Data Quality, nao imposta
--    por constraint.
--
-- 2. numeric SEM precisao. A origem traz ate 17 casas decimais em
--    saldo_disponivel. NUMERIC(18,2) arredondaria silenciosamente. O tipo
--    numeric irrestrito do PostgreSQL armazena o decimal exato recebido.
--
-- 3. cpfcnpj, cpf e cep como text. 96 CPFs e 105 CEPs comecam com zero.
--
-- 4. timestamptz para os campos com sufixo UTC, aceitando com e sem fracao
--    de segundo (contas.data_ultimo_lancamento e transacoes.data_transacao
--    misturam os dois formatos na mesma coluna).
--
-- 5. Colunas de linhagem prefixadas com _ (secao 9).

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.agencias (
    cod_agencia       bigint PRIMARY KEY,
    nome              text   NOT NULL,
    endereco          text   NOT NULL,
    cidade            text   NOT NULL,
    uf                text   NOT NULL,
    data_abertura     date   NOT NULL,
    tipo_agencia      text   NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),
    _source_file      text,
    _source_lineno    bigint,
    _airflow_run_id   text,
    _pipeline_version text
);

CREATE TABLE IF NOT EXISTS raw.clientes (
    cod_cliente       bigint PRIMARY KEY,
    primeiro_nome     text   NOT NULL,
    ultimo_nome       text   NOT NULL,
    email             text   NOT NULL,
    tipo_cliente      text   NOT NULL,
    data_inclusao     timestamptz NOT NULL,
    cpfcnpj           text   NOT NULL,
    data_nascimento   date   NOT NULL,
    endereco          text   NOT NULL,
    cep               text   NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),
    _source_file      text,
    _source_lineno    bigint,
    _airflow_run_id   text,
    _pipeline_version text
);

CREATE TABLE IF NOT EXISTS raw.colaborador_agencia (
    cod_colaborador   bigint NOT NULL,
    cod_agencia       bigint NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),
    _source_file      text,
    _source_lineno    bigint,
    _airflow_run_id   text,
    _pipeline_version text,
    PRIMARY KEY (cod_colaborador, cod_agencia)
);

CREATE TABLE IF NOT EXISTS raw.colaboradores (
    cod_colaborador   bigint PRIMARY KEY,
    primeiro_nome     text   NOT NULL,
    ultimo_nome       text   NOT NULL,
    email             text   NOT NULL,
    cpf               text   NOT NULL,
    data_nascimento   date   NOT NULL,
    endereco          text   NOT NULL,
    cep               text   NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),
    _source_file      text,
    _source_lineno    bigint,
    _airflow_run_id   text,
    _pipeline_version text
);

CREATE TABLE IF NOT EXISTS raw.contas (
    num_conta              bigint PRIMARY KEY,
    cod_cliente            bigint NOT NULL,
    cod_agencia            bigint NOT NULL,
    cod_colaborador        bigint NOT NULL,
    tipo_conta             text   NOT NULL,
    data_abertura          timestamptz NOT NULL,
    saldo_total            numeric NOT NULL,
    saldo_disponivel       numeric NOT NULL,
    data_ultimo_lancamento timestamptz NOT NULL,
    _ingested_at           timestamptz NOT NULL DEFAULT now(),
    _source_file           text,
    _source_lineno         bigint,
    _airflow_run_id        text,
    _pipeline_version      text
);

CREATE TABLE IF NOT EXISTS raw.propostas_credito (
    cod_proposta          bigint PRIMARY KEY,
    cod_cliente           bigint  NOT NULL,
    cod_colaborador       bigint  NOT NULL,
    data_entrada_proposta timestamptz NOT NULL,
    taxa_juros_mensal     numeric NOT NULL,
    valor_proposta        numeric NOT NULL,
    valor_financiamento   numeric NOT NULL,
    valor_entrada         numeric NOT NULL,
    valor_prestacao       numeric NOT NULL,
    quantidade_parcelas   integer NOT NULL,
    carencia              integer NOT NULL,
    status_proposta       text    NOT NULL,
    _ingested_at          timestamptz NOT NULL DEFAULT now(),
    _source_file          text,
    _source_lineno        bigint,
    _airflow_run_id       text,
    _pipeline_version     text
);

CREATE TABLE IF NOT EXISTS raw.transacoes (
    cod_transacao     bigint PRIMARY KEY,
    num_conta         bigint NOT NULL,
    data_transacao    timestamptz NOT NULL,
    nome_transacao    text    NOT NULL,
    valor_transacao   numeric NOT NULL,
    _ingested_at      timestamptz NOT NULL DEFAULT now(),
    _source_file      text,
    _source_lineno    bigint,
    _airflow_run_id   text,
    _pipeline_version text
);

CREATE INDEX IF NOT EXISTS ix_transacoes_conta ON raw.transacoes (num_conta);
CREATE INDEX IF NOT EXISTS ix_contas_cliente   ON raw.contas (cod_cliente);
CREATE INDEX IF NOT EXISTS ix_propostas_cliente ON raw.propostas_credito (cod_cliente);
