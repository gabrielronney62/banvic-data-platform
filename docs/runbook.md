# Runbook

Operação do dia a dia da plataforma.

---

## Retomar o trabalho

Sempre que voltar ao projeto, principalmente após reiniciar a máquina:

```bash
cd ~/projetos/banvic-data-platform
source .venv/bin/activate
set -a; source versions.lock; set +a
export TF_VAR_pg_image="$PG_IMAGE_DIGEST"
make verify
```

`Plataforma operacional` significa que pode seguir. Qualquer `[FAIL]` indica
o que fazer.

Se o `verify` acusar a ponte de dados quebrada:

```bash
make rebuild
```

---

## Encerrar a sessão

```bash
git add .
git commit -m "wip: fim da sessao"
git pull --rebase
git push
git status --short --branch     # não pode dizer "ahead"
kind delete cluster --name banvic
```

Destruir o cluster de propósito é melhor que descobrir um estado
inconsistente depois. Reconstruir leva de 8 a 12 minutos.

---

## Executar o pipeline

```bash
SC=$(kubectl get pod -n banvic -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags trigger banvic_ingestion
kubectl get pods -n banvic -w
```

Ou pela interface em `http://localhost:8080`.

---

## Alterar a DAG

Edite `airflow/dags/banvic_ingestion.py`. O arquivo chega ao cluster pelo
PVC; nenhum rebuild é necessário.

Valide antes:

```bash
python3 -m py_compile airflow/dags/banvic_ingestion.py
make lint
```

E confirme que o Airflow a carregou:

```bash
kubectl exec -n banvic "$SC" -c scheduler -- airflow dags list-import-errors
```

---

## Alterar contratos, SQL de promoção ou o pacote banvic

Esses artefatos vivem **dentro da imagem**:

```bash
make test
make airflow-build
make airflow-deploy
```

---

## Alterar o meltano.yml

```bash
make meltano-build
```

Teste sem a DAG:

```bash
make meltano-run
make staging-counts
```

---

## Rotacionar uma senha

```bash
NOVA=$(openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 28)
sed -i "s|^BANVIC_DW_PASSWORD=.*|BANVIC_DW_PASSWORD=${NOVA}|" .env
unset NOVA

bash scripts/create_secrets.sh

set -a; source .env; set +a
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c "psql -U \$POSTGRES_USER -d \$POSTGRES_DB \
    -c \"ALTER USER \$POSTGRES_USER WITH PASSWORD '$BANVIC_DW_PASSWORD';\""

kubectl rollout restart deployment -n banvic -l release=airflow
```

**Nunca** use `airflow connections get <id> -o json`: ele imprime a senha em
texto plano. Sem o `-o json` a saída já é suficiente.

---

## Consultar a auditoria

Últimas execuções:

```bash
kubectl exec -i banvic-postgres-0 -n banvic -- \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f -' <<'SQL'
SELECT run_id, status, finished_at - started_at AS duracao
  FROM ops.pipeline_runs ORDER BY started_at DESC LIMIT 5;
SQL
```

Métricas e contagens: `make raw-counts` e `make staging-counts`.

---

## Investigar uma falha

Pela interface é mais rápido: clique na task, aba **Logs**.

Pelo terminal, os logs estão no host:

```bash
TASK=promote_to_raw
LOG=$(find airflow/logs -path "*task_id=$TASK*" -name "*.log" | sort | tail -1)
python3 -c "
import json
for linha in open('$LOG', encoding='utf-8'):
    try: d = json.loads(linha)
    except Exception: continue
    if d.get('level') == 'error':
        for e in d.get('error_detail', []):
            print(e.get('exc_type'), ':', e.get('exc_value'))
            for f in e.get('frames', [])[-5:]:
                print('   ', f['filename'].split('/')[-1], f['lineno'], f['name'])
"
```

---

## Rodar a suíte de testes

```bash
make test-all
```

Ou individualmente: `make lint`, `make test`, `make test-integration`,
`make test-idempotency`, `make test-failure`.

---

## Destruir e reconstruir

```bash
make destroy
```

```bash
set -a; source versions.lock; set +a
export TF_VAR_pg_image="$PG_IMAGE_DIGEST"
make rebuild
make ddl
```

Os CSVs e o `.env` permanecem intactos no host.
