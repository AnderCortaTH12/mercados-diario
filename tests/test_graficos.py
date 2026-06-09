"""Tests del módulo core/graficos — sin llamadas a API reales."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from core.graficos import (
    GraficoSpec,
    generar_distribucion_categorias,
    generar_evolucion_volumen,
    generar_top_movers_oi,
    generar_graficos_segun_spec,
    parsear_specs_graficos,
)

FECHA = date(2026, 6, 4)
FECHA_ANT = date(2026, 6, 3)
FECHA_ANT2 = date(2026, 6, 2)


# ---------------------------------------------------------------------------
# DataFrames sintéticos
# ---------------------------------------------------------------------------

def _df_dia(fecha: date) -> list[dict]:
    return [
        {
            "fecha": fecha, "contract_group": "FUTURES IBEX 35",
            "underlying_asset": "IBEX35", "traded_contracts_day": 5000,
            "open_interest": 120000, "variacion_dia_pct": 2.1, "es_total": False,
        },
        {
            "fecha": fecha, "contract_group": "FUTURES STOCK",
            "underlying_asset": "SAN", "traded_contracts_day": 800,
            "open_interest": 50000, "variacion_dia_pct": -18.5, "es_total": False,
        },
        {
            "fecha": fecha, "contract_group": "OPTIONS STOCK",
            "underlying_asset": "TEF", "traded_contracts_day": 400,
            "open_interest": 30000, "variacion_dia_pct": 5.3, "es_total": False,
        },
        {
            "fecha": fecha, "contract_group": "FUTURES IBEX 35",
            "underlying_asset": None, "traded_contracts_day": 5000,
            "open_interest": 120000, "variacion_dia_pct": None, "es_total": True,
        },
        {
            "fecha": fecha, "contract_group": "FUTURES STOCK",
            "underlying_asset": None, "traded_contracts_day": 800,
            "open_interest": 50000, "variacion_dia_pct": None, "es_total": True,
        },
        {
            "fecha": fecha, "contract_group": "OPTIONS STOCK",
            "underlying_asset": None, "traded_contracts_day": 400,
            "open_interest": 30000, "variacion_dia_pct": None, "es_total": True,
        },
    ]


def _df_multi() -> pd.DataFrame:
    """DataFrame con 3 fechas para tests de evolución temporal."""
    rows = _df_dia(FECHA_ANT2) + _df_dia(FECHA_ANT) + _df_dia(FECHA)
    return pd.DataFrame(rows)


def _df_simple() -> pd.DataFrame:
    return pd.DataFrame(_df_dia(FECHA))


# ---------------------------------------------------------------------------
# test_generar_top_movers_oi
# ---------------------------------------------------------------------------

def test_generar_top_movers_oi():
    df = _df_simple()
    html = generar_top_movers_oi(df, FECHA, "Test top movers", top_n=3)

    assert isinstance(html, str)
    assert len(html) > 0
    assert "<div" in html
    assert "plotly" in html.lower()


def test_generar_top_movers_oi_sin_columna_variacion():
    df = _df_simple().drop(columns=["variacion_dia_pct"])
    html = generar_top_movers_oi(df, FECHA, "Test sin variacion")

    assert html == ""


def test_generar_top_movers_oi_fecha_sin_datos():
    df = _df_simple()
    html = generar_top_movers_oi(df, date(2000, 1, 1), "Fecha vacía")

    assert html == ""


# ---------------------------------------------------------------------------
# test_generar_evolucion_volumen
# ---------------------------------------------------------------------------

def test_generar_evolucion_volumen():
    df = _df_multi()
    html = generar_evolucion_volumen(df, FECHA, "Test evolución", dias=10)

    assert isinstance(html, str)
    assert len(html) > 0
    assert "<div" in html
    assert "plotly" in html.lower()


def test_generar_evolucion_volumen_datos_insuficientes():
    df = _df_simple()  # solo una fecha
    html = generar_evolucion_volumen(df, FECHA, "Solo un día")

    assert html == ""


# ---------------------------------------------------------------------------
# test_generar_distribucion_categorias
# ---------------------------------------------------------------------------

def test_generar_distribucion_categorias():
    df = _df_simple()
    html = generar_distribucion_categorias(df, FECHA, "Test distribución")

    assert isinstance(html, str)
    assert len(html) > 0
    assert "<div" in html
    assert "plotly" in html.lower()


def test_generar_distribucion_sin_datos():
    df = _df_simple()
    html = generar_distribucion_categorias(df, date(2000, 1, 1), "Sin datos")

    assert html == ""


# ---------------------------------------------------------------------------
# test_parsear_specs_graficos
# ---------------------------------------------------------------------------

BLOQUE_VALIDO = """### WHAT TO WATCH
Vigilar IBEX35.

===GRAFICOS===
{
  "graficos": [
    {
      "tipo": "top_movers_oi",
      "titulo": "Los 5 mayores movimientos de OI",
      "parametros": {"top_n": 5}
    },
    {
      "tipo": "evolucion_volumen",
      "titulo": "El volumen explota un 166%",
      "parametros": {"dias": 10}
    }
  ]
}
===FIN GRAFICOS==="""


def test_parsear_specs_validas():
    specs, texto = parsear_specs_graficos(BLOQUE_VALIDO)

    assert len(specs) == 2
    assert specs[0].tipo == "top_movers_oi"
    assert specs[0].titulo == "Los 5 mayores movimientos de OI"
    assert specs[0].parametros == {"top_n": 5}
    assert specs[1].tipo == "evolucion_volumen"
    assert specs[1].parametros == {"dias": 10}

    # El bloque ===GRAFICOS=== debe haberse eliminado del texto
    assert "===GRAFICOS===" not in texto
    assert "===FIN GRAFICOS===" not in texto
    assert "WHAT TO WATCH" in texto


def test_parsear_specs_invalidas():
    texto_malformado = "Análisis.\n===GRAFICOS===\n{esto no es json\n===FIN GRAFICOS==="
    specs, texto = parsear_specs_graficos(texto_malformado)

    assert specs == []
    assert "===GRAFICOS===" not in texto
    assert "===FIN GRAFICOS===" not in texto


def test_parsear_specs_ausente():
    texto_sin_bloque = "## TITULAR\nSesión tranquila.\n\n## WHAT TO WATCH\nVigilar OI."
    specs, texto = parsear_specs_graficos(texto_sin_bloque)

    assert specs == []
    assert texto == texto_sin_bloque


# ---------------------------------------------------------------------------
# test_generar_graficos_segun_spec (dispatcher)
# ---------------------------------------------------------------------------

def test_generar_graficos_segun_spec():
    df = _df_multi()
    specs = [
        GraficoSpec(tipo="top_movers_oi", titulo="Top movers", parametros={"top_n": 3}),
        GraficoSpec(tipo="evolucion_volumen", titulo="Evolución", parametros={"dias": 5}),
        GraficoSpec(tipo="distribucion_categorias", titulo="Distribución", parametros={}),
    ]
    resultado = generar_graficos_segun_spec(specs, df, FECHA)

    assert "top_movers_oi" in resultado
    assert "evolucion_volumen" in resultado
    assert "distribucion_categorias" in resultado
    assert all("<div" in html for html in resultado.values())


def test_generar_graficos_tipo_desconocido():
    df = _df_simple()
    specs = [GraficoSpec(tipo="tipo_inexistente", titulo="?", parametros={})]
    resultado = generar_graficos_segun_spec(specs, df, FECHA)

    assert resultado == {}
