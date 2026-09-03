# ADR 0001 — PostgreSQL como destino, não MinIO

**Status:** aceito
**Data:** 2026-08

## Contexto

O enunciado permite object storage (MinIO) ou banco relacional como destino
da ingestão. Precisamos escolher um.

## Decisão

PostgreSQL como Data Warehouse, com as camadas `staging`, `raw` e `ops`.

## Justificativa

As fontes são cópias de tabelas de um ERP: já são relacionais, com chaves
primárias e relacionamentos declarados. Convertê-las para arquivos em object
storage e depois consultá-las com SQL adiciona uma camada sem ganho.

São sete tabelas, não setecentas. O volume total é de 4,7 MB.

A verificação final é SQL. Com PostgreSQL, comprovar row counts, unicidade de
PK e integridade referencial é uma consulta. Com MinIO, exigiria uma camada
de query engine.

A promoção atômica entre camadas usa uma transação do próprio banco. Em
object storage, atomicidade exigiria estratégia de swap de prefixos ou um
formato transacional como Delta ou Iceberg — complexidade desproporcional
para o tamanho do problema.

## Consequências

O projeto não demonstra manipulação de object storage. Em compensação,
demonstra transação, rollback, constraints e verificação declarativa de
integridade, que são competências mais próximas do domínio bancário.

Se o volume crescesse a ponto de justificar particionamento e leitura
colunar, a decisão deveria ser revista.
