-- Promocao atomica de staging para raw (secoes 12 e 13).
--
-- Todo o conteudo das sete tabelas raw e substituido dentro de UMA
-- transacao. Se qualquer INSERT falhar, o ROLLBACK preserva a versao
-- anterior da raw intacta.
--
-- Os casts acontecem aqui, e nao no Meltano. O tap-csv emite tudo como
-- string, staging espelha o arquivo, e a conversao fica em SQL versionado
-- e auditavel. Um valor invalido faz esta transacao falhar, sem destruir
-- a raw valida que ja existia.
--
-- Parametros esperados via psql -v:
--   run_id            identificador da execucao do Airflow
--   pipeline_version  versao do pipeline
--
-- Uso:
--   psql -v ON_ERROR_STOP=1 -v run_id=... -v pipeline_version=... -f promote_raw.sql

\set ON_ERROR_STOP on

BEGIN;

-- ---------------------------------------------------------------- agencias
TRUNCATE TABLE raw.agencias;
INSERT INTO raw.agencias (
    cod_agencia, nome, endereco, cidade, uf, data_abertura, tipo_agencia,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_agencia::bigint,
    nome,
    endereco,
    cidade,
    uf,
    data_abertura::date,
    tipo_agencia,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.agencias;

-- ---------------------------------------------------------------- clientes
TRUNCATE TABLE raw.clientes;
INSERT INTO raw.clientes (
    cod_cliente, primeiro_nome, ultimo_nome, email, tipo_cliente,
    data_inclusao, cpfcnpj, data_nascimento, endereco, cep,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_cliente::bigint,
    primeiro_nome,
    ultimo_nome,
    email,
    tipo_cliente,
    data_inclusao::timestamptz,
    cpfcnpj,
    data_nascimento::date,
    endereco,
    cep,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.clientes;

-- ------------------------------------------------------- colaborador_agencia
TRUNCATE TABLE raw.colaborador_agencia;
INSERT INTO raw.colaborador_agencia (
    cod_colaborador, cod_agencia,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_colaborador::bigint,
    cod_agencia::bigint,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.colaborador_agencia;

-- ----------------------------------------------------------- colaboradores
TRUNCATE TABLE raw.colaboradores;
INSERT INTO raw.colaboradores (
    cod_colaborador, primeiro_nome, ultimo_nome, email, cpf,
    data_nascimento, endereco, cep,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_colaborador::bigint,
    primeiro_nome,
    ultimo_nome,
    email,
    cpf,
    data_nascimento::date,
    endereco,
    cep,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.colaboradores;

-- ------------------------------------------------------------------ contas
TRUNCATE TABLE raw.contas;
INSERT INTO raw.contas (
    num_conta, cod_cliente, cod_agencia, cod_colaborador, tipo_conta,
    data_abertura, saldo_total, saldo_disponivel, data_ultimo_lancamento,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    num_conta::bigint,
    cod_cliente::bigint,
    cod_agencia::bigint,
    cod_colaborador::bigint,
    tipo_conta,
    data_abertura::timestamptz,
    saldo_total::numeric,
    saldo_disponivel::numeric,
    data_ultimo_lancamento::timestamptz,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.contas;

-- ------------------------------------------------------- propostas_credito
TRUNCATE TABLE raw.propostas_credito;
INSERT INTO raw.propostas_credito (
    cod_proposta, cod_cliente, cod_colaborador, data_entrada_proposta,
    taxa_juros_mensal, valor_proposta, valor_financiamento, valor_entrada,
    valor_prestacao, quantidade_parcelas, carencia, status_proposta,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_proposta::bigint,
    cod_cliente::bigint,
    cod_colaborador::bigint,
    data_entrada_proposta::timestamptz,
    taxa_juros_mensal::numeric,
    valor_proposta::numeric,
    valor_financiamento::numeric,
    valor_entrada::numeric,
    valor_prestacao::numeric,
    quantidade_parcelas::integer,
    carencia::integer,
    status_proposta,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.propostas_credito;

-- -------------------------------------------------------------- transacoes
TRUNCATE TABLE raw.transacoes;
INSERT INTO raw.transacoes (
    cod_transacao, num_conta, data_transacao, nome_transacao, valor_transacao,
    _source_file, _source_lineno, _airflow_run_id, _pipeline_version
)
SELECT
    cod_transacao::bigint,
    num_conta::bigint,
    data_transacao::timestamptz,
    nome_transacao,
    valor_transacao::numeric,
    _sdc_source_file,
    _sdc_source_lineno,
    :'run_id',
    :'pipeline_version'
FROM staging.transacoes;

COMMIT;
