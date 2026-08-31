variable "kubeconfig_path" {
  description = "Caminho do kubeconfig usado para acessar o cluster."
  type        = string
  default     = "~/.kube/config"
}

variable "kube_context" {
  description = "Contexto do kubeconfig. Trava o alvo do apply."
  type        = string
  default     = "kind-banvic"
}

variable "namespace" {
  description = "Namespace dedicado da plataforma BanVic."
  type        = string
  default     = "banvic"
}

variable "sources_node_path" {
  description = "Caminho das fontes CSV dentro do no do Kind, exposto por extraMounts."
  type        = string
  default     = "/data/incoming"
}

variable "sources_node_name" {
  description = "Nome do no que possui o mount das fontes."
  type        = string
  default     = "banvic-control-plane"
}

variable "sources_storage_class" {
  description = "StorageClass dedicada. Nao existe provisionador: o bind e estatico e explicito."
  type        = string
  default     = "banvic-sources"
}

variable "sources_capacity" {
  description = "Capacidade declarada do volume das fontes."
  type        = string
  default     = "1Gi"
}

variable "pg_image" {
  description = "Imagem do PostgreSQL do DW, referenciada por digest imutavel."
  type        = string
}

variable "dw_secret_name" {
  description = "Nome do Secret criado por scripts/create_secrets.sh."
  type        = string
  default     = "banvic-dw-credentials"
}

variable "dw_storage_size" {
  description = "Tamanho do volume de dados do PostgreSQL."
  type        = string
  default     = "2Gi"
}

variable "dw_nodeport" {
  description = "NodePort do PostgreSQL. Mapeado para 15432 no host pelo cluster.yaml."
  type        = number
  default     = 30432
}
