-- Contagem e unicidade de PK por tabela em raw (secao 29).
-- Os valores vem do banco durante a execucao, nunca escritos manualmente.
SELECT 'agencias'            AS tabela, count(*) AS linhas, count(DISTINCT cod_agencia)                       AS pks_distintas FROM raw.agencias
UNION ALL SELECT 'clientes',            count(*), count(DISTINCT cod_cliente)                                 FROM raw.clientes
UNION ALL SELECT 'colaborador_agencia', count(*), count(DISTINCT (cod_colaborador, cod_agencia))              FROM raw.colaborador_agencia
UNION ALL SELECT 'colaboradores',       count(*), count(DISTINCT cod_colaborador)                             FROM raw.colaboradores
UNION ALL SELECT 'contas',              count(*), count(DISTINCT num_conta)                                   FROM raw.contas
UNION ALL SELECT 'propostas_credito',   count(*), count(DISTINCT cod_proposta)                                FROM raw.propostas_credito
UNION ALL SELECT 'transacoes',          count(*), count(DISTINCT cod_transacao)                               FROM raw.transacoes
ORDER BY tabela;
