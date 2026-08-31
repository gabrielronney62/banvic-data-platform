output "namespace" {
  description = "Namespace provisionado da plataforma."
  value       = kubernetes_namespace.banvic.metadata[0].name
}

output "sources_pv_name" {
  description = "Nome do PersistentVolume das fontes CSV."
  value       = kubernetes_persistent_volume.sources.metadata[0].name
}

output "sources_pvc_name" {
  description = "Nome do PVC que os pods devem referenciar."
  value       = kubernetes_persistent_volume_claim.sources.metadata[0].name
}

output "sources_node_path" {
  description = "Caminho das fontes dentro do no do Kind."
  value       = var.sources_node_path
}

output "dw_service_dns" {
  description = "DNS interno do PostgreSQL do DW, usado pelos pods."
  value       = "${kubernetes_service.postgres.metadata[0].name}.${kubernetes_namespace.banvic.metadata[0].name}.svc.cluster.local"
}

output "dw_host_port" {
  description = "Porta no host Windows para clientes externos como DBeaver."
  value       = 15432
}

output "dw_image" {
  description = "Imagem do PostgreSQL efetivamente aplicada."
  value       = var.pg_image
}
