# ADR 0006 — numeric sem precisão declarada para valores monetários

**Status:** aceito
**Data:** 2026-08

## Contexto

Valores monetários costumam ser declarados como `NUMERIC(18,2)`. A auditoria
das fontes, porém, revelou algo inesperado.

## Decisão

Colunas monetárias em `raw` usam `numeric` **sem precisão nem escala
declaradas**.

## Justificativa

A auditoria dos CSVs de origem encontrou até 17 casas decimais:

```
contas.saldo_disponivel        casas_decimais_max = 17
contas.saldo_total             casas_decimais_max = 16
propostas.valor_prestacao      casas_decimais_max = 15
transacoes.valor_transacao     casas_decimais_max = 15
```

São artefatos de aritmética de ponto flutuante no sistema de origem, mas o
valor recebido é o que a `raw` deve preservar.

`NUMERIC(18,2)` arredondaria silenciosamente: um saldo gravado como
`22538.060000000005` viraria `22538.06`, e ninguém notaria.

O tipo `numeric` irrestrito do PostgreSQL armazena o decimal exato como veio
na string de origem.

## Alternativas consideradas

**`double precision`** faz round-trip bit-exato dos mesmos valores, mas
`numeric` é mais defensável em contexto financeiro e não introduz surpresas
em agregações.

**`text`** preservaria tudo, mas inviabilizaria qualquer soma ou média sem
cast a cada consulta.

## Consequências

Verificável por teste de integração:

```sql
SELECT count(*) FROM raw.contas
 WHERE length(split_part(saldo_disponivel::text, '.', 2)) > 2;
```

Se retornar zero, houve arredondamento e a decisão não foi aplicada.

Uma eventual camada de negócio pode arredondar para duas casas conforme a
regra contábil apropriada. Essa é uma decisão de negócio, e o lugar dela não
é a camada que reproduz a origem.
