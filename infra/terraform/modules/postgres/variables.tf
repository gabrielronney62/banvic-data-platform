variable "name" {
  description = "Nome base dos recursos. Ex.: banvic-postgres, airflow-postgres."
  type        = string
}

variable "namespace" {
  description = "Namespace onde a instancia sera criada."
  type        = string
}

variable "image" {
  description = "Imagem do PostgreSQL, referenciada por digest imutavel."
  type        = string
}

variable "secret_name" {
  description = "Secret com POSTGRES_DB, POSTGRES_USER e POSTGRES_PASSWORD."
  type        = string
}

variable "storage_size" {
  description = "Tamanho do volume de dados."
  type        = string
  default     = "2Gi"
}

variable "storage_class" {
  description = "StorageClass do volume de dados."
  type        = string
  default     = "standard"
}

variable "node_port" {
  description = "NodePort para acesso externo. Null mantem o Service como ClusterIP."
  type        = number
  default     = null
}

variable "init_sql" {
  description = "Mapa nome-do-arquivo => conteudo SQL. Executado apenas na primeira inicializacao."
  type        = map(string)
  default     = {}
}

variable "resources_requests" {
  description = "Requisicoes de CPU e memoria do container."
  type        = map(string)
  default     = { cpu = "100m", memory = "256Mi" }
}

variable "resources_limits" {
  description = "Limites de memoria do container."
  type        = map(string)
  default     = { memory = "1Gi" }
}
