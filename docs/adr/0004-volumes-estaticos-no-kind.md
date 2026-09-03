# ADR 0004 — Volumes com bind estático em vez do provisionador padrão

**Status:** aceito
**Data:** 2026-08

## Contexto

O Kind traz uma StorageClass `standard` com o provisionador `local-path`, que
cria volumes automaticamente. Três volumes do projeto, porém, precisam
apontar para diretórios específicos do host: as fontes CSV, as DAGs e os
logs.

## Decisão

Fontes, DAGs e logs usam PersistentVolume com `hostPath` e bind estático, em
StorageClasses dedicadas e sem provisionador (`banvic-sources`,
`banvic-dags`, `banvic-logs`).

Os volumes de dados dos dois PostgreSQL usam a StorageClass `standard`, com
provisionamento dinâmico.

## Justificativa

Se usássemos a `standard` para as fontes, o provisionador criaria um volume
novo e **vazio**, ignorando os arquivos do host. Ao declarar uma StorageClass
que não tem provisionador, forçamos o Kubernetes a casar o PVC com o PV que
declaramos, e com nenhum outro.

O volume de logs tem um motivo adicional: o chart do Airflow o cria com
`ReadWriteMany`, e o `local-path` só suporta `ReadWriteOnce`. Sem o PV
estático, o PVC fica `Pending` e os quatro componentes nunca são agendados.

## Consequências

`hostPath` amarra o volume a um nó específico, o que está **declarado** via
`node_affinity`. Num cluster de vários nós isso seria incorreto; com um nó,
é uma simplificação legítima do Kind, e a afinidade documenta a restrição.

`reclaim_policy: Retain` garante que apagar um PVC não apague os dados de
origem.

Efeito colateral útil: os logs ficam legíveis em `airflow/logs/` no host,
sem precisar de `kubectl logs`.

Efeito colateral ruim: os `extraMounts` do Kind não se restabelecem após
`docker start`. Ver `docs/troubleshooting.md`.
