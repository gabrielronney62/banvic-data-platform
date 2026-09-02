SHELL := /bin/bash
.DEFAULT_GOAL := help
include versions.env
export

TF := terraform -chdir=infra/terraform

.PHONY: help check versions lint test cluster-up cluster-status tf-init tf-plan tf-apply infra-status destroy

help: ## Lista os targets disponiveis
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

check: ## Valida pre-requisitos e versoes do host
	@bash scripts/check_prerequisites.sh

versions: ## Exibe as versoes fixadas do projeto
	@grep -vE '^\s*(#|$$)' versions.env | sort

cluster-up: ## Cria o cluster Kind a partir de infra/kind/cluster.yaml
	@kind create cluster --config infra/kind/cluster.yaml

cluster-status: ## Mostra nos e pods do cluster
	@kubectl get nodes
	@echo
	@kubectl get pods -A

tf-init: ## Inicializa o Terraform e baixa os providers
	@$(TF) init

tf-plan: ## Mostra o plano de mudancas sem aplicar
	@$(TF) plan

tf-apply: ## Aplica a infraestrutura declarada
	@$(TF) apply

infra-status: ## Mostra namespace, PV e PVC provisionados
	@kubectl get namespace $(K8S_NAMESPACE)
	@echo
	@kubectl get pv
	@echo
	@kubectl get pvc -n $(K8S_NAMESPACE)

destroy: ## Destroi o cluster Kind por completo
	@kind delete cluster --name $(KIND_CLUSTER_NAME)

lock-images: ## Resolve tags de imagem para digests imutaveis em versions.lock
	@bash scripts/lock_images.sh

secrets: ## Cria os Secrets do Kubernetes a partir do .env local
	@bash scripts/create_secrets.sh

dw-status: ## Mostra o estado do PostgreSQL do Data Warehouse
	@kubectl get statefulset,pod,svc,pvc -n $(K8S_NAMESPACE) -l app.kubernetes.io/name=banvic-postgres

dw-psql: ## Abre um psql interativo dentro do pod do DW
	@kubectl exec -it banvic-postgres-0 -n $(K8S_NAMESPACE) -- \
	  sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

dw-schemas: ## Lista os schemas do Data Warehouse
	@kubectl exec banvic-postgres-0 -n $(K8S_NAMESPACE) -- \
	  sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -c "\dn+"'

bootstrap: ## Sobe tudo do zero: cluster, namespace, secrets e infraestrutura
	@$(MAKE) cluster-up
	@$(MAKE) tf-init
	@$(TF) apply -target=kubernetes_namespace.$(K8S_NAMESPACE) -auto-approve
	@$(MAKE) secrets
	@$(MAKE) tf-apply

db-status: ## Mostra as duas instancias PostgreSQL
	@kubectl get statefulset,pod,svc -n $(K8S_NAMESPACE) -l app.kubernetes.io/part-of=banvic-data-platform

metadata-psql: ## Abre psql no banco de metadados do Airflow
	@kubectl exec -it airflow-postgres-0 -n $(K8S_NAMESPACE) -- \
	  sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

meltano-build: ## Constroi a imagem do Meltano e injeta no cluster
	@docker build \
	  --build-arg MELTANO_VERSION=$(MELTANO_VERSION) \
	  -t $(IMAGE_MELTANO):$(IMAGE_TAG) \
	  -f images/meltano/Dockerfile meltano/
	@kind load docker-image $(IMAGE_MELTANO):$(IMAGE_TAG) --name $(KIND_CLUSTER_NAME)

meltano-run: ## Executa a carga standalone CSV -> staging
	@kubectl delete job meltano-carga-inicial -n $(K8S_NAMESPACE) --ignore-not-found
	@kubectl apply -f meltano/k8s/job-carga-standalone.yaml
	@kubectl wait --for=condition=complete --timeout=10m \
	  job/meltano-carga-inicial -n $(K8S_NAMESPACE)

staging-counts: ## Conta os registros das sete tabelas em staging
	@kubectl exec -i banvic-postgres-0 -n $(K8S_NAMESPACE) -- \
	  sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -f -' < sql/quality/staging_counts.sql

test-idempotency: ## Executa a carga duas vezes e compara as contagens
	@bash scripts/test_idempotency.sh

verify: ## Verifica se a plataforma esta operacional (rode apos reboot)
	@bash scripts/verify.sh

rebuild: ## Reconstroi a plataforma inteira do zero
	@kind delete cluster --name $(KIND_CLUSTER_NAME) 2>/dev/null || true
	@rm -f infra/terraform/terraform.tfstate infra/terraform/terraform.tfstate.backup
	@kind create cluster --config infra/kind/cluster.yaml
	@test $$(docker exec banvic-control-plane ls -1 /data/incoming | wc -l) -eq 7 \
	  || (echo "ERRO: extraMounts nao montou os 7 CSVs. Abortando." && exit 1)
	@echo "Ponte de dados validada: 7 CSVs no no."
	@$(TF) init
	@$(TF) apply -target=kubernetes_namespace.banvic -auto-approve
	@bash scripts/create_secrets.sh
	@$(TF) apply -auto-approve
	@$(MAKE) airflow-build
	@$(MAKE) airflow-build
	@bash scripts/deploy_airflow.sh
	@$(MAKE) meltano-build
	@$(MAKE) verify

ddl: ## Aplica o DDL idempotente de ops e raw
	@bash scripts/apply_ddl.sh

promote: ## Promove staging -> raw numa transacao atomica
	@bash scripts/promote.sh

raw-counts: ## Contagem e unicidade de PK das sete tabelas em raw
	@kubectl exec -i banvic-postgres-0 -n $(K8S_NAMESPACE) -- \
	  sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -f -' < sql/quality/raw_counts.sql

setup-dev: ## Cria o .venv e instala as dependencias de desenvolvimento
	@bash scripts/setup_dev.sh

test: ## Roda os testes unitarios do pacote banvic
	@.venv/bin/python -m pytest tests/unit -v

airflow-build: ## Constroi a imagem banvic-airflow e injeta no cluster
	@docker build \
	  --build-arg AIRFLOW_VERSION=$(AIRFLOW_VERSION) \
	  --build-arg PYTHON_VERSION=$(PYTHON_VERSION) \
	  --build-arg AIRFLOW_CONSTRAINTS_URL=$(AIRFLOW_CONSTRAINTS_URL) \
	  -t $(IMAGE_AIRFLOW):$(IMAGE_TAG) \
	  -f images/airflow/Dockerfile .
	@kind load docker-image $(IMAGE_AIRFLOW):$(IMAGE_TAG) --name $(KIND_CLUSTER_NAME)

test-integration: ## Testes de integracao contra o DW (exige cluster de pe)
	@.venv/bin/python -m pytest tests/integration -v -m integration

test-failure: ## Demonstra falha controlada preservando a camada raw
	@.venv/bin/python scripts/test_failure.py

test-all: ## Roda lint, unitarios, integracao, idempotencia e falha controlada
	@$(MAKE) lint
	@$(MAKE) test
	@$(MAKE) test-integration
	@$(MAKE) test-idempotency
	@$(MAKE) test-failure

lint: ## Roda o ruff em src, scripts, tests e dags
	@.venv/bin/ruff check src scripts tests airflow/dags
