# Dicionário de dados

As sete tabelas do ERP do BanVic, os tipos aplicados na camada `raw` e as
particularidades encontradas na auditoria das fontes.

Os contratos declarativos em `airflow/include/contracts/contracts.yml` são a
fonte de verdade; este documento explica o raciocínio por trás deles.

---

## Inventário

| Tabela | Registros | Colunas | Chave primária |
|---|---:|---:|---|
| `agencias` | 10 | 7 | `cod_agencia` |
| `clientes` | 998 | 10 | `cod_cliente` |
| `colaborador_agencia` | 100 | 2 | `cod_colaborador` + `cod_agencia` |
| `colaboradores` | 100 | 8 | `cod_colaborador` |
| `contas` | 999 | 9 | `num_conta` |
| `propostas_credito` | 2.000 | 12 | `cod_proposta` |
| `transacoes` | 71.999 | 5 | `cod_transacao` |

Arquivos CSV separados por vírgula, codificação UTF-8, terminador LF, sem
BOM. Nenhum valor nulo nas fontes atuais — o que **não** deve ser assumido
para cargas futuras.

---

## Colunas de linhagem

Todas as tabelas em `raw` recebem cinco colunas adicionais:

| Coluna | Tipo | Origem |
|---|---|---|
| `_ingested_at` | `timestamptz` | `now()` na promoção |
| `_source_file` | `text` | `_sdc_source_file` do tap-csv |
| `_source_lineno` | `bigint` | `_sdc_source_lineno` do tap-csv |
| `_airflow_run_id` | `text` | `run_id` da execução |
| `_pipeline_version` | `text` | `pipeline_version` do contrato |

O `_source_lineno` permite apontar a linha exata do CSV quando um registro
falha uma validação.

---

## agencias

| Coluna | Tipo em `raw` |
|---|---|
| `cod_agencia` | `bigint` (PK) |
| `nome` | `text` |
| `endereco` | `text` |
| `cidade` | `text` |
| `uf` | `text` |
| `data_abertura` | `date` |
| `tipo_agencia` | `text` |

`endereco` contém vírgulas e aspas, o que torna obrigatório o parsing com
quoting. Contar linhas com `wc -l` funciona neste conjunto, mas o código usa
`csv.reader` por robustez.

---

## clientes

| Coluna | Tipo em `raw` | Observação |
|---|---|---|
| `cod_cliente` | `bigint` (PK) | 1 a 999, com o 528 ausente |
| `primeiro_nome` | `text` | |
| `ultimo_nome` | `text` | |
| `email` | `text` | **não é único** |
| `tipo_cliente` | `text` | valor único no conjunto atual |
| `data_inclusao` | `timestamptz` | sufixo `UTC` |
| `cpfcnpj` | `text` | 96 valores começam com zero |
| `data_nascimento` | `date` | |
| `endereco` | `text` | |
| `cep` | `text` | dois formatos, 105 começam com zero |

**E-mails compartilhados.** Quatro endereços aparecem em dois clientes cada.
Não existe regra de negócio proibindo isso, então o projeto não trata `email`
como `UNIQUE`. Se houvesse verificação, seria `INFO`.

**CEP em dois formatos.** Aproximadamente metade dos registros usa
`99999-999` e a outra metade `99999999`. É heterogeneidade da origem,
preservada como está e registrável como `INFO`. Normalizar seria alterar o
dado.

**Zeros à esquerda.** Conversão numérica de `cpfcnpj` ou `cep` destruiria o
dado. Ver [ADR 0007](adr/0007-casts-em-sql-nao-no-meltano.md).

---

## colaborador_agencia

| Coluna | Tipo em `raw` |
|---|---|
| `cod_colaborador` | `bigint` |
| `cod_agencia` | `bigint` |

Tabela associativa sem chave própria. A PK é composta pelas duas colunas, e a
unicidade foi verificada na auditoria: 100 combinações distintas em 100
registros.

Relacionamentos, ambos `CRITICAL`:

```
cod_colaborador -> colaboradores.cod_colaborador
cod_agencia     -> agencias.cod_agencia
```

---

## colaboradores

| Coluna | Tipo em `raw` | Observação |
|---|---|---|
| `cod_colaborador` | `bigint` (PK) | |
| `primeiro_nome` | `text` | |
| `ultimo_nome` | `text` | |
| `email` | `text` | sem duplicatas |
| `cpf` | `text` | zeros à esquerda |
| `data_nascimento` | `date` | |
| `endereco` | `text` | |
| `cep` | `text` | dois formatos, zeros à esquerda |

---

## contas

| Coluna | Tipo em `raw` | Observação |
|---|---|---|
| `num_conta` | `bigint` (PK) | |
| `cod_cliente` | `bigint` | inclui o órfão 528 |
| `cod_agencia` | `bigint` | |
| `cod_colaborador` | `bigint` | |
| `tipo_conta` | `text` | valor único no conjunto atual |
| `data_abertura` | `timestamptz` | sufixo `UTC` |
| `saldo_total` | `numeric` | até 16 casas decimais |
| `saldo_disponivel` | `numeric` | até 17 casas decimais |
| `data_ultimo_lancamento` | `timestamptz` | **mistura com e sem microssegundos** |

**Precisão decimal.** Ver [ADR 0006](adr/0006-numeric-sem-precisao.md).

**Sem regra `saldo_disponivel <= saldo_total`.** Nenhuma regra de negócio
sustenta essa afirmação, então nenhuma verificação a impõe.

Relacionamentos:

```
cod_cliente     -> clientes.cod_cliente          WARN
cod_agencia     -> agencias.cod_agencia          CRITICAL
cod_colaborador -> colaboradores.cod_colaborador CRITICAL
```

---

## propostas_credito

| Coluna | Tipo em `raw` | Observação |
|---|---|---|
| `cod_proposta` | `bigint` (PK) | |
| `cod_cliente` | `bigint` | inclui 4 órfãs do 528 |
| `cod_colaborador` | `bigint` | |
| `data_entrada_proposta` | `timestamptz` | sufixo `UTC` |
| `taxa_juros_mensal` | `numeric` | |
| `valor_proposta` | `numeric` | |
| `valor_financiamento` | `numeric` | |
| `valor_entrada` | `numeric` | |
| `valor_prestacao` | `numeric` | até 15 casas decimais |
| `quantidade_parcelas` | `integer` | 1 a 120 |
| `carencia` | `integer` | **292 registros com valor zero** |
| `status_proposta` | `text` | |

**Carência zero é válida.** Uma verificação ingênua de `> 0` geraria 292
falsos positivos.

---

## transacoes

| Coluna | Tipo em `raw` | Observação |
|---|---|---|
| `cod_transacao` | `bigint` (PK) | |
| `num_conta` | `bigint` | |
| `data_transacao` | `timestamptz` | **mistura com e sem microssegundos** |
| `nome_transacao` | `text` | |
| `valor_transacao` | `numeric` | **59.748 valores negativos** |

**Negativo é a norma, não a exceção.** Cerca de 83% das transações têm valor
negativo. Tratá-las como erro invalidaria a maior parte do conjunto.

Período coberto: 2010 a 2023.

---

## Particularidades transversais

### Timestamps com e sem microssegundos

Duas colunas misturam os dois formatos no mesmo campo:

```
2020-05-22 03:15:21 UTC
2022-12-30 00:00:00.041757 UTC
```

O `::timestamptz` do PostgreSQL aceita ambos, inclusive a abreviação `UTC`.
Uma regra que rejeitasse a parte fracionária invalidaria dados corretos.

### A inconsistência do cliente 528

| Tabela | Registros com `cod_cliente = 528` |
|---|---:|
| `clientes` | 0 |
| `contas` | 1 |
| `propostas_credito` | 4 |

Preservada integralmente. Ver
[ADR 0005](adr/0005-raw-sem-foreign-keys.md) e
[data-quality.md](data-quality.md).

### Domínios de valor único

`clientes.tipo_cliente` e `contas.tipo_conta` têm um único valor distinto no
conjunto atual. Criar `CHECK` sobre isso seria inventar regra e quebraria na
primeira carga com outro tipo.
