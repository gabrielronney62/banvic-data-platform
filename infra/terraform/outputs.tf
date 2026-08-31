output "namespace" {
  description = "Namespace provisionado da plataforma."
  value       = kubernetes_namespace.banvic.metadata[0].name
}

output "sources_pv_name" {
  description = "Nome do PersistentVolume das fontes CSV."
  value       = kubernetes_persistent_volume.sources.metadata[0].name
}

output "sources_pvc_name" {
  description = "Nome do PVC das fontes, referenciado pelos pods."
  value       = kubernetes_persistent_volume_claim.sources.metadata[0].name
}

output "dags_pvc_name" {
  description = "Nome do PVC das DAGs, consumido pelo chart do Airflow."
  value       = kubernetes_persistent_volume_claim.dags.metadata[0].name
}

output "dw_dns" {
  description = "FQDN interno do Data Warehouse."
  value       = module.dw.dns
}

output "dw_host_port" {
  description = "Porta no host Windows para clientes externos."
  value       = 15432
}

output "metadata_dns" {
  description = "FQDN interno do banco de metadados do Airflow."
  value       = module.airflow_metadata.dns
}

output "dw_image" {
  description = "Imagem PostgreSQL efetivamente aplicada."
  value       = var.pg_image
}
