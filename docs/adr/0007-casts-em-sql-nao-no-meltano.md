# ADR 0007 — Casts em SQL na promoção, não no Meltano

**Status:** aceito
**Data:** 2026-08

## Contexto

O `tap-csv` do MeltanoLabs não infere tipos: emite todas as colunas como
`string`. Poderíamos configurar tipagem no tap ou no target, ou aceitar o
comportamento padrão.

## Decisão

`staging` recebe tudo em `TEXT`, espelhando o arquivo. Os casts acontecem no
SQL de promoção de `staging` para `raw`, dentro da transação atômica.

## Justificativa

**O Meltano nunca falha por conversão.** Um CPF com formato estranho ou uma
data inválida chegam intactos ao `staging`. O problema vira resultado de Data
Quality, não crash de ingestão — o que atende à separação exigida entre falha
técnica e qualidade da origem.

**Os casts ficam versionados e auditáveis.** `sql/promotion/promote_raw.sql`
mostra, coluna por coluna, o que vira `bigint`, o que vira `timestamptz`, e o
que permanece `text`. Revisar isso num arquivo SQL é mais simples do que
inferir o comportamento de um plugin.

**Uma falha de cast não destrói dados bons.** Como a promoção é uma
transação, o `ROLLBACK` devolve os `TRUNCATE` e a versão anterior de `raw`
permanece intacta.

## O que os casts preservam

Campos que **permanecem** `text` por decisão explícita:

- `cpfcnpj`, `cpf`, `cep`: 96 CPFs e 105 CEPs começam com zero, e a conversão
  numérica destruiria o dado.

Campos com particularidade de formato:

- `clientes.data_inclusao`, `contas.data_abertura`,
  `contas.data_ultimo_lancamento`, `propostas.data_entrada_proposta` e
  `transacoes.data_transacao` trazem sufixo `UTC`, e duas dessas colunas
  misturam valores com e sem microssegundos. O `::timestamptz` do PostgreSQL
  aceita os dois formatos.
- `agencias.data_abertura`, `clientes.data_nascimento` e
  `colaboradores.data_nascimento` são `date` puro.

## Consequências

O mesmo arquivo SQL é usado pela DAG (via `PostgresHook`) e pelo script
manual `scripts/promote.py` (via psycopg2), evitando duas versões da
promoção divergindo com o tempo.

Uma armadilha descoberta na prática: o psycopg2 varre a string inteira
procurando marcadores `%(nome)s`, **inclusive dentro de comentários SQL**. Um
marcador escrito num comentário explicativo vira parâmetro esperado e quebra
a execução com `KeyError`. Há um teste unitário que impede a recorrência.
