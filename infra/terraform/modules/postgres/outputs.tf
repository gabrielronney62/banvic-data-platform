output "service_name" {
  description = "Nome do Service da instancia."
  value       = kubernetes_service.this.metadata[0].name
}

output "dns" {
  description = "FQDN interno da instancia no cluster."
  value       = "${kubernetes_service.this.metadata[0].name}.${var.namespace}.svc.cluster.local"
}

output "statefulset_name" {
  description = "Nome do StatefulSet, util para kubectl exec."
  value       = kubernetes_stateful_set.this.metadata[0].name
}
