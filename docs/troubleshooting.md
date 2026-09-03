# Troubleshooting

Problemas encontrados durante a construção da plataforma, com sintoma, causa
e solução. Todos foram reproduzidos no ambiente alvo: Windows 11, WSL2,
Docker Desktop e Kind.

---

## 1. O tap-csv reporta arquivo inexistente, mas os arquivos estão lá

**Sintoma**

```
Exception: File path does not exist /opt/banvic/incoming/agencias.csv
```

E ao mesmo tempo:

```bash
ls -1 data/incoming/*.csv | wc -l    # 7
```

**Causa**

Os `extraMounts` do Kind são bind mounts aplicados na **criação** do
container do nó. Após reiniciar a máquina, `docker start banvic-control-plane`
sobe o container mas não restabelece os mounts. O diretório `/data/incoming`
é recriado vazio dentro do nó.

**Diagnóstico**

```bash
make verify
```

Ou manualmente, testando as três camadas:

```bash
ls -1 data/incoming/*.csv | wc -l                          # host
docker exec banvic-control-plane ls -1 /data/incoming      # nó
kubectl run t -n banvic --rm -i --restart=Never --image=busybox:1.37 \
  --overrides='{"spec":{"containers":[{"name":"t","image":"busybox:1.37","command":["ls","/mnt/f"],"volumeMounts":[{"name":"f","mountPath":"/mnt/f"}]}],"volumes":[{"name":"f","persistentVolumeClaim":{"claimName":"banvic-sources-pvc"}}]}}'
```

Se o host mostra 7 e o nó mostra 0, é este problema.

**Solução**

Não há como reparar um `extraMounts` em cluster já criado. Recrie:

```bash
set -a; source versions.lock; set +a
export TF_VAR_pg_image="$PG_IMAGE_DIGEST"
make rebuild
```

O `make rebuild` **aborta** se os sete arquivos não chegarem ao nó, em vez de
provisionar tudo sobre uma base quebrada.

**Prevenção**

Encerre o cluster de forma limpa antes de desligar a máquina:

```bash
kind delete cluster --name banvic
```

Ou rode `make verify` sempre que voltar ao projeto.

---

## 2. dag-processor em CrashLoopBackOff com FileNotFoundError

**Sintoma**

```
FileNotFoundError: [Errno 2] No such file or directory:
'/opt/airflow/logs/dag_processor/<data>/dags-folder/<dag>.py.log'
```

O pod fica em `1/2 CrashLoopBackOff`, e `kubectl exec` responde
`container not found`.

**Causa**

O dag-processor cria uma árvore de diretórios dentro do volume de logs para
cada arquivo de DAG parseado. O volume vem de um `hostPath` cujo dono é o
usuário do host, e o processo roda como uid 50000.

Só se manifesta quando existe ao menos um arquivo de DAG. Com a pasta vazia,
nenhum log precisa ser criado e o pod sobe normalmente.

**Solução**

```bash
sudo chown -R 50000:0 airflow/logs
sudo chmod -R 775 airflow/logs
kubectl delete pod -n banvic -l component=dag-processor
kubectl rollout status deployment/airflow-dag-processor -n banvic --timeout=5m
```

Confirme que o Airflow passou a escrever:

```bash
ls -laR airflow/logs/ | head
```

Deve aparecer `dag_processor/<data>/dags-folder/`.

---

## 3. FileSensor falha com "The conn_id fs_default isn't defined"

**Sintoma**

```
AirflowNotFoundException: The conn_id `fs_default` isn't defined
```

**Causa**

O Airflow 3 não cria conexões padrão. Toda a documentação e a maior parte dos
exemplos na internet assumem o comportamento do Airflow 2, onde `fs_default`
existia após a inicialização do banco.

**Solução**

Declare a conexão como variável de ambiente no `values.yaml`:

```yaml
env:
  - name: AIRFLOW_CONN_FS_DEFAULT
    value: '{"conn_type": "fs", "extra": {"path": "/"}}'
```

Não há credencial envolvida: é apenas um caminho no filesystem.

Verifique:

```bash
SC=$(kubectl get pod -n banvic -l component=scheduler -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n banvic "$SC" -c scheduler -- airflow connections get fs_default
```

---

## 4. Task falha com "The key 'run_id' in args is a part of kwargs and therefore reserved"

**Sintoma**

```
ValueError: The key 'run_id' in args is a part of kwargs and therefore reserved.
```

**Causa**

`run_id` é chave do contexto do Airflow. No Task SDK do Airflow 3, ela não
pode ser nome de parâmetro de uma task decorada com `@task`.

**Solução**

Renomeie o parâmetro. Ler `run_id` do contexto como variável local continua
permitido:

```python
@task
def start_pipeline_run(**context) -> str:
    run_id = context["run_id"]   # variável local: OK
    ...

@task
def audit_sources(pipeline_run_id: str) -> None:   # parâmetro: renomeado
    ...
```

---

## 5. Promoção falha com KeyError num nome de coluna

**Sintoma**

```
KeyError: 'nome'
```

O nome citado é uma coluna que existe nas tabelas, o que faz parecer erro de
schema.

**Causa**

O psycopg2 varre a **string inteira** do SQL procurando marcadores no formato
`%(nome)s`, incluindo o interior de comentários. Um comentário explicativo
como:

```sql
-- Parametros nomeados no formato pyformat (%(nome)s):
```

faz o psycopg2 esperar uma chave `nome` no dicionário de parâmetros.

**Solução**

Nenhum `%(...)s` pode aparecer no arquivo além dos parâmetros reais. Há um
teste unitário que garante isso:

```python
marcadores = set(re.findall(r"%\((\w+)\)s", sql))
assert marcadores == {"run_id", "pipeline_version"}
```

---

## 6. Coluna de checksum vazia em ops.pipeline_table_metrics

**Sintoma**

As contagens estão corretas, mas `source_checksum` aparece vazio.

**Causa**

`audit_sources` grava o checksum. As etapas seguintes (`validate_staging` e
`validate_raw`) reescrevem a mesma linha para acrescentar contagens, mas não
recalculam o hash e enviam string vazia. O `ON CONFLICT ... DO UPDATE`
sobrescrevia o valor.

**Solução**

`COALESCE` combinado com `NULLIF` no UPSERT:

```sql
SET source_checksum = COALESCE(NULLIF(EXCLUDED.source_checksum, ''),
                               ops.pipeline_table_metrics.source_checksum)
```

---

## 7. helm upgrade falha com "additional properties not allowed"

**Sintoma**

```
Error: values don't meet the specifications of the schema(s):
- at '/createUserJob': additional properties 'password', 'username' not allowed
```

**Causa**

O chart do Airflow tem um `values.schema.json` que valida a estrutura. Chaves
mudam de lugar entre versões, e o changelog nem sempre mostra a estrutura
final.

**Solução**

Consulte o schema em vez de adivinhar:

```bash
helm show values apache-airflow/airflow --version 1.22.0 > /tmp/ref.yaml
sed -n '/^createUserJob:/,/^[a-z]/p' /tmp/ref.yaml
```

E valide antes de instalar, com os mesmos `--set` do comando real:

```bash
helm template airflow apache-airflow/airflow --version 1.22.0 \
  --values infra/helm/airflow-values.yaml --set ... > /dev/null
```

O `scripts/deploy_airflow.sh` já faz essa validação.

---

## 8. PVC de logs em Pending, pods em FailedScheduling

**Sintoma**

```
failed to provision volume with StorageClass "standard":
NodePath only supports ReadWriteOnce and ReadWriteOncePod access modes
```

Os quatro componentes do Airflow ficam em `Pending` com
`running PreBind plugin "VolumeBinding"`.

**Causa**

O chart cria o PVC de logs com `ReadWriteMany`. O provisionador `local-path`
do Kind só suporta `ReadWriteOnce`.

**Solução**

PersistentVolume estático via `hostPath`, referenciado por
`logs.persistence.existingClaim`. Ver
[ADR 0004](adr/0004-volumes-estaticos-no-kind.md).

---

## 9. pip install recusado no Ubuntu 24.04

**Sintoma**

```
error: externally-managed-environment
```

**Causa**

Ubuntu 24.04 marca o Python do sistema como gerenciado pelo SO (PEP 668) e
recusa instalação fora de um ambiente virtual. É o comportamento correto.

**Solução**

```bash
make setup-dev
```

Não use `--break-system-packages`: misturar dependências do projeto com as do
sistema operacional causa problemas difíceis de diagnosticar depois.

---

## 10. Pods em Pending por falta de memória

**Sintoma**

Pods em `Pending` prolongado, ou `Evicted` durante a execução.

**Diagnóstico**

```bash
docker info --format 'Mem={{.MemTotal}}'
kubectl describe node banvic-control-plane | sed -n '/Allocated resources/,/^Events/p'
```

**Causa**

Airflow 3 sobe quatro processos permanentes, mais dois PostgreSQL, mais um
pod por task. Abaixo de 8 GB o cluster fica instável.

**Solução**

Crie `C:\Users\<usuario>\.wslconfig`:

```ini
[wsl2]
memory=10GB
processors=8
swap=2GB
```

E no PowerShell:

```powershell
wsl --shutdown
```

Atenção ao nome do arquivo: precisa ser exatamente `.wslconfig`, sem
extensão. O Explorer do Windows esconde extensões conhecidas e salva
`.wslconfig.txt` sem avisar. Crie pelo PowerShell com `-Encoding ASCII`.

---

## 11. Arquivos truncados ao colar no terminal WSL2

**Sintoma**

Um arquivo criado por heredoc sai com linhas repetidas, embaralhadas ou
faltando o final. O `bash -n` pode aprovar a sintaxe se a corrupção cair em
comentários.

**Causa**

O buffer de colagem do terminal WSL2 se atropela em blocos grandes.

**Solução**

Sempre valide o arquivo depois de criá-lo:

| Tipo | Validação |
|---|---|
| YAML | `python3 -c "import yaml; yaml.safe_load(open('X'))"` |
| TOML | `python3 -c "import tomllib; tomllib.load(open('X','rb'))"` |
| Python | `python3 -m py_compile X` |
| Shell | `bash -n X` mais `cat X` |
| Makefile | `make -n <target>` |
| SQL | executar contra o banco |

Para arquivos longos, prefira transferir por download e conferir com
`md5sum`.
