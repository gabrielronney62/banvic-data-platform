"""Testes de integracao contra o Data Warehouse real.

Exigem o cluster de pe e uma execucao bem-sucedida da DAG. Conectam pelo
NodePort exposto em localhost:15432 usando as credenciais do .env.

Rodar com:
    make test-integration

Todos marcados com `integration`, entao `make test` (unitarios) continua
rapido e sem dependencia externa.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from banvic.audit import sha256_file
from banvic.contracts import load_contracts

psycopg2 = pytest.importorskip("psycopg2")

ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_PATH = ROOT / "airflow" / "include" / "contracts" / "contracts.yml"

pytestmark = pytest.mark.integration


def _env() -> dict[str, str]:
    """Le o .env local em pares chave-valor."""
    arquivo = ROOT / ".env"
    if not arquivo.is_file():
        pytest.skip(".env nao encontrado")
    valores: dict[str, str] = {}
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha and not linha.startswith("#") and "=" in linha:
            chave, valor = linha.split("=", 1)
            valores[chave.strip()] = valor.strip()
    return valores


@pytest.fixture(scope="module")
def conn():
    """Conexao com o DW pelo NodePort. Pula os testes se o cluster estiver fora."""
    env = _env()
    try:
        conexao = psycopg2.connect(
            host=os.environ.get("BANVIC_TEST_HOST", "localhost"),
            port=int(os.environ.get("BANVIC_TEST_PORT", "15432")),
            dbname=env["BANVIC_DW_DB"],
            user=env["BANVIC_DW_USER"],
            password=env["BANVIC_DW_PASSWORD"],
            connect_timeout=5,
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(f"DW inacessivel em localhost:15432: {exc}")
    yield conexao
    conexao.close()


@pytest.fixture(scope="module")
def contracts():
    return load_contracts(CONTRACTS_PATH)


def _um(conn, sql: str, params=None):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        linha = cur.fetchone()
    return linha[0] if linha else None


# ------------------------------------------------------------ estrutura


def test_schemas_existem(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT schema_name FROM information_schema.schemata "
            "WHERE schema_name IN ('staging', 'raw', 'ops')"
        )
        encontrados = {linha[0] for linha in cur.fetchall()}
    assert encontrados == {"staging", "raw", "ops"}


def test_sete_tabelas_em_raw(conn, contracts):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'raw'"
        )
        encontradas = {linha[0] for linha in cur.fetchall()}
    assert encontradas == set(contracts.table_names)


def test_raw_nao_tem_foreign_keys(conn):
    """A raw reproduz a origem: FK rejeitaria as linhas orfas do cliente 528."""
    total = _um(
        conn,
        "SELECT count(*) FROM information_schema.table_constraints "
        "WHERE table_schema = 'raw' AND constraint_type = 'FOREIGN KEY'",
    )
    assert total == 0


# ------------------------------------------------------------ contagens


def test_contagens_batem_com_os_contratos(conn, contracts):
    divergencias = []
    for contrato in contracts.tables:
        total = _um(conn, f'SELECT count(*) FROM raw."{contrato.table}"')  # noqa: S608
        if total != contrato.expected_rows:
            divergencias.append(f"{contrato.table}: {total} != {contrato.expected_rows}")
    assert not divergencias, divergencias


def test_pks_sao_unicas_em_raw(conn, contracts):
    problemas = []
    for contrato in contracts.tables:
        colunas = ", ".join(f'"{c}"' for c in contrato.primary_key)
        linhas = _um(conn, f'SELECT count(*) FROM raw."{contrato.table}"')  # noqa: S608
        distintas = _um(
            conn,
            f"SELECT count(*) FROM (SELECT DISTINCT {colunas} "  # noqa: S608
            f'FROM raw."{contrato.table}") AS k',
        )
        if linhas != distintas:
            problemas.append(f"{contrato.table}: {linhas} linhas, {distintas} PKs")
    assert not problemas, problemas


def test_staging_e_raw_tem_as_mesmas_contagens(conn, contracts):
    divergencias = []
    for contrato in contracts.tables:
        stg = _um(conn, f'SELECT count(*) FROM staging."{contrato.table}"')  # noqa: S608
        raw = _um(conn, f'SELECT count(*) FROM raw."{contrato.table}"')  # noqa: S608
        if stg != raw:
            divergencias.append(f"{contrato.table}: staging={stg} raw={raw}")
    assert not divergencias, divergencias


# ---------------------------------------------------------------- tipos


TIPO_ESPERADO = {
    "bigint": "bigint",
    "integer": "integer",
    "numeric": "numeric",
    "date": "date",
    "timestamptz": "timestamp with time zone",
    "text": "text",
}


def test_tipos_em_raw_seguem_os_contratos(conn, contracts):
    divergencias = []
    for contrato in contracts.tables:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'raw' AND table_name = %s",
                (contrato.table,),
            )
            reais = dict(cur.fetchall())
        for coluna in contrato.columns:
            esperado = TIPO_ESPERADO[coluna.type]
            real = reais.get(coluna.name)
            if real != esperado:
                divergencias.append(
                    f"{contrato.table}.{coluna.name}: {real} != {esperado}"
                )
    assert not divergencias, divergencias


def test_campos_sensiveis_permanecem_texto(conn):
    """CPF, CNPJ e CEP tem zeros a esquerda que a conversao numerica destruiria."""
    for tabela, coluna in [
        ("clientes", "cpfcnpj"),
        ("clientes", "cep"),
        ("colaboradores", "cpf"),
        ("colaboradores", "cep"),
    ]:
        tipo = _um(
            conn,
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'raw' AND table_name = %s AND column_name = %s",
            (tabela, coluna),
        )
        assert tipo == "text", f"raw.{tabela}.{coluna} e {tipo}"


def test_zeros_a_esquerda_preservados(conn):
    com_zero = _um(conn, "SELECT count(*) FROM raw.clientes WHERE cep LIKE '0%'")
    assert com_zero > 0, "nenhum CEP com zero a esquerda: a conversao destruiu o dado"


def test_precisao_decimal_nao_foi_arredondada(conn):
    """NUMERIC(18,2) truncaria: a origem traz ate 17 casas decimais."""
    total = _um(
        conn,
        "SELECT count(*) FROM raw.contas "
        "WHERE length(split_part(saldo_disponivel::text, '.', 2)) > 2",
    )
    assert total > 0, "todos os saldos com 2 casas: houve arredondamento"


# ------------------------------------------------- inconsistencia da origem


def test_cliente_528_preservado_como_orfao(conn):
    """Secao 7: a raw reproduz a origem, sem inventar nem excluir registros."""
    assert _um(conn, "SELECT count(*) FROM raw.clientes WHERE cod_cliente = 528") == 0
    assert _um(conn, "SELECT count(*) FROM raw.contas WHERE cod_cliente = 528") == 1
    assert (
        _um(conn, "SELECT count(*) FROM raw.propostas_credito WHERE cod_cliente = 528")
        == 4
    )


def test_valores_negativos_preservados(conn):
    """Negativo em transacoes e valido e nao deve ser tratado como erro."""
    negativos = _um(
        conn, "SELECT count(*) FROM raw.transacoes WHERE valor_transacao < 0"
    )
    assert negativos > 0


# ------------------------------------------------------------ auditoria


@pytest.fixture(scope="module")
def ultimo_run(conn):
    run_id = _um(
        conn,
        "SELECT run_id FROM ops.pipeline_runs "
        "WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1",
    )
    if not run_id:
        pytest.skip("nenhuma execucao SUCCESS registrada em ops.pipeline_runs")
    return run_id


def test_metricas_gravadas_para_as_sete_tabelas(conn, ultimo_run, contracts):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM ops.pipeline_table_metrics WHERE run_id = %s",
            (ultimo_run,),
        )
        tabelas = {linha[0] for linha in cur.fetchall()}
    assert tabelas == set(contracts.table_names)


def test_checksums_batem_com_os_arquivos_em_disco(conn, ultimo_run, contracts):
    """Fecha a cadeia: o hash gravado na auditoria e o do arquivo de origem."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, source_checksum FROM ops.pipeline_table_metrics "
            "WHERE run_id = %s",
            (ultimo_run,),
        )
        gravados = dict(cur.fetchall())

    divergencias = []
    for contrato in contracts.tables:
        arquivo = ROOT / "data" / "incoming" / contrato.source_file
        if not arquivo.is_file():
            pytest.skip(f"fonte ausente: {arquivo}")
        real = sha256_file(arquivo)
        gravado = gravados.get(contrato.table)
        if gravado != real:
            divergencias.append(f"{contrato.table}: {gravado} != {real}")
    assert not divergencias, divergencias


def test_checksum_tem_formato_de_sha256(conn, ultimo_run):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_checksum FROM ops.pipeline_table_metrics WHERE run_id = %s",
            (ultimo_run,),
        )
        valores = [linha[0] for linha in cur.fetchall()]
    assert valores
    for valor in valores:
        assert re.fullmatch(r"[0-9a-f]{64}", valor or ""), valor


def test_contagens_da_auditoria_batem_com_o_banco(conn, ultimo_run, contracts):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name, row_count_source, row_count_staging, row_count_raw "
            "FROM ops.pipeline_table_metrics WHERE run_id = %s",
            (ultimo_run,),
        )
        metricas = {linha[0]: linha[1:] for linha in cur.fetchall()}

    for contrato in contracts.tables:
        origem, stg, raw = metricas[contrato.table]
        assert origem == contrato.expected_rows, contrato.table
        assert stg == origem, contrato.table
        assert raw == origem, contrato.table


# --------------------------------------------------------- data quality


def test_cliente_528_registrado_como_warn(conn, ultimo_run):
    """A inconsistencia da origem vira observabilidade, nao falha tecnica."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT check_name, severity, status, invalid_rows "
            "FROM ops.data_quality_results "
            "WHERE run_id = %s AND status <> 'PASS' ORDER BY table_name",
            (ultimo_run,),
        )
        avisos = cur.fetchall()

    por_check = {linha[0]: linha for linha in avisos}
    assert "fk_contas_clientes" in por_check
    assert "fk_propostas_credito_clientes" in por_check
    assert por_check["fk_contas_clientes"][3] == 1
    assert por_check["fk_propostas_credito_clientes"][3] == 4
    for linha in avisos:
        assert linha[1] == "WARN", f"{linha[0]} deveria ser WARN, veio {linha[1]}"


def test_nenhuma_verificacao_critical_falhou(conn, ultimo_run):
    total = _um(
        conn,
        "SELECT count(*) FROM ops.data_quality_results "
        "WHERE run_id = %s AND severity = 'CRITICAL' AND status = 'FAIL'",
        (ultimo_run,),
    )
    assert total == 0


def test_execucao_foi_fechada(conn, ultimo_run):
    """Sem finish_run, a execucao ficaria eternamente em RUNNING na auditoria."""
    fim = _um(
        conn, "SELECT finished_at FROM ops.pipeline_runs WHERE run_id = %s", (ultimo_run,)
    )
    assert fim is not None


# ------------------------------------------------------------- linhagem


def test_linhagem_preenchida_em_raw(conn, contracts):
    for contrato in contracts.tables:
        sem_linhagem = _um(
            conn,
            f'SELECT count(*) FROM raw."{contrato.table}" '  # noqa: S608
            f"WHERE _source_file IS NULL OR _airflow_run_id IS NULL",
        )
        assert sem_linhagem == 0, contrato.table
