# Checklist de evidências

Comandos que comprovam cada requisito do desafio. Todos produzem saída a
partir do estado real do sistema; nenhum valor é escrito manualmente.

**Nenhum comando desta lista exibe senha.**

---

## 1. Ambiente e ferramentas

```bash
docker version | head -3
kind version
kubectl version --client
helm version
terraform version
```

Ou, de uma vez:

```bash
make check
```

Comprova versões, memória disponível, tipo do filesystem e presença dos sete
arquivos de origem.

---

## 2. Infraestrutura provisionada

```bash
kubectl get nodes
kubectl get pods -n banvic
kubectl get svc -n banvic
kubectl get pvc -n banvic
kubectl get pv
```

**Esperado:** um nó `Ready`; seis pods `Running`; `banvic-postgres` como
NodePort e `airflow-postgres` como ClusterIP; cinco PVCs `Bound`.

### Terraform

```bash
terraform -chdir=infra/terraform plan
```

**Esperado:** `No changes. Your infrastructure matches the configuration.`

O mesmo módulo instanciado duas vezes:

```bash
terraform -chdir=infra/terraform state list | grep module
```

---

## 3. Imagens próprias

```bash
docker images banvic-airflow banvic-meltano
docker exec banvic-control-plane crictl images | grep banvic
```

Usuário não-root em ambas:

```bash
docker run --rm --entrypoint id banvic-airflow:0.1.0
docker run --rm --entrypoint id banvic-meltano:0.1.0
```

**Esperado:** `uid=50000(airflow)` e `uid=1000(meltano)`.

Nenhum dado pessoal dentro das imagens:

```bash
docker run --rm --entrypoint sh banvic-airflow:0.1.0 -c \
  'find / -name "clientes.csv" -o -name "transacoes.csv" 2>/dev/null | head; echo "busca concluida"'
```

**Esperado:** apenas `busca concluida`.

---

## 4. Airflow

```bash
helm list -n banvic
```

**Esperado:** release `airflow`, status `deployed`, chart `airflow-1.22.0`,
app version `3.2.2`.

```bash
SC=$(kubectl get pod -n banvic -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n banvic "$SC" -c scheduler -- airflow config get-value core executor
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags list | grep banvic
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags list-import-errors
```

**Esperado:** `KubernetesExecutor`; `banvic_ingestion` listada; nenhum erro
de import.

Interface acessível em `http://localhost:8080`, sem `port-forward`:

```bash
kubectl get svc -n banvic airflow-api-server
```

**Esperado:** `NodePort`, `8080:30080/TCP`.

---

## 5. Sensor e execução da DAG

```bash
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags trigger banvic_ingestion
kubectl get pods -n banvic -w
```

**Esperado:** pods efêmeros nascendo e morrendo, um por task, incluindo o pod
do Meltano durante `load_staging`.

No graph da interface: sete `FileSensor` no TaskGroup `wait_for_sources`,
`load_staging` identificado como `KubernetesPodOperator`, e `finish_failed`
em `skipped` quando tudo passa.

---

## 6. Meltano

```bash
docker run --rm --entrypoint sh banvic-meltano:0.1.0 -c \
  'cd /project && meltano invoke tap-csv --version && meltano invoke target-postgres --version'
```

Versões fixadas:

```bash
grep -E "TAP_CSV|TARGET_POSTGRES|MELTANO_VERSION" versions.env
```

**Esperado:** `tap-csv` pinado por tag Git, `target-postgres` por versão
exata.

---

## 7. Sete tabelas com contagens corretas

```bash
make staging-counts
make raw-counts
```

**Esperado**, com `linhas` igual a `pks_distintas`:

| tabela | registros |
|---|---:|
| agencias | 10 |
| clientes | 998 |
| colaborador_agencia | 100 |
| colaboradores | 100 |
| contas | 999 |
| propostas_credito | 2.000 |
| transacoes | 71.999 |

Tipos aplicados pelos casts:

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT column_name, data_type
  FROM information_schema.columns
 WHERE table_schema = 'raw' AND table_name = 'clientes'
 ORDER BY ordinal_position;
SQL
```

**Esperado:** `cod_cliente` como `bigint`, `data_inclusao` como
`timestamp with time zone`, `data_nascimento` como `date`, e `cpfcnpj` e
`cep` ainda como `text`.

---

## 8. Auditoria preenchida

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT run_id, status, pipeline_version, finished_at - started_at AS duracao
  FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 5;
SQL
```

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT table_name, row_count_source, row_count_staging, row_count_raw,
       left(source_checksum, 16) AS checksum
  FROM ops.pipeline_table_metrics
 WHERE run_id = (SELECT run_id FROM ops.pipeline_runs
                  WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1)
 ORDER BY table_name;
SQL
```

**Esperado:** as três contagens iguais em cada linha, e checksum SHA-256
preenchido.

O checksum gravado bate com o arquivo em disco? O teste de integração
comprova:

```bash
.venv/bin/python -m pytest tests/integration/test_pipeline.py \
  -k checksums_batem -v -m integration
```

---

## 9. Data Quality e o cliente 528

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT table_name, check_name, severity, status, invalid_rows,
       left(details, 70) AS detalhe
  FROM ops.data_quality_results
 WHERE run_id = (SELECT run_id FROM ops.pipeline_runs
                  WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1)
   AND status <> 'PASS'
 ORDER BY severity, table_name;
SQL
```

**Esperado:** duas linhas `WARN`, `fk_contas_clientes` com 1 e
`fk_propostas_credito_clientes` com 4, ambas citando o valor 528. O pipeline
terminou em `SUCCESS`.

A inconsistência preservada na camada `raw`:

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT 'clientes'          AS tabela, count(*) FROM raw.clientes          WHERE cod_cliente = 528
UNION ALL SELECT 'contas',            count(*) FROM raw.contas            WHERE cod_cliente = 528
UNION ALL SELECT 'propostas_credito', count(*) FROM raw.propostas_credito WHERE cod_cliente = 528;
SQL
```

**Esperado:** `0`, `1`, `4`.

Ausência de foreign keys, que é o que permite isso:

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT count(*) AS fks_em_raw
  FROM information_schema.table_constraints
 WHERE table_schema = 'raw' AND constraint_type = 'FOREIGN KEY';
SQL
```

**Esperado:** `0`.

---

## 10. Idempotência

```bash
make test-idempotency
```

**Esperado:** as duas listagens de contagens idênticas, e
`IDEMPOTENCIA: OK`.

Pela DAG, disparando duas vezes e comparando:

```bash
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags trigger banvic_ingestion
# aguardar
make raw-counts
```

---

## 11. Tratamento de falhas

```bash
make test-failure
```

**Esperado:** Cenário A com a validação estrutural bloqueando um arquivo
ausente; Cenário B com a promoção abortando em
`invalid input syntax for type date` e as contagens de `raw` intactas antes
e depois; resumo final com `OK` nos dois.

---

## 12. Segurança

```bash
kubectl get secrets -n banvic
```

**Esperado:** os Secrets listados, sem valores.

```bash
set -a; source .env; set +a
git grep -I "$BANVIC_DW_PASSWORD" -- . && echo "VAZAMENTO" || echo "OK: nenhuma ocorrencia"
grep -c "$BANVIC_DW_PASSWORD" infra/terraform/terraform.tfstate 2>/dev/null || echo "OK: nenhuma ocorrencia"
```

**Esperado:** `OK` nas duas. A segunda comprova a decisão do
[ADR 0003](adr/0003-secrets-fora-do-terraform.md).

```bash
git check-ignore -v .env infra/terraform/terraform.tfstate
git ls-files | grep -E "^data/incoming/.*\.csv$" || echo "OK: nenhum CSV versionado"
```

---

## 13. Testes

```bash
make test-all
```

**Esperado, em sequência:**

```
All checks passed!                                    (ruff)
47 passed                                             (unitários)
20 passed                                             (integração)
IDEMPOTENCIA: OK -- contagens identicas               (idempotência)
Cenario A: OK   Cenario B: OK                         (falha controlada)
```

---

## 14. Reprodutibilidade do zero

```bash
set -a; source versions.lock; set +a
export TF_VAR_pg_image="$PG_IMAGE_DIGEST"
make rebuild
make ddl
```

O `make rebuild` destrói o cluster, recria, **aborta se os sete CSVs não
chegarem ao nó**, provisiona com Terraform, cria os Secrets, instala o
Airflow, constrói as imagens e valida.

Versões fixadas:

```bash
make versions
cat versions.lock
```

**Esperado:** nenhuma tag flutuante; digests imutáveis no `versions.lock`.
