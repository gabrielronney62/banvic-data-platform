# ADR 0002 — Sem docker-compose

**Status:** aceito
**Data:** 2026-08

## Contexto

`docker-compose` é o caminho mais curto para subir uma stack local. O
enunciado, porém, exige Kind, Kubernetes, Terraform e Helm.

## Decisão

Não existe `docker-compose.yml` no projeto. A orquestração local é feita
integralmente por Kind e Kubernetes.

## Alternativas consideradas

**Manter os dois.** Rejeitada: duas definições da mesma stack divergem na
primeira alteração que alguém esquecer de replicar.

**Usar compose para desenvolvimento e Kind para entrega.** Rejeitada pelo
mesmo motivo, e porque sugeriria que o Kubernetes é enfeite.

## Consequências

`docker-compose` não cobriria requisitos centrais do desafio: não tem
PersistentVolume, não tem Secret do Kubernetes, não roda `KubernetesExecutor`
e não permite o Meltano executar em pod próprio via `KubernetesPodOperator`.

O domínio de Docker é evidenciado de outra forma: duas imagens próprias com
versões fixadas e usuário não-root, `.dockerignore` restritivo, e
`kind load docker-image` injetando as imagens no nó sem registry externo.

Para desenvolvimento do `meltano.yml` e testes de integração, um PostgreSQL
descartável é criado com `docker run` direto, sem arquivo de composição.
