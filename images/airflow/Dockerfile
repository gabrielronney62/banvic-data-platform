# syntax=docker/dockerfile:1
ARG AIRFLOW_VERSION=3.2.2
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION
ARG PYTHON_VERSION
ARG AIRFLOW_CONSTRAINTS_URL

USER airflow

COPY --chown=airflow:root images/airflow/requirements.txt /tmp/requirements.txt

# O constraints do Airflow resolve providers e dependencias transitivas de
# forma coerente com a versao do core. E o mecanismo canonico do projeto.
RUN pip install --no-cache-dir \
      --constraint "${AIRFLOW_CONSTRAINTS_URL}" \
      -r /tmp/requirements.txt

# Pacote de suporte do pipeline.
COPY --chown=airflow:root src/banvic /opt/airflow/lib/banvic

# Contratos e SQL de promocao entram na IMAGEM, nao no volume de DAGs.
# Sao codigo do pipeline, nao configuracao de runtime: alterar um contrato
# exige rebuild e nova tag, o que mantem a rastreabilidade da secao 21.
COPY --chown=airflow:root airflow/include/contracts /opt/airflow/include/contracts
COPY --chown=airflow:root sql/promotion/promote_raw.sql /opt/airflow/include/sql/promote_raw.sql

ENV PYTHONPATH=/opt/airflow/lib
ENV BANVIC_CONTRACTS_PATH=/opt/airflow/include/contracts/contracts.yml
ENV BANVIC_PROMOTION_SQL=/opt/airflow/include/sql/promote_raw.sql

# Falha o build se algo essencial faltar, em vez de descobrir num pod
# em CrashLoopBackOff.
RUN python -c "import banvic, yaml, psycopg2; print('banvic', banvic.__version__)" \
 && python -c "from banvic.contracts import load_contracts; \
c = load_contracts('/opt/airflow/include/contracts/contracts.yml'); \
assert len(c.tables) == 7, c.table_names; print('contratos:', c.table_names)" \
 && test -s /opt/airflow/include/sql/promote_raw.sql
