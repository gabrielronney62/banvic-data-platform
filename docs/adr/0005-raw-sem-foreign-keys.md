# ADR 0005 — A camada raw não tem foreign keys

**Status:** aceito
**Data:** 2026-08

## Contexto

Os contratos declaram oito relacionamentos entre as sete tabelas. Seria
natural traduzi-los em `FOREIGN KEY` no DDL da camada `raw`.

## Decisão

A camada `raw` não tem nenhuma foreign key. A integridade referencial é
**verificada** por Data Quality e registrada em `ops.data_quality_results`,
não **imposta** por constraint.

## Justificativa

A origem tem uma inconsistência real e conhecida: `cod_cliente = 528` não
existe em `clientes.csv`, mas 1 conta e 4 propostas apontam para ele.

Com foreign keys, esses cinco registros seriam rejeitados no `INSERT`, e a
promoção falharia. As saídas possíveis seriam todas ruins: inventar o
cliente, excluir os órfãos, ou alterar as chaves — as três proibidas
explicitamente pelo enunciado.

A camada `raw` existe para reproduzir fielmente a origem. Corrigir dados ali
esconderia o problema em vez de expô-lo.

## Consequências

Um relacionamento inválido vira uma linha em `ops.data_quality_results`, com
severidade lida do contrato. Os relacionamentos que envolvem `cod_cliente`
são declarados `WARN`; os outros seis são `CRITICAL` e bloqueiam a promoção.

A política fica em YAML, não em código. Mudar a severidade de um
relacionamento é editar uma linha do contrato.

Consultas analíticas sobre a `raw` precisam lidar com órfãos explicitamente.
Uma camada de negócio construída sobre ela poderia aplicar as regras que
julgar corretas — mas essa decisão seria dela, documentada, e não um efeito
colateral silencioso da ingestão.
