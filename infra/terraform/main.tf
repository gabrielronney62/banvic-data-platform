resource "kubernetes_namespace" "banvic" {
  metadata {
    name = var.namespace

    labels = {
      "app.kubernetes.io/name"       = "banvic"
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }
}

resource "kubernetes_persistent_volume" "sources" {
  metadata {
    name = "banvic-sources-pv"

    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
      "banvic.io/role"               = "source-files"
    }
  }

  spec {
    capacity = {
      storage = var.sources_capacity
    }

    access_modes                     = ["ReadOnlyMany"]
    persistent_volume_reclaim_policy = "Retain"
    storage_class_name               = var.sources_storage_class

    persistent_volume_source {
      host_path {
        path = var.sources_node_path
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

resource "kubernetes_persistent_volume_claim" "sources" {
  metadata {
    name      = "banvic-sources-pvc"
    namespace = kubernetes_namespace.banvic.metadata[0].name

    labels = {
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    access_modes       = ["ReadOnlyMany"]
    storage_class_name = var.sources_storage_class
    volume_name        = kubernetes_persistent_volume.sources.metadata[0].name

    resources {
      requests = {
        storage = var.sources_capacity
      }
    }
  }

  wait_until_bound = true
}
