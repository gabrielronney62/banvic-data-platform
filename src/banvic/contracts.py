"""Leitura e representacao dos contratos declarativos das fontes.

Os contratos vivem em YAML (secao 21 do desafio). Este modulo os carrega
e expoe como objetos tipados, para que nenhuma regra especifica de tabela
precise ser escrita como if/else no restante do pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_CONTRACTS_PATH = Path(
    os.environ.get(
        "BANVIC_CONTRACTS_PATH",
        "/opt/airflow/dags/../include/contracts/contracts.yml",
    )
)

VALID_TYPES = frozenset(
    {"text", "bigint", "integer", "numeric", "date", "timestamptz"}
)
VALID_SEVERITIES = frozenset({"CRITICAL", "WARN", "INFO"})


class ContractError(ValueError):
    """Contrato malformado ou incoerente."""


@dataclass(frozen=True)
class Column:
    """Uma coluna declarada no contrato."""

    name: str
    type: str
    nullable: bool


@dataclass(frozen=True)
class Relationship:
    """Relacionamento logico entre tabelas.

    A severidade distingue falha tecnica (CRITICAL) de problema conhecido
    da origem (WARN), como o cod_cliente 528 da secao 7.
    """

    column: str
    parent_table: str
    parent_column: str
    severity: str


@dataclass(frozen=True)
class TableContract:
    """Contrato de uma tabela de origem."""

    table: str
    source_file: str
    primary_key: tuple[str, ...]
    expected_rows: int
    columns: tuple[Column, ...]
    relationships: tuple[Relationship, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        """Nomes das colunas na ordem declarada."""
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        """Retorna a coluna pelo nome."""
        for col in self.columns:
            if col.name == name:
                return col
        raise ContractError(f"coluna {name!r} nao declarada em {self.table!r}")


@dataclass(frozen=True)
class Contracts:
    """Conjunto completo de contratos do pipeline."""

    pipeline_version: str
    source_dir: str
    tables: tuple[TableContract, ...]

    @property
    def table_names(self) -> tuple[str, ...]:
        """Nomes das tabelas na ordem declarada."""
        return tuple(t.table for t in self.tables)

    def table(self, name: str) -> TableContract:
        """Retorna o contrato de uma tabela pelo nome."""
        for tbl in self.tables:
            if tbl.table == name:
                return tbl
        raise ContractError(f"tabela {name!r} nao declarada nos contratos")

    def source_path(self, name: str) -> Path:
        """Caminho absoluto do arquivo de origem de uma tabela."""
        return Path(self.source_dir) / self.table(name).source_file


def _parse_relationship(raw: dict, table: str) -> Relationship:
    """Converte um relacionamento do YAML em objeto tipado."""
    try:
        parent_table, parent_column = str(raw["references"]).split(".", 1)
    except (KeyError, ValueError) as exc:
        raise ContractError(
            f"relacionamento invalido em {table!r}: esperado 'tabela.coluna'"
        ) from exc

    severity = str(raw.get("severity", "CRITICAL")).upper()
    if severity not in VALID_SEVERITIES:
        raise ContractError(
            f"severidade {severity!r} invalida em {table!r}; "
            f"use uma de {sorted(VALID_SEVERITIES)}"
        )

    return Relationship(
        column=raw["column"],
        parent_table=parent_table,
        parent_column=parent_column,
        severity=severity,
    )


def _parse_table(raw: dict) -> TableContract:
    """Converte um bloco de tabela do YAML em objeto tipado."""
    name = raw.get("table")
    if not name:
        raise ContractError("bloco de tabela sem a chave 'table'")

    columns: list[Column] = []
    for col_name, spec in (raw.get("columns") or {}).items():
        col_type = str(spec.get("type", "")).lower()
        if col_type not in VALID_TYPES:
            raise ContractError(
                f"tipo {col_type!r} invalido em {name}.{col_name}; "
                f"use um de {sorted(VALID_TYPES)}"
            )
        columns.append(
            Column(
                name=col_name,
                type=col_type,
                nullable=bool(spec.get("nullable", True)),
            )
        )

    if not columns:
        raise ContractError(f"tabela {name!r} sem colunas declaradas")

    primary_key = tuple(raw.get("primary_key") or ())
    if not primary_key:
        raise ContractError(f"tabela {name!r} sem primary_key declarada")

    declared = {c.name for c in columns}
    faltando = [k for k in primary_key if k not in declared]
    if faltando:
        raise ContractError(
            f"primary_key de {name!r} referencia colunas nao declaradas: {faltando}"
        )

    return TableContract(
        table=name,
        source_file=raw["source_file"],
        primary_key=primary_key,
        expected_rows=int(raw["expected_rows"]),
        columns=tuple(columns),
        relationships=tuple(
            _parse_relationship(r, name) for r in (raw.get("relationships") or [])
        ),
    )


def load_contracts(path: Path | str | None = None) -> Contracts:
    """Carrega os contratos de um arquivo YAML.

    Args:
        path: caminho do arquivo. Usa BANVIC_CONTRACTS_PATH se omitido.

    Raises:
        ContractError: se o arquivo estiver ausente ou malformado.
    """
    contracts_path = Path(path) if path else DEFAULT_CONTRACTS_PATH

    if not contracts_path.is_file():
        raise ContractError(f"arquivo de contratos nao encontrado: {contracts_path}")

    with contracts_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    if not isinstance(raw, dict) or "tables" not in raw:
        raise ContractError(f"contrato malformado em {contracts_path}: falta 'tables'")

    tables = tuple(_parse_table(t) for t in raw["tables"])

    nomes = [t.table for t in tables]
    duplicados = {n for n in nomes if nomes.count(n) > 1}
    if duplicados:
        raise ContractError(f"tabelas declaradas mais de uma vez: {sorted(duplicados)}")

    return Contracts(
        pipeline_version=str(raw.get("pipeline_version", "0.0.0")),
        source_dir=str(raw.get("source_dir", "/opt/banvic/incoming")),
        tables=tables,
    )


@lru_cache(maxsize=4)
def get_contracts(path: str | None = None) -> Contracts:
    """Versao memoizada de load_contracts, para uso dentro das tasks."""
    return load_contracts(path)
