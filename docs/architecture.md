# Arquitetura

Detalhamento do desenho da plataforma, das camadas de dados e do fluxo de
execução.

---

## Camadas físicas

```
Windows 11
   │
   ├── WSL2 (Ubuntu 24.04, ext4)          ← terminal, projeto, CSVs
   │     │
   │     └── Docker Desktop (daemon)      ← motor de containers
   │           │
   │           └── Kind: 1 nó             ← container que finge ser máquina
   │                 │
   │                 └── Kubernetes       ← namespace banvic
   │                       ├── Airflow 3.2.2 (4 componentes + pods efêmeros)
   │                       ├── PostgreSQL banvic_dw
   │                       └── PostgreSQL airflow (metadados)
```

O projeto precisa estar em `ext4`. Sobre `9p`/`drvfs` os bind mounts do Kind
se comportam de forma imprevisível.

---

## A ponte de dados

Os CSVs atravessam três camadas até chegarem ao pod que os lê:

```
~/projetos/banvic-data-platform/data/incoming/     host (ext4)
        │
        │  extraMounts do cluster.yaml
        ▼
/data/incoming                                     dentro do nó Kind
        │
        │  PersistentVolume banvic-sources-pv (hostPath, ROX, Retain)
        │  PersistentVolumeClaim banvic-sources-pvc
        ▼
/opt/banvic/incoming                               dentro do pod
```

O `extraMounts` só é aplicado na **criação** do container do nó. Essa é a
origem do problema mais comum do projeto, documentado em
[troubleshooting.md](troubleshooting.md).

Três volumes usam esse padrão: fontes (somente leitura), DAGs (leitura e
escrita, porque o dag-processor grava bytecode) e logs (leitura e escrita,
`ReadWriteMany`). Ver [ADR 0004](adr/0004-volumes-estaticos-no-kind.md).

Dois volumes usam provisionamento dinâmico com a StorageClass `standard`: os
dados dos dois PostgreSQL.

---

## Camadas de dados

### staging

Área temporária de carga. Recebe o Meltano com **todas as colunas em TEXT**,
espelhando fielmente o arquivo de origem.

Pode ser recriada entre execuções. O `load_method: overwrite` do
`target-postgres` substitui o conteúdo a cada carga, usando tabela temporária
com swap — o que já torna a carga atômica por si.

Recebe também as colunas de metadados do tap: `_sdc_source_file`,
`_sdc_source_lineno` e `_sdc_extracted_at`.

### raw

Cópia centralizada da origem, com tipos nativos aplicados por casts
explícitos em SQL.

Preserva os registros como recebidos: sem foreign keys, sem correção
silenciosa, sem arredondamento. Acrescenta cinco colunas de linhagem.

### ops

Estrutura operacional, com três tabelas:

| Tabela | Conteúdo |
|---|---|
| `pipeline_runs` | Uma linha por execução da DAG |
| `pipeline_table_metrics` | Checksum SHA-256 e contagens por tabela e camada |
| `data_quality_results` | Resultados das verificações, com severidade |

O DDL é idempotente (`CREATE TABLE IF NOT EXISTS`) e aplicado por
`make ddl`, fora do entrypoint do container. O entrypoint executa apenas na
primeira inicialização do volume, o que impediria evoluir o esquema sem
destruir o banco.

---

## Separação dos dois PostgreSQL

O projeto tem duas instâncias, provisionadas pelo **mesmo módulo Terraform**
com configurações diferentes:

| Instância | Conteúdo | Exposição | Volume |
|---|---|---|---|
| `banvic-postgres` | Data Warehouse | NodePort 30432 → host 15432 | 2Gi |
| `airflow-postgres` | Metadados do Airflow | ClusterIP apenas | 1Gi |

Responsabilidades e ciclos de vida distintos. Perder o banco de metadados
custa o histórico de execuções; perder o DW custa os dados ingeridos.

O banco de metadados não é exposto fora do cluster: menos superfície.

O chart do Airflow traz um PostgreSQL embutido, mas ele passou a usar
`bitnamilegacy/postgresql` após a mudança de registry da Bitnami. Provisionar
com o módulo próprio elimina essa dependência.

---

## O pipeline

### 1. wait_for_sources

TaskGroup com um `FileSensor` por arquivo. Sete tasks, para que o graph
mostre exatamente qual arquivo está faltando.

Modo `reschedule`: o worker é liberado entre as verificações, em vez de
manter um pod dormindo. `poke_interval` de 15 segundos, timeout de 10
minutos.

### 2. start_pipeline_run

Abre o registro em `ops.pipeline_runs` com status `RUNNING`. Idempotente por
`run_id`, com `ON CONFLICT DO UPDATE`, para que reexecutar a task não quebre
por chave duplicada.

### 3. audit_sources

Calcula SHA-256 em blocos de 1 MiB e conta registros com `csv.reader`.
Grava em `ops.pipeline_table_metrics` e devolve o mapa de contagens para as
etapas seguintes.

### 4. validate_contracts

Executa as validações estruturais contra os contratos declarativos. Grava
todos os resultados em `ops.data_quality_results` e falha a task apenas se
houver resultado `CRITICAL` com status `FAIL`.

### 5. load_staging

`KubernetesPodOperator` criando um pod com a imagem `banvic-meltano`. O pod
monta o PVC das fontes, recebe as credenciais por `secretKeyRef`, executa
`meltano run tap-csv target-postgres` e morre.

`imagePullPolicy: Never` força o uso da imagem injetada por `kind load`.

### 6. validate_staging

Compara a contagem da origem com a de `staging`, tabela por tabela.
Divergência aqui é falha técnica e bloqueia a promoção.

### 7. run_data_quality

Verifica os oito relacionamentos declarados nos contratos, com a severidade
lida do próprio contrato. Registra os resultados e falha apenas em
`CRITICAL`.

### 8. promote_to_raw

Executa `sql/promotion/promote_raw.sql` numa única transação:

```
BEGIN (implícito no psycopg2)
  TRUNCATE raw.<tabela>
  INSERT INTO raw SELECT <casts explícitos> FROM staging
  ... 7 vezes
COMMIT
```

Se qualquer cast falhar, o `ROLLBACK` devolve inclusive os `TRUNCATE`.

### 9. validate_raw

Confere contagens e unicidade de chave primária em `raw`, e completa as
métricas em `ops`.

### 10. finish_success / finish_failed

Duas tasks com `trigger_rule` distintos. A de sucesso usa `all_success`; a de
falha usa `one_failed` e depende de todas as etapas anteriores.

Garante que `ops.pipeline_runs` seja sempre fechado. Sem isso, uma execução
com erro ficaria eternamente em `RUNNING` na auditoria.

---

## Onde vive cada artefato

A distinção importa para saber o que exige rebuild de imagem:

| Artefato | Onde vive | Alterar exige |
|---|---|---|
| DAG | PVC `banvic-dags-pvc` | Nada, reflete direto |
| Contratos | **Dentro da imagem** | `make airflow-build` |
| SQL de promoção | **Dentro da imagem** | `make airflow-build` |
| Pacote `banvic` | **Dentro da imagem** | `make airflow-build` |
| `meltano.yml` | **Dentro da imagem** | `make meltano-build` |
| Fontes CSV | PVC `banvic-sources-pvc` | Nada |
| Logs | PVC `airflow-logs` | Nada |

Contratos e SQL entram na imagem de propósito: são código do pipeline, não
configuração de runtime. Alterá-los exige rebuild e nova tag, o que preserva
a rastreabilidade.

---

## Reprodutibilidade

Três mecanismos, em camadas:

**`versions.env`** declara as versões de todas as ferramentas e imagens.
Nenhuma tag flutuante.

**`versions.lock`** guarda os digests imutáveis das imagens base, resolvidos
por `make lock-images` e versionados no Git. O Terraform consome o digest,
nunca a tag.

**`.terraform.lock.hcl`** fixa a versão e os hashes criptográficos do
provider Kubernetes, garantindo que outra pessoa provisione com exatamente o
mesmo plugin.

O `make rebuild` reconstrói tudo do zero e **aborta** se os sete arquivos não
chegarem ao nó, aplicando o princípio de fail fast ao próprio deploy.
