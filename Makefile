SHELL := /bin/bash
.DEFAULT_GOAL := help
include versions.env
export

TF := terraform -chdir=infra/terraform

.PHONY: help check versions lint test cluster-up cluster-status tf-init tf-plan tf-apply infra-status destroy

help: ## Lista os targets disponiveis
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
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
