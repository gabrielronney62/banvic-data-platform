# syntax=docker/dockerfile:1
ARG MELTANO_VERSION=4.2.2
FROM meltano/meltano:v${MELTANO_VERSION}-python3.12

# A imagem oficial roda como root e nao traz usuario dedicado.
# Criamos um para atender ao requisito de nao-root da secao 19.
# UID 1000 e o primeiro nao-privilegiado, livre nesta base.
ARG APP_UID=1000
ARG APP_GID=1000

RUN groupadd --gid ${APP_GID} meltano \
 && useradd --uid ${APP_UID} --gid ${APP_GID} --create-home --shell /bin/bash meltano

WORKDIR /project

COPY meltano.yml /project/meltano.yml

# Plugins instalados no build, nao em runtime: o pod sobe pronto e a
# execucao nao depende de rede nem de disponibilidade do PyPI/GitHub.
RUN meltano install --clean \
 && meltano --version

# Ponto de montagem das fontes. Criado no build para que uma falha de
# volume apareca como diretorio vazio, e nao como caminho inexistente.
RUN mkdir -p /opt/banvic/incoming

# O Meltano escreve em .meltano/ e em logs durante a execucao.
RUN chown -R ${APP_UID}:${APP_GID} /project /opt/banvic

USER meltano

ENTRYPOINT ["meltano"]
CMD ["--version"]
