# Volume de logs do Airflow.
#
# O chart pede ReadWriteMany, porque num cluster real os componentes e os
# pods efemeros de task caem em nos diferentes. O provisionador local-path
# do Kind so suporta ReadWriteOnce, entao o PVC dinamico fica Pending e os
# pods nunca sao agendados.
#
# Solucao: PV estatico via hostPath, o mesmo padrao das fontes e das DAGs.
# Correto aqui porque o cluster tem um unico no, o que esta declarado no
# node_affinity abaixo.

resource "kubernetes_persistent_volume" "logs" {
  metadata {
    name = "banvic-airflow-logs-pv"
    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
      "banvic.io/role"               = "airflow-logs"
    }
  }

  spec {
    capacity                         = { storage = "2Gi" }
    access_modes                     = ["ReadWriteMany"]
    persistent_volume_reclaim_policy = "Retain"
    storage_class_name               = var.logs_storage_class

    persistent_volume_source {
      host_path {
        path = var.logs_node_path
        type = "Directory"
      }
    }

    node_affinity {
      required {
        node_selector_term {
          match_expressions {
            key      = "kubernetes.io/hostname"
            operator = "In"
            values   = [var.sources_node_name]
          }
        }
      }
    }
  }
}

resource "kubernetes_persistent_volume_claim" "logs" {
  metadata {
    name      = "airflow-logs"
    namespace = kubernetes_namespace.banvic.metadata[0].name
    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    access_modes       = ["ReadWriteMany"]
    storage_class_name = var.logs_storage_class
    volume_name        = kubernetes_persistent_volume.logs.metadata[0].name

    resources {
      requests = { storage = "2Gi" }
    }
  }

  wait_until_bound = true
}
