locals {
  labels = {
    "app.kubernetes.io/name"       = var.name
    "app.kubernetes.io/part-of"    = "banvic-data-platform"
    "app.kubernetes.io/managed-by" = "terraform"
  }

  init_checksum = sha256(join("", [for k in sort(keys(var.init_sql)) : var.init_sql[k]]))
}

resource "kubernetes_config_map" "init_sql" {
  metadata {
    name      = "${var.name}-init-sql"
    namespace = var.namespace
    labels    = local.labels
  }

  data = var.init_sql
}

resource "kubernetes_service" "this" {
  metadata {
    name      = var.name
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    type     = var.node_port == null ? "ClusterIP" : "NodePort"
    selector = { "app.kubernetes.io/name" = var.name }

    port {
      name        = "postgres"
      port        = 5432
      target_port = 5432
      node_port   = var.node_port
      protocol    = "TCP"
    }
  }
}

resource "kubernetes_stateful_set" "this" {
  metadata {
    name      = var.name
    namespace = var.namespace
    labels    = local.labels
  }

  spec {
    service_name = kubernetes_service.this.metadata[0].name
    replicas     = 1

    selector {
      match_labels = { "app.kubernetes.io/name" = var.name }
    }

    template {
      metadata {
        labels      = { "app.kubernetes.io/name" = var.name }
        annotations = { "banvic.io/init-sql-checksum" = local.init_checksum }
      }

      spec {
        container {
          name  = "postgres"
          image = var.image

          port {
            name           = "postgres"
            container_port = 5432
          }

          env_from {
            secret_ref { name = var.secret_name }
          }

          env {
            name  = "PGDATA"
            value = "/var/lib/postgresql/data/pgdata"
          }

          volume_mount {
            name       = "dados"
            mount_path = "/var/lib/postgresql/data"
          }

          volume_mount {
            name       = "init-sql"
            mount_path = "/docker-entrypoint-initdb.d"
            read_only  = true
          }

          resources {
            requests = var.resources_requests
            limits   = var.resources_limits
          }

          readiness_probe {
            exec {
              command = ["sh", "-c", "pg_isready -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\""]
            }
            initial_delay_seconds = 10
            period_seconds        = 5
            timeout_seconds       = 3
          }

          liveness_probe {
            exec {
              command = ["sh", "-c", "pg_isready -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\""]
            }
            initial_delay_seconds = 30
            period_seconds        = 15
            timeout_seconds       = 5
          }
        }

        volume {
          name = "init-sql"
          config_map { name = kubernetes_config_map.init_sql.metadata[0].name }
        }
      }
    }

    volume_claim_template {
      metadata { name = "dados" }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = var.storage_class
        resources {
          requests = { storage = var.storage_size }
        }
      }
    }
  }

  timeouts {
    create = "5m"
    update = "5m"
  }
}
