# ADR 0003 — Secrets criados por script, não pelo Terraform

**Status:** aceito
**Data:** 2026-08

## Contexto

O Terraform provisiona namespace, volumes e as instâncias PostgreSQL. Seria
natural que também criasse os Secrets do Kubernetes.

## Decisão

Os Secrets são criados por `scripts/create_secrets.sh`, usando `kubectl`. O
Terraform apenas os referencia pelo nome.

## Justificativa

Recursos gerenciados por Terraform são gravados em `terraform.tfstate` em
**texto plano**. Isso inclui senhas. O arquivo está no `.gitignore`, mas fica
em disco sem proteção, e qualquer `terraform show` o exibe.

É uma limitação conhecida do Terraform, não um erro de configuração.

## Consequências

O segredo existe apenas em dois lugares: no `.env` local (fora do Git, com
permissão 600) e no etcd do cluster.

Verificável:

```bash
grep -c "$BANVIC_DW_PASSWORD" infra/terraform/terraform.tfstate   # 0
```

O custo é que o `make rebuild` precisa chamar `create_secrets.sh` entre dois
`terraform apply`: o namespace primeiro, depois os Secrets, depois o resto.
Está automatizado.

O script usa `--dry-run=client -o yaml | kubectl apply -f -`, o que o torna
idempotente.
