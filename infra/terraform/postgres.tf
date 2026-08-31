resource "kubernetes_config_map" "dw_init_sql" {
  metadata {
    name      = "banvic-dw-init-sql"
    namespace = kubernetes_namespace.banvic.metadata[0].name
  }

  data = {
    "001_schemas.sql" = file("${path.module}/../../sql/init/001_schemas.sql")
  }
}

resource "kubernetes_service" "postgres" {
  metadata {
    name      = "banvic-postgres"
    namespace = kubernetes_namespace.banvic.metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "banvic-postgres"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    type = "NodePort"

    selector = {
      "app.kubernetes.io/name" = "banvic-postgres"
    }

    port {
      name        = "postgres"
      port        = 5432
      target_port = 5432
      node_port   = var.dw_nodeport
      protocol    = "TCP"
    }
  }
}

resource "kubernetes_stateful_set" "postgres" {
  metadata {
    name      = "banvic-postgres"
    namespace = kubernetes_namespace.banvic.metadata[0].name
    labels = {
      "app.kubernetes.io/name"       = "banvic-postgres"
      "app.kubernetes.io/part-of"    = "banvic-data-platform"
      "app.kubernetes.io/managed-by" = "terraform"
    }
  }

  spec {
    service_name = kubernetes_service.postgres.metadata[0].name
    replicas     = 1

    selector {
      match_labels = {
        "app.kubernetes.io/name" = "banvic-postgres"
      }
    }

    template {
      metadata {
        labels = {
          "app.kubernetes.io/name" = "banvic-postgres"
        }
        annotations = {
          "banvic.io/init-sql-checksum" = sha256(
            kubernetes_config_map.dw_init_sql.data["001_schemas.sql"]
          )
        }
      }

      spec {
        container {
          name  = "postgres"
          image = var.pg_image

          port {
            name           = "postgres"
            container_port = 5432
          }

          env_from {
            secret_ref {
              name = var.dw_secret_name
            }
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
            requests = {
              cpu    = "100m"
              memory = "256Mi"
            }
            limits = {
              memory = "1Gi"
            }
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
          config_map {
            name = kubernetes_config_map.dw_init_sql.metadata[0].name
          }
        }
      }
    }

    volume_claim_template {
      metadata {
        name = "dados"
      }
      spec {
        access_modes       = ["ReadWriteOnce"]
        storage_class_name = "standard"

        resources {
          requests = {
            storage = var.dw_storage_size
          }
        }
      }
    }
  }

  timeouts {
    create = "5m"
    update = "5m"
  }
}
