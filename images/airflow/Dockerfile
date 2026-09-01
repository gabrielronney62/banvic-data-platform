# syntax=docker/dockerfile:1
ARG AIRFLOW_VERSION=3.2.2
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

# Reaproveita os ARGs apos o FROM: eles nao atravessam o estagio sozinhos.
ARG AIRFLOW_VERSION
ARG PYTHON_VERSION
ARG AIRFLOW_CONSTRAINTS_URL

# A imagem base ja roda como airflow (uid 50000). Nao voltamos para root.
USER airflow

COPY --chown=airflow:root images/airflow/requirements.txt /tmp/requirements.txt

# O constraints do Airflow resolve providers e dependencias transitivas de
# forma coerente com a versao do core. E o mecanismo canonico do projeto,
# mais confiavel do que fixar dezenas de versoes a mao.
RUN pip install --no-cache-dir \
      --constraint "${AIRFLOW_CONSTRAINTS_URL}" \
      -r /tmp/requirements.txt

# Pacote de suporte do pipeline. Copiado em vez de instalado via pip para
# manter o build simples e o contexto enxuto.
COPY --chown=airflow:root src/banvic /opt/airflow/lib/banvic

ENV PYTHONPATH=/opt/airflow/lib
ENV BANVIC_CONTRACTS_PATH=/opt/airflow/include/contracts/contracts.yml

# Falha o build se o pacote nao importar: melhor descobrir aqui do que
# num pod em CrashLoopBackOff.
RUN python -c "import banvic, yaml, psycopg2; print('banvic', banvic.__version__)"
