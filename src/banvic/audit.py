"""Auditoria das fontes: checksum, contagem de linhas e cabecalho.

Atende a secao 10 do desafio. Nenhuma funcao aqui altera arquivo ou banco:
o modulo apenas observa e reporta.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

CHUNK_SIZE = 1 << 20  # 1 MiB


class AuditError(RuntimeError):
    """Falha ao auditar um arquivo de origem."""


@dataclass(frozen=True)
class FileAudit:
    """Resultado da auditoria de um arquivo de origem."""

    filename: str
    path: str
    exists: bool
    size_bytes: int
    checksum_sha256: str
    row_count: int
    header: tuple[str, ...]


def sha256_file(path: Path) -> str:
    """Calcula o SHA-256 de um arquivo lendo em blocos.

    Le em blocos de 1 MiB para nao carregar transacoes.csv inteiro
    (4,2 MB hoje, mas o pipeline nao deve assumir tamanho da fonte).
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_header(path: Path) -> tuple[str, ...]:
    """Le o cabecalho de um CSV respeitando quoting."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        try:
            return tuple(next(csv.reader(fh)))
        except StopIteration:
            return ()


def count_rows(path: Path) -> int:
    """Conta registros logicos de um CSV, excluindo o cabecalho.

    Usa csv.reader em vez de contar quebras de linha porque campos podem
    conter virgulas, aspas e, em tese, quebras de linha embutidas.
    Retorna 0 para arquivo vazio ou apenas com cabecalho.
    """
    with path.open("r", encoding="utf-8", newline="") as fh:
        total = sum(1 for _ in csv.reader(fh))
    return max(total - 1, 0)


def audit_file(path: Path | str) -> FileAudit:
    """Audita um arquivo de origem.

    Raises:
        AuditError: se o arquivo nao existir.

    """
    file_path = Path(path)

    if not file_path.is_file():
        raise AuditError(f"arquivo de origem ausente: {file_path}")

    return FileAudit(
        filename=file_path.name,
        path=str(file_path),
        exists=True,
        size_bytes=file_path.stat().st_size,
        checksum_sha256=sha256_file(file_path),
        row_count=count_rows(file_path),
        header=read_header(file_path),
    )
