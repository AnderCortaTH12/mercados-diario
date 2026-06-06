"""Tests del analizador con Claude API — sin llamadas reales (mock del cliente)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from core.analizador import (
    PRECIO_INPUT_POR_MTOKEN,
    PRECIO_OUTPUT_POR_MTOKEN,
    AnalisisResultado,
    cargar_prompt,
    construir_contexto_meff,
    analizar_dia,
)

FECHA_TEST = date(2026, 6, 4)


# ---------------------------------------------------------------------------
# test_cargar_prompt
# ---------------------------------------------------------------------------

def test_cargar_prompt(tmp_path: Path):
    ruta = tmp_path / "prompt.md"
    contenido = "Eres un analista senior de derivados."
    ruta.write_text(contenido, encoding="utf-8")

    resultado = cargar_prompt(ruta)

    assert resultado == contenido


def test_cargar_prompt_archivo_no_existe(tmp_path: Path):
    ruta = tmp_path / "no_existe.md"
    with pytest.raises(FileNotFoundError):
        cargar_prompt(ruta)


# ---------------------------------------------------------------------------
# test_construir_contexto
# ---------------------------------------------------------------------------

def _df_metricas_ejemplo(fecha: date) -> pd.DataFrame:
    """DataFrame con 24 contratos para verificar los filtros top-N.

    Distribución diseñada para que el ranking excluya XYZ con certeza:
    - 10 filler_var  : vol=500, OI=100, |var|=3%  → ocupan top-10 var
    - 10 filler_plain: vol=500, OI=100, var=0%    → ocupan top-15 vol/OI
    - IBEX35         : vol=5000, OI=120000         → top vol y top OI
    - OPTIONS IBEX   : vol=5,   OI=200             → top OI (rank 2)
    - SAN            : vol=8,   OI=80,  |var|=25%  → top var
    - XYZ            : vol=3,   OI=50,  |var|=1%   → excluido de todos los top-N
    """
    rows: list[dict] = [
        # Incluido por top vol (rank 1) y top OI (rank 1)
        {"fecha": fecha, "contract_group": "FUTURES IBEX 35", "underlying_asset": "IBEX35",
         "traded_contracts_day": 5000, "open_interest": 120000, "variacion_dia_pct": 2.1,
         "variacion_semana_pct": 1.5, "media_movil_5d": 4800.0, "z_score_volumen": float("nan"),
         "traded_contracts_mtd": 25000, "daily_average_mtd": 5000, "es_total": False},
        # Incluido por top OI (rank 2; OI=200 > fillers OI=100)
        {"fecha": fecha, "contract_group": "OPTIONS ON IBEX 35", "underlying_asset": "IBEX35",
         "traded_contracts_day": 5, "open_interest": 200, "variacion_dia_pct": 1.0,
         "variacion_semana_pct": 0.5, "media_movil_5d": 4.0, "z_score_volumen": float("nan"),
         "traded_contracts_mtd": 25, "daily_average_mtd": 5, "es_total": False},
        # Incluido por top var (|var|=25%, rank 1)
        {"fecha": fecha, "contract_group": "FUTURES STOCK", "underlying_asset": "SAN",
         "traded_contracts_day": 8, "open_interest": 80, "variacion_dia_pct": 25.0,
         "variacion_semana_pct": 10.0, "media_movil_5d": 7.0, "z_score_volumen": float("nan"),
         "traded_contracts_mtd": 40, "daily_average_mtd": 8, "es_total": False},
        # Excluido: vol=3 (< filler 500), OI=50 (< filler 100), |var|=1% (< filler_var 3%)
        {"fecha": fecha, "contract_group": "FUTURES STOCK", "underlying_asset": "XYZ",
         "traded_contracts_day": 3, "open_interest": 50, "variacion_dia_pct": 1.0,
         "variacion_semana_pct": 0.5, "media_movil_5d": 3.0, "z_score_volumen": float("nan"),
         "traded_contracts_mtd": 15, "daily_average_mtd": 3, "es_total": False},
    ]
    # 10 fillers con |var|=3% — ocupan las posiciones 2-11 en top-10 var
    for i in range(10):
        rows.append({
            "fecha": fecha, "contract_group": "FUTURES STOCK", "underlying_asset": f"FILL_V{i}",
            "traded_contracts_day": 500, "open_interest": 100, "variacion_dia_pct": 3.0,
            "variacion_semana_pct": 1.0, "media_movil_5d": 500.0, "z_score_volumen": float("nan"),
            "traded_contracts_mtd": 2500, "daily_average_mtd": 500, "es_total": False,
        })
    # 10 fillers planos — ocupan posiciones 2-15 en top-15 vol y OI
    for i in range(10):
        rows.append({
            "fecha": fecha, "contract_group": "FUTURES STOCK", "underlying_asset": f"FILL_P{i}",
            "traded_contracts_day": 500, "open_interest": 100, "variacion_dia_pct": 0.0,
            "variacion_semana_pct": 0.0, "media_movil_5d": 500.0, "z_score_volumen": float("nan"),
            "traded_contracts_mtd": 2500, "daily_average_mtd": 500, "es_total": False,
        })
    return pd.DataFrame(rows)


def test_construir_contexto_incluye_vol_alto():
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    # IBEX35 está en top-15 vol (rank 1 con vol=5000)
    assert "IBEX35" in contexto
    assert "FUTURES IBEX 35" in contexto


def test_construir_contexto_incluye_oi_alto():
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    # OPTIONS ON IBEX 35 tiene OI=200, solo superado por IBEX35 → rank 2 en top-15 OI
    assert "OPTIONS ON IBEX 35" in contexto


def test_construir_contexto_excluye_contratos_irrelevantes():
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    # XYZ: vol=3 (rank >15), OI=50 (rank >15), |var|=1% (rank >10) → excluido
    assert "XYZ" not in contexto


def test_construir_contexto_incluye_variacion_extrema():
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    # SAN tiene |var|=25%, el mayor de todos → top-10 var rank 1
    assert "SAN" in contexto


def test_construir_contexto_incluye_anomalias():
    df = _df_metricas_ejemplo(FECHA_TEST)
    anomalias = [
        {
            "tipo_anomalia": "variacion_oi_extrema",
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "SAN",
            "valor": 25.0,
            "contexto": "Open Interest varió +25.0% respecto al día anterior",
        }
    ]
    contexto = construir_contexto_meff(df, df, anomalias, FECHA_TEST)

    assert "ANOMALÍAS" in contexto
    assert "variacion_oi_extrema" in contexto


def test_construir_contexto_sin_anomalias_mensaje():
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    assert "Ninguna anomalía" in contexto


def test_construir_contexto_formato_csv_no_markdown_table():
    """Verifica que el formato es CSV inline, no tablas Markdown."""
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    # Las tablas Markdown usan |; el contexto no debe tener filas con pipes
    lineas_con_pipe = [l for l in contexto.splitlines() if l.strip().startswith("|")]
    assert len(lineas_con_pipe) == 0, "Se encontraron tablas Markdown en lugar de CSV"


def test_construir_contexto_header_contiene_metricas():
    """Verifica que el header incluye vol total y OI total del día."""
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto = construir_contexto_meff(df, df, [], FECHA_TEST)

    assert "SESIÓN=" in contexto
    assert "VOLUMEN_HOY=" in contexto
    assert "OI_TOTAL=" in contexto
    assert "ANOMALÍAS=" in contexto


def test_construir_contexto_es_mas_compacto_que_markdown():
    """El contexto CSV debe ser significativamente más corto que una tabla Markdown equivalente."""
    import io
    df = _df_metricas_ejemplo(FECHA_TEST)
    contexto_csv = construir_contexto_meff(df, df, [], FECHA_TEST)
    # Una tabla Markdown del DF completo sería mucho más grande
    md_completo = df.to_markdown(index=False)
    # El contexto CSV debe ser menor que el Markdown completo del DF
    assert len(contexto_csv) < len(md_completo), (
        f"CSV ({len(contexto_csv)} chars) no es más compacto que Markdown ({len(md_completo)} chars)"
    )


# ---------------------------------------------------------------------------
# test_analizar_dia_mock
# ---------------------------------------------------------------------------

def _crear_historico_csv(tmp_path: Path) -> Path:
    """Crea un CSV histórico mínimo para el test."""
    ruta = tmp_path / "meff_historico.csv"
    df = pd.DataFrame([
        {
            "contract_group": "FUTURES IBEX 35", "underlying_asset": "IBEX35",
            "traded_contracts_day": 5000, "traded_contracts_mtd": 25000,
            "traded_contracts_ytd": 250000, "daily_average_mtd": 5000,
            "daily_average_ytd": 5000, "open_interest": 120000,
            "fecha": FECHA_TEST.isoformat(), "es_total": False,
        },
    ])
    df.to_csv(ruta, index=False, encoding="utf-8")
    return ruta


def _crear_anomalias_json(tmp_path: Path) -> Path:
    """Crea un JSON de anomalías vacío para el test."""
    import json
    ruta = tmp_path / "anomalias.json"
    ruta.write_text(json.dumps({"fecha": FECHA_TEST.isoformat(), "anomalias": []}), encoding="utf-8")
    return ruta


def test_analizar_dia_mock(tmp_path: Path):
    ruta_historico = _crear_historico_csv(tmp_path)
    ruta_anomalias = _crear_anomalias_json(tmp_path)

    texto_resumen = "## TITULAR EJECUTIVO\nSesión sin anomalías relevantes en el MEFF."
    tokens_in = 1500
    tokens_out = 400
    coste_esperado = (tokens_in * PRECIO_INPUT_POR_MTOKEN + tokens_out * PRECIO_OUTPUT_POR_MTOKEN) / 1_000_000

    mock_respuesta = MagicMock()
    mock_respuesta.usage.input_tokens = tokens_in
    mock_respuesta.usage.output_tokens = tokens_out
    mock_respuesta.content = [MagicMock(text=texto_resumen)]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_respuesta

    with (
        patch("anthropic.Anthropic", return_value=mock_client),
        patch("core.analizador.DIRECTORIO_PROYECTO", tmp_path),
    ):
        (tmp_path / "fuentes" / "meff").mkdir(parents=True, exist_ok=True)
        (tmp_path / "fuentes" / "meff" / "prompt.md").write_text(
            "Eres un analista senior.", encoding="utf-8"
        )

        resultado = analizar_dia(
            fecha=FECHA_TEST,
            ruta_historico=ruta_historico,
            ruta_anomalias=ruta_anomalias,
        )

    assert isinstance(resultado, AnalisisResultado)
    assert resultado.exito is True
    assert resultado.fecha == FECHA_TEST
    assert resultado.resumen_markdown == texto_resumen
    assert resultado.tokens_input == tokens_in
    assert resultado.tokens_output == tokens_out
    assert abs(resultado.coste_estimado_usd - coste_esperado) < 1e-9
    assert resultado.resumen_json is not None
    assert resultado.resumen_json["modelo"] == "claude-sonnet-4-5"
    # Verificar que la telemetría está en el JSON
    assert "tokens_contexto_estimados" in resultado.resumen_json
    assert "chars_contexto" in resultado.resumen_json


def test_analizar_dia_historico_no_existe(tmp_path: Path):
    ruta_historico = tmp_path / "no_existe.csv"
    ruta_anomalias = tmp_path / "anomalias.json"

    (tmp_path / "fuentes" / "meff").mkdir(parents=True, exist_ok=True)
    (tmp_path / "fuentes" / "meff" / "prompt.md").write_text("prompt", encoding="utf-8")

    with patch("core.analizador.DIRECTORIO_PROYECTO", tmp_path):
        resultado = analizar_dia(
            fecha=FECHA_TEST,
            ruta_historico=ruta_historico,
            ruta_anomalias=ruta_anomalias,
        )

    assert resultado.exito is False
    assert "Histórico no encontrado" in resultado.mensaje
