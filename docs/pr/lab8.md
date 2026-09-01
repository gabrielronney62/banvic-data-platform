## O que foi feito

- Pacote `banvic` em `src/`, com tres modulos:
  - `contracts.py`: carrega o YAML em objetos tipados, rejeitando contrato
    malformado no carregamento e nao na execucao
  - `audit.py`: SHA-256 em blocos, contagem de linhas com csv.reader,
    leitura de cabecalho
  - `validation.py`: validacoes estruturais retornando CheckResult, que
    mapeia direto para ops.data_quality_results
- 23 testes unitarios cobrindo a lista da secao 22: checksum, contratos,
  schema, PK nula, PK duplicada, arquivo vazio, arquivo ausente, row count
- Imagem `banvic-airflow:0.1.0` com o pacote e os providers, usando o
  arquivo de constraints oficial do Airflow 3.2.2
- `pyproject.toml` e `scripts/setup_dev.sh` para o ambiente local

## Decisoes

**Codigo Python antes da DAG.** A logica de checksum, contratos e validacao
vive em modulos testaveis com pytest, fora do Airflow. A DAG vira
orquestracao fina. O ciclo de correcao passa de minutos para segundos.

**A severidade esta no tipo, nao no if.** `CheckResult.blocks_promotion` so
e verdadeiro quando status FAIL e severidade CRITICAL. Row count divergente
e WARN e nao bloqueia; PK duplicada e CRITICAL e bloqueia. A separacao da
secao 11 fica num lugar so.

**Constraints em vez de versoes fixas nos requirements.** O arquivo de
constraints do Airflow 3.2.2 pina providers e dependencias transitivas de
forma coerente com o core. Fixar dezenas de versoes a mao brigaria com ele.

**venv obrigatorio.** Ubuntu 24.04 marca o Python do sistema como
externally-managed (PEP 668). `scripts/setup_dev.sh` cria o .venv e instala
o pacote em modo editavel.

## Evidencia

    make test          # 23 passed
    make airflow-build

Executado contra as fontes reais, o pacote emite 35 verificacoes (5 por
tabela), todas PASS, com os checksums SHA-256 batendo com a auditoria
inicial.

Imagem verificada: `uid=50000(airflow)`, nao-root; nenhum CSV do BanVic
dentro da imagem.

Dentro do cluster:

    kubectl exec ... dag-processor -- python -c "import banvic; ..."
    banvic 0.1.0
