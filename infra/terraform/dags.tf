# Volume das DAGs.
#
# Bind estatico pelo mesmo motivo do volume de fontes: queremos que o PVC
# case com ESTE volume, e nao que um provisionador crie um vazio.
#
# Diferente das fontes, aqui o acesso e de leitura e escrita: o dag-processor
# grava bytecode compilado (__pycache__) junto aos arquivos.

resource "kubernetes_persistent_volume" "dags" {
  metadata {
    name = "banvic-dags-pv"
    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
      "banvic.io/role"               = "dag-files"
    }
  }

  spec {
    capacity                         = { storage = "1Gi" }
    access_modes                     = ["ReadWriteMany"]
    persistent_volume_reclaim_policy = "Retain"
    storage_class_name               = var.dags_storage_class

    persistent_volume_source {
      host_path {
        path = var.dags_node_path
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

resource "kubernetes_persistent_volume_claim" "dags" {
  metadata {
    name      = "banvic-dags-pvc"
    namespace = kubernetes_namespace.banvic.metadata[0].name
    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    access_modes       = ["ReadWriteMany"]
    storage_class_name = var.dags_storage_class
    volume_name        = kubernetes_persistent_volume.dags.metadata[0].name

    resources {
      requests = { storage = "1Gi" }
    }
  }

  wait_until_bound = true
}
