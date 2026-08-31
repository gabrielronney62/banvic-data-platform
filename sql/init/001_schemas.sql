-- Estrutura de camadas do Data Warehouse BanVic.
-- Executado uma unica vez, na primeira inicializacao do cluster PostgreSQL,
-- pelo entrypoint da imagem oficial (/docker-entrypoint-initdb.d).

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS ops;

COMMENT ON SCHEMA staging IS
  'Area temporaria de carga. Recebe o Meltano com todas as colunas em TEXT, '
  'espelhando fielmente o arquivo de origem. Pode ser recriada entre execucoes.';

COMMENT ON SCHEMA raw IS
  'Copia centralizada da origem, com casts explicitos aplicados na promocao. '
  'Preserva os registros recebidos sem correcao silenciosa de dados.';

COMMENT ON SCHEMA ops IS
  'Metadados operacionais: execucoes do pipeline, metricas por tabela '
  'e resultados de data quality.';

SET timezone = 'UTC';
