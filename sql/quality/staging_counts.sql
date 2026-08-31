-- Contagem por tabela em staging. Os valores vem do banco, nunca escritos
-- manualmente: e a evidencia exigida na secao 29.
SELECT 'agencias'            AS tabela, count(*) AS registros FROM staging.agencias
UNION ALL SELECT 'clientes',            count(*) FROM staging.clientes
UNION ALL SELECT 'colaborador_agencia', count(*) FROM staging.colaborador_agencia
UNION ALL SELECT 'colaboradores',       count(*) FROM staging.colaboradores
UNION ALL SELECT 'contas',              count(*) FROM staging.contas
UNION ALL SELECT 'propostas_credito',   count(*) FROM staging.propostas_credito
UNION ALL SELECT 'transacoes',          count(*) FROM staging.transacoes
ORDER BY tabela;
