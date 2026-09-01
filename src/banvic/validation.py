"""Validacoes estruturais das fontes contra os contratos.

A secao 11 do desafio separa dois conceitos, e este modulo respeita a
separacao com rigor:

  - Validacao estrutural: arquivo ausente, cabecalho incompativel, coluna
    faltando, PK nula ou duplicada, contagem divergente. Indica possivel
    falha tecnica e PODE impedir a promocao.

  - Qualidade dos dados de negocio: registrada e preservada, nunca
    corrigida. O cod_cliente 528 inexistente e o exemplo canonico.

Este modulo cuida apenas do primeiro grupo. As verificacoes de negocio
rodam em SQL, sobre staging, depois da carga.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from banvic.audit import audit_file
from banvic.contracts import TableContract

SEVERITY_CRITICAL = "CRITICAL"
SEVERITY_WARN = "WARN"
SEVERITY_INFO = "INFO"

STATUS_PASS = "PASS"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    """Resultado de uma verificacao individual.

    Mapeia diretamente para uma linha de ops.data_quality_results.
    """

    table_name: str
    check_name: str
    severity: str
    status: str
    invalid_rows: int = 0
    details: str = ""

    @property
    def blocks_promotion(self) -> bool:
        """Indica se este resultado deve impedir a promocao para raw."""
        return self.status == STATUS_FAIL and self.severity == SEVERITY_CRITICAL


@dataclass
class ValidationReport:
    """Conjunto de resultados de uma validacao."""

    results: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        """Acrescenta um resultado ao relatorio."""
        self.results.append(result)

    @property
    def blocking(self) -> list[CheckResult]:
        """Resultados que impedem a promocao."""
        return [r for r in self.results if r.blocks_promotion]

    @property
    def ok(self) -> bool:
        """True quando nada impede a promocao."""
        return not self.blocking

    def summary(self) -> str:
        """Resumo legivel para o log da task."""
        counts = Counter(r.status for r in self.results)
        return (
            f"{len(self.results)} verificacoes: "
            f"{counts.get(STATUS_PASS, 0)} PASS, "
            f"{counts.get(STATUS_WARN, 0)} WARN, "
            f"{counts.get(STATUS_FAIL, 0)} FAIL"
        )


def check_file_present(contract: TableContract, path: Path) -> CheckResult:
    """Verifica se o arquivo de origem existe e nao esta vazio."""
    if not path.is_file():
        return CheckResult(
            contract.table,
            "file_present",
            SEVERITY_CRITICAL,
            STATUS_FAIL,
            details=f"arquivo ausente: {path}",
        )
    if path.stat().st_size == 0:
        return CheckResult(
            contract.table,
            "file_present",
            SEVERITY_CRITICAL,
            STATUS_FAIL,
            details=f"arquivo vazio: {path}",
        )
    return CheckResult(
        contract.table, "file_present", SEVERITY_CRITICAL, STATUS_PASS
    )


def check_header(contract: TableContract, header: tuple[str, ...]) -> CheckResult:
    """Compara o cabecalho do arquivo com as colunas do contrato.

    Colunas faltando sao falha critica. Colunas extras sao INFO: a origem
    pode ganhar campos sem que isso quebre a ingestao.
    """
    esperadas = set(contract.column_names)
    recebidas = set(header)

    faltando = sorted(esperadas - recebidas)
    extras = sorted(recebidas - esperadas)

    if faltando:
        return CheckResult(
            contract.table,
            "header_matches_contract",
            SEVERITY_CRITICAL,
            STATUS_FAIL,
            details=f"colunas ausentes: {faltando}",
        )
    if extras:
        return CheckResult(
            contract.table,
            "header_matches_contract",
            SEVERITY_INFO,
            STATUS_WARN,
            details=f"colunas nao declaradas no contrato: {extras}",
        )
    return CheckResult(
        contract.table, "header_matches_contract", SEVERITY_CRITICAL, STATUS_PASS
    )


def check_row_count(contract: TableContract, row_count: int) -> CheckResult:
    """Compara a contagem lida com a esperada pelo contrato.

    Divergencia e WARN, nao FAIL: uma carga futura legitimamente traz
    outra quantidade de registros. O que importa e o numero ser registrado
    e a divergencia ficar visivel.
    """
    if row_count == contract.expected_rows:
        return CheckResult(
            contract.table,
            "row_count_matches_expected",
            SEVERITY_INFO,
            STATUS_PASS,
            details=f"{row_count} registros",
        )
    return CheckResult(
        contract.table,
        "row_count_matches_expected",
        SEVERITY_WARN,
        STATUS_WARN,
        invalid_rows=abs(row_count - contract.expected_rows),
        details=f"esperado {contract.expected_rows}, lido {row_count}",
    )


def check_primary_key(contract: TableContract, path: Path) -> list[CheckResult]:
    """Verifica PK nula e PK duplicada no arquivo de origem.

    Ambas sao falhas criticas: indicam problema de extracao ou corrupcao,
    nao caracteristica legitima da fonte.
    """
    nulos = 0
    chaves: Counter[tuple[str, ...]] = Counter()

    with path.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            valores = tuple((row.get(k) or "").strip() for k in contract.primary_key)
            if any(v == "" for v in valores):
                nulos += 1
            else:
                chaves[valores] += 1

    duplicadas = sum(n - 1 for n in chaves.values() if n > 1)

    resultados = [
        CheckResult(
            contract.table,
            "primary_key_not_null",
            SEVERITY_CRITICAL,
            STATUS_FAIL if nulos else STATUS_PASS,
            invalid_rows=nulos,
            details=f"pk={'+'.join(contract.primary_key)}",
        ),
        CheckResult(
            contract.table,
            "primary_key_unique",
            SEVERITY_CRITICAL,
            STATUS_FAIL if duplicadas else STATUS_PASS,
            invalid_rows=duplicadas,
            details=f"{len(chaves)} chaves distintas",
        ),
    ]
    return resultados


def validate_source(contract: TableContract, path: Path | str) -> ValidationReport:
    """Roda todas as validacoes estruturais de uma fonte.

    Se o arquivo estiver ausente ou vazio, para por ali: as demais
    verificacoes nao teriam o que examinar.
    """
    file_path = Path(path)
    report = ValidationReport()

    presenca = check_file_present(contract, file_path)
    report.add(presenca)
    if presenca.status == STATUS_FAIL:
        return report

    auditoria = audit_file(file_path)
    report.add(check_header(contract, auditoria.header))
    report.add(check_row_count(contract, auditoria.row_count))

    for resultado in check_primary_key(contract, file_path):
        report.add(resultado)

    return report
