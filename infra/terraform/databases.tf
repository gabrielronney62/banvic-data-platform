# Duas instancias PostgreSQL, deliberadamente separadas (requisito da secao 3).
#
# banvic_dw       : Data Warehouse. Camadas staging, raw e ops.
# airflow_metadata: estado interno do Airflow. Nao contem dado de negocio.
#
# Responsabilidades e ciclos de vida distintos. Perder o banco de metadados
# custa o historico de execucoes; perder o DW custa os dados ingeridos.

module "dw" {
  source = "./modules/postgres"

  name        = "banvic-postgres"
  namespace   = kubernetes_namespace.banvic.metadata[0].name
  image       = var.pg_image
  secret_name = var.dw_secret_name

  storage_size = var.dw_storage_size
  node_port    = var.dw_nodeport

  init_sql = {
    "001_schemas.sql" = file("${path.module}/../../sql/init/001_schemas.sql")
  }
}

module "airflow_metadata" {
  source = "./modules/postgres"

  name        = "airflow-postgres"
  namespace   = kubernetes_namespace.banvic.metadata[0].name
  image       = var.pg_image
  secret_name = var.metadata_secret_name

  storage_size = var.metadata_storage_size

  resources_requests = { cpu = "100m", memory = "256Mi" }
  resources_limits   = { memory = "512Mi" }
}
