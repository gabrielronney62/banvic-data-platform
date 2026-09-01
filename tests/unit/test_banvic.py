"""Testes unitarios do pacote banvic.

Cobrem o que a secao 22 exige: checksum, contratos, validacao de schema,
PK nula, PK duplicada, arquivo vazio, arquivo ausente e row count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from banvic.audit import AuditError, audit_file, count_rows, read_header, sha256_file
from banvic.contracts import ContractError, load_contracts
from banvic.validation import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_WARN,
    check_header,
    check_primary_key,
    check_row_count,
    validate_source,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"
CONTRACTS = FIXTURES / "contracts_teste.yml"


@pytest.fixture
def contracts():
    return load_contracts(CONTRACTS)


@pytest.fixture
def agencias(contracts):
    return contracts.table("agencias")


# --------------------------------------------------------------- contratos


def test_carrega_contratos(contracts):
    assert contracts.pipeline_version == "9.9.9"
    assert contracts.table_names == ("agencias", "contas")


def test_contrato_expoe_pk_e_colunas(agencias):
    assert agencias.primary_key == ("cod_agencia",)
    assert agencias.expected_rows == 3
    assert len(agencias.columns) == 7
    assert agencias.column("cod_agencia").type == "bigint"
    assert agencias.column("data_abertura").type == "date"


def test_relacionamento_com_severidade(contracts):
    rel = contracts.table("contas").relationships[0]
    assert rel.parent_table == "clientes"
    assert rel.parent_column == "cod_cliente"
    assert rel.severity == "WARN"


def test_tabela_inexistente_levanta_erro(contracts):
    with pytest.raises(ContractError, match="nao declarada"):
        contracts.table("inexistente")


def test_arquivo_de_contratos_ausente():
    with pytest.raises(ContractError, match="nao encontrado"):
        load_contracts(FIXTURES / "nao-existe.yml")


def test_tipo_invalido_e_rejeitado(tmp_path):
    ruim = tmp_path / "ruim.yml"
    ruim.write_text(
        "tables:\n"
        "  - table: t\n"
        "    source_file: t.csv\n"
        "    primary_key: [id]\n"
        "    expected_rows: 1\n"
        "    columns:\n"
        "      id: { type: blob, nullable: false }\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="invalido"):
        load_contracts(ruim)


def test_pk_fora_das_colunas_e_rejeitada(tmp_path):
    ruim = tmp_path / "ruim.yml"
    ruim.write_text(
        "tables:\n"
        "  - table: t\n"
        "    source_file: t.csv\n"
        "    primary_key: [nao_existe]\n"
        "    expected_rows: 1\n"
        "    columns:\n"
        "      id: { type: bigint, nullable: false }\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="nao declaradas"):
        load_contracts(ruim)


# --------------------------------------------------------------- auditoria


def test_checksum_e_estavel():
    primeiro = sha256_file(FIXTURES / "ok.csv")
    segundo = sha256_file(FIXTURES / "ok.csv")
    assert primeiro == segundo
    assert len(primeiro) == 64


def test_checksum_muda_com_o_conteudo(tmp_path):
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("x,y\n1,2\n", encoding="utf-8")
    b.write_text("x,y\n1,3\n", encoding="utf-8")
    assert sha256_file(a) != sha256_file(b)


def test_conta_linhas_ignorando_cabecalho():
    assert count_rows(FIXTURES / "ok.csv") == 3


def test_conta_linhas_respeita_virgula_entre_aspas():
    # "Rua A, 100" tem virgula: contar campos por split quebraria.
    header = read_header(FIXTURES / "ok.csv")
    assert len(header) == 7
    assert header[2] == "endereco"


def test_arquivo_vazio_tem_zero_linhas():
    assert count_rows(FIXTURES / "vazio.csv") == 0


def test_auditar_arquivo_ausente_levanta_erro():
    with pytest.raises(AuditError, match="ausente"):
        audit_file(FIXTURES / "nao-existe.csv")


def test_auditoria_completa():
    resultado = audit_file(FIXTURES / "ok.csv")
    assert resultado.filename == "ok.csv"
    assert resultado.row_count == 3
    assert resultado.size_bytes > 0
    assert len(resultado.checksum_sha256) == 64
    assert resultado.header[0] == "cod_agencia"


# -------------------------------------------------------------- validacao


def test_fonte_valida_passa_em_tudo(agencias):
    report = validate_source(agencias, FIXTURES / "ok.csv")
    assert report.ok
    assert all(r.status == STATUS_PASS for r in report.results)
    assert "5 verificacoes" in report.summary()


def test_arquivo_ausente_bloqueia(agencias):
    report = validate_source(agencias, FIXTURES / "nao-existe.csv")
    assert not report.ok
    assert report.results[0].check_name == "file_present"
    # Para na primeira falha: nao adianta checar cabecalho de arquivo ausente.
    assert len(report.results) == 1


def test_arquivo_vazio_bloqueia(agencias):
    report = validate_source(agencias, FIXTURES / "vazio.csv")
    assert not report.ok
    assert "vazio" in report.results[0].details


def test_header_incompleto_bloqueia(agencias):
    report = validate_source(agencias, FIXTURES / "header_incompleto.csv")
    assert not report.ok
    falha = next(r for r in report.results if r.check_name == "header_matches_contract")
    assert falha.status == STATUS_FAIL
    assert "endereco" in falha.details


def test_coluna_extra_e_apenas_informativa(agencias):
    resultado = check_header(agencias, (*agencias.column_names, "coluna_nova"))
    assert resultado.status == STATUS_WARN
    assert resultado.severity == "INFO"
    assert not resultado.blocks_promotion


def test_pk_nula_bloqueia(agencias):
    resultados = check_primary_key(agencias, FIXTURES / "pk_nula.csv")
    nulos = next(r for r in resultados if r.check_name == "primary_key_not_null")
    assert nulos.status == STATUS_FAIL
    assert nulos.invalid_rows == 1
    assert nulos.blocks_promotion


def test_pk_duplicada_bloqueia(agencias):
    resultados = check_primary_key(agencias, FIXTURES / "pk_duplicada.csv")
    dup = next(r for r in resultados if r.check_name == "primary_key_unique")
    assert dup.status == STATUS_FAIL
    assert dup.invalid_rows == 1
    assert dup.blocks_promotion


def test_row_count_divergente_e_warn_nao_fail(agencias):
    resultado = check_row_count(agencias, 99)
    assert resultado.status == STATUS_WARN
    assert resultado.invalid_rows == 96
    # Uma carga futura pode legitimamente ter outra quantidade.
    assert not resultado.blocks_promotion


def test_row_count_correto_passa(agencias):
    resultado = check_row_count(agencias, 3)
    assert resultado.status == STATUS_PASS
