# Data Quality

Política de qualidade de dados do pipeline: o que bloqueia a promoção, o que
é apenas registrado, e por quê.

---

## A separação fundamental

O projeto distingue dois conceitos que costumam ser tratados como um só.

**Validação estrutural** indica possível falha técnica na extração ou na
carga. Pode impedir a promoção para `raw`.

**Qualidade dos dados de negócio** descreve a origem como ela é. É
registrada e preservada, nunca corrigida.

A distinção não é retórica: ela está codificada no tipo. Um `CheckResult` só
bloqueia a promoção quando satisfaz as duas condições:

```python
@property
def blocks_promotion(self) -> bool:
    return self.status == STATUS_FAIL and self.severity == SEVERITY_CRITICAL
```

---

## Severidades

| Severidade | Significado | Bloqueia? |
|---|---|---|
| `CRITICAL` | Possível falha técnica | Sim, quando `status = FAIL` |
| `WARN` | Problema conhecido da origem | Não |
| `INFO` | Observação, sem julgamento | Não |

| Status | Significado |
|---|---|
| `PASS` | Verificação passou |
| `WARN` | Divergência registrada, sem bloqueio |
| `FAIL` | Verificação falhou |

A severidade dos relacionamentos vem dos **contratos declarativos**, não do
código Python. Mudar a política de um relacionamento é editar uma linha de
YAML.

---

## Catálogo de verificações

### Estruturais, sobre os arquivos de origem

Executadas por `validate_contracts`, antes da ingestão.

| Verificação | Severidade | Bloqueia | O que detecta |
|---|---|---|---|
| `file_present` | `CRITICAL` | Sim | Arquivo ausente ou vazio |
| `header_matches_contract` | `CRITICAL` | Sim | Coluna declarada faltando |
| `header_matches_contract` | `INFO` | Não | Coluna extra não declarada |
| `primary_key_not_null` | `CRITICAL` | Sim | PK nula |
| `primary_key_unique` | `CRITICAL` | Sim | PK duplicada |
| `row_count_matches_expected` | `WARN` | Não | Contagem diferente do contrato |

**Coluna extra é `INFO`.** A origem pode ganhar campos sem que isso quebre a
ingestão.

**Row count divergente é `WARN`.** Uma carga futura legitimamente traz outra
quantidade de registros. O que importa é o número ser registrado e a
divergência ficar visível.

**PK nula ou duplicada é `CRITICAL`.** Não é característica legítima de uma
tabela com chave primária declarada; indica problema de extração ou
corrupção.

### Estrutural, sobre a carga

Executada por `validate_staging`, depois do Meltano.

| Verificação | Bloqueia | O que detecta |
|---|---|---|
| origem = staging | Sim | Meltano perdeu ou duplicou registros |

Divergência aqui é falha técnica, não problema de negócio.

### Relacionamentos, sobre staging

Executada por `run_data_quality`. A severidade vem do contrato.

| Verificação | Severidade | Bloqueia |
|---|---|---|
| `fk_colaborador_agencia_colaboradores` | `CRITICAL` | Sim |
| `fk_colaborador_agencia_agencias` | `CRITICAL` | Sim |
| `fk_contas_clientes` | `WARN` | **Não** |
| `fk_contas_agencias` | `CRITICAL` | Sim |
| `fk_contas_colaboradores` | `CRITICAL` | Sim |
| `fk_propostas_credito_clientes` | `WARN` | **Não** |
| `fk_propostas_credito_colaboradores` | `CRITICAL` | Sim |
| `fk_transacoes_contas` | `CRITICAL` | Sim |

### Estrutural, sobre raw

Executada por `validate_raw`, depois da promoção.

| Verificação | Bloqueia | O que detecta |
|---|---|---|
| contagem raw = origem | Sim | Perda na promoção |
| `COUNT(*)` = `COUNT(DISTINCT pk)` | Sim | Duplicação de chave |

---

## O caso do cliente 528

É a inconsistência real da origem, e o teste mais direto da política.

### O que existe

`clientes.csv` traz 998 registros com códigos de 1 a 999. O `cod_cliente =
528` **não existe**. Mas:

| Tabela | Registros apontando para 528 |
|---|---:|
| `contas` | 1 |
| `propostas_credito` | 4 |

### O que o pipeline faz

Nada além de registrar. Não inventa o cliente, não exclui a conta, não exclui
as propostas, não altera as chaves.

```
[WARN] fk_contas_clientes             invalid_rows=1  valores orfaos: ['528']
[WARN] fk_propostas_credito_clientes  invalid_rows=4  valores orfaos: ['528']
```

O pipeline termina em `SUCCESS`.

### Por que isso é a decisão certa

Um pipeline que "corrige" a origem esconde o problema. O time de dados
concluiria que a base está íntegra, e o time responsável pelo ERP nunca
saberia do defeito.

Ao preservar e registrar, o problema fica visível e endereçável na fonte.

### Consequência arquitetural

A camada `raw` **não tem foreign keys**. Com elas, os cinco registros seriam
rejeitados no `INSERT` e a promoção falharia. Ver
[ADR 0005](adr/0005-raw-sem-foreign-keys.md).

---

## Regras que o projeto deliberadamente não criou

O enunciado adverte contra inventar regras. Três casos concretos:

**`email` não é `UNIQUE`.** Quatro endereços são compartilhados por dois
clientes cada. Não existe regra de negócio proibindo, então não há
verificação bloqueante. Se houvesse, seria `INFO`.

**Sem `saldo_disponivel <= saldo_total`.** Parece razoável, mas nenhuma regra
de negócio foi fornecida. Limite de crédito, cheque especial ou bloqueio
judicial poderiam legitimamente violar essa desigualdade.

**Valores negativos em `transacoes` não são erro.** São 59.748 de 71.999.
Tratá-los como problema invalidaria a maior parte do conjunto.

**`carencia = 0` não é erro.** São 292 registros.

**Sem `CHECK` em `tipo_cliente` e `tipo_conta`.** Ambos têm valor único no
conjunto atual, mas isso é observação, não regra. Uma constraint quebraria na
primeira carga com outro tipo.

---

## Onde os resultados ficam

```sql
SELECT table_name, check_name, severity, status, invalid_rows, details, checked_at
  FROM ops.data_quality_results
 WHERE run_id = (SELECT run_id FROM ops.pipeline_runs
                  WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1)
 ORDER BY severity, table_name;
```

Auditoria por tabela, com checksum SHA-256 e contagens em cada camada:

```sql
SELECT table_name, source_file, source_checksum,
       row_count_source, row_count_staging, row_count_raw, status
  FROM ops.pipeline_table_metrics
 WHERE run_id = (SELECT run_id FROM ops.pipeline_runs
                  ORDER BY started_at DESC LIMIT 1)
 ORDER BY table_name;
```

Histórico de execuções, incluindo as que falharam:

```sql
SELECT run_id, status, pipeline_version, started_at,
       finished_at - started_at AS duracao, error_message
  FROM ops.pipeline_runs
 ORDER BY started_at DESC;
```

---

## Observabilidade

O projeto não usa Prometheus nem Grafana. Para uma prova de conceito com
sete tabelas, eles adicionariam complexidade sem benefício proporcional.

A observabilidade vem de quatro fontes:

- interface do Airflow, com o graph e o histórico de execuções;
- logs das tasks, persistidos em volume e legíveis também no host;
- `ops.pipeline_runs` e `ops.pipeline_table_metrics`;
- `ops.data_quality_results`.
