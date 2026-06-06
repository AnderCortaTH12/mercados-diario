"""Tests del parseo, validación, histórico, métricas y detección de anomalías del MEFF."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook

from core.procesador import (
    UMBRAL_CONTRATOS_MINIMO,
    UMBRAL_VARIACION_OI_PCT,
    UMBRAL_ZSCORE_VOLUMEN,
    VENTANA_ZSCORE,
    HistoricoResultado,
    actualizar_historico,
    calcular_metricas_derivadas,
    detectar_anomalias,
)
from fuentes.meff.parser import (
    COLUMNAS_ESPERADAS,
    ValidacionResultado,
    parsear_excel,
    validar_dataframe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FECHA_TEST = date(2026, 6, 4)
FECHA_TEST_2 = date(2026, 6, 3)
FECHA_TEST_3 = date(2026, 6, 2)


def crear_excel_meff(ruta: Path, filas_datos: list[list] | None = None) -> Path:
    """Crea un Excel mínimo con la estructura real del MEFF (incluyendo el typo).

    Args:
        ruta: Ruta donde guardar el archivo .xlsx.
        filas_datos: Lista de listas con las filas de datos (sin cabecera).
            Si None, se usan datos de ejemplo por defecto.

    Returns:
        La misma ``ruta`` una vez guardado el archivo.
    """
    if filas_datos is None:
        filas_datos = [
            # contract_group, underlying_asset, day, mtd, ytd, avg_mtd, avg_ytd, oi
            ["FUTURES STOCK TOTAL", None, 100, 500, 5000, 125, 250, 10000],
            ["FUTURES STOCK", "ACS",   20,  100, 1000,  25,  50,  2000],
            ["FUTURES STOCK", "BBVA",  30,  150, 1500,  37,  75,  3000],
            ["FUTURES STOCK", "ITX",   50,  250, 2500,  63, 125,  5000],
        ]

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"

    # Cabecera con el typo original del MEFF ("Conctracts" en Ytd)
    ws.append([
        "Contract Group",
        "Underlying Asset",
        "Traded Contracts Day",
        "Traded Contracts Mtd",
        "Traded Conctracts Ytd",   # typo intencional
        "Daily Average Mtd",
        "Daily Average Ytd",
        "Open Interest",
    ])
    for fila in filas_datos:
        ws.append(fila)

    wb.save(ruta)
    return ruta


def crear_df_dia(fecha: date, filas: list[dict] | None = None) -> pd.DataFrame:
    """Crea un DataFrame de sesión con la estructura esperada del histórico."""
    if filas is None:
        filas = [
            {"contract_group": "FUTURES STOCK", "underlying_asset": "ACS",
             "traded_contracts_day": 20, "traded_contracts_mtd": 100,
             "traded_contracts_ytd": 1000, "daily_average_mtd": 25,
             "daily_average_ytd": 50, "open_interest": 2000,
             "fecha": fecha, "es_total": False},
            {"contract_group": "FUTURES STOCK", "underlying_asset": "BBVA",
             "traded_contracts_day": 30, "traded_contracts_mtd": 150,
             "traded_contracts_ytd": 1500, "daily_average_mtd": 37,
             "daily_average_ytd": 75, "open_interest": 3000,
             "fecha": fecha, "es_total": False},
        ]
    return pd.DataFrame(filas)


# ---------------------------------------------------------------------------
# Tests: parseo del Excel
# ---------------------------------------------------------------------------

def test_parseo_excel_columnas(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    for col in COLUMNAS_ESPERADAS:
        assert col in df.columns, f"Falta columna: {col}"


def test_parseo_excel_numero_filas(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    # 4 filas de datos (1 TOTAL + 3 individuales)
    assert len(df) == 4


def test_parseo_excel_fecha_correcta(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    assert all(df["fecha"] == FECHA_TEST)


def test_parseo_excel_es_total(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    # Solo la primera fila ("FUTURES STOCK TOTAL" + None) debe ser es_total=True
    assert df["es_total"].sum() == 1
    assert df.loc[df["es_total"], "contract_group"].iloc[0] == "FUTURES STOCK TOTAL"


def test_parseo_excel_nan_numerico_a_cero(tmp_path: Path):
    filas = [
        ["FUTURES STOCK", "ACS", None, None, None, None, None, None],
    ]
    ruta = crear_excel_meff(tmp_path / "test.xlsx", filas_datos=filas)
    df = parsear_excel(ruta, FECHA_TEST)
    assert df["open_interest"].iloc[0] == 0
    assert df["traded_contracts_day"].iloc[0] == 0


def test_parseo_excel_typo_columna_ytd(tmp_path: Path):
    # El Excel tiene "Traded Conctracts Ytd" — debe mapearse a "traded_contracts_ytd"
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    assert "traded_contracts_ytd" in df.columns
    assert "Traded Conctracts Ytd" not in df.columns


def test_parseo_excel_valores_numericos(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    fila_acs = df[df["underlying_asset"] == "ACS"].iloc[0]
    assert fila_acs["traded_contracts_day"] == 20
    assert fila_acs["open_interest"] == 2000


# ---------------------------------------------------------------------------
# Tests: validación
# ---------------------------------------------------------------------------

def test_validacion_dataframe_valido(tmp_path: Path):
    ruta = crear_excel_meff(tmp_path / "test.xlsx")
    df = parsear_excel(ruta, FECHA_TEST)
    resultado = validar_dataframe(df)
    assert resultado.valido is True
    assert resultado.errores == []


def test_validacion_detecta_columna_faltante():
    df = crear_df_dia(FECHA_TEST)
    df = df.drop(columns=["open_interest"])
    resultado = validar_dataframe(df)
    assert resultado.valido is False
    assert any("open_interest" in e for e in resultado.errores)


def test_validacion_detecta_valores_negativos():
    df = crear_df_dia(FECHA_TEST)
    df.loc[0, "open_interest"] = -100
    resultado = validar_dataframe(df)
    assert resultado.valido is False
    assert any("negativo" in e for e in resultado.errores)


def test_validacion_detecta_duplicados():
    df = crear_df_dia(FECHA_TEST)
    df_dupes = pd.concat([df, df], ignore_index=True)
    resultado = validar_dataframe(df_dupes)
    assert resultado.valido is False
    assert any("duplicad" in e for e in resultado.errores)


def test_validacion_dataframe_vacio():
    df = pd.DataFrame()
    resultado = validar_dataframe(df)
    assert resultado.valido is False


# ---------------------------------------------------------------------------
# Tests: histórico CSV
# ---------------------------------------------------------------------------

def test_actualizar_historico_crea_archivo(tmp_path: Path):
    ruta = tmp_path / "historico.csv"
    df = crear_df_dia(FECHA_TEST)
    resultado = actualizar_historico(df, ruta)

    assert ruta.exists()
    assert isinstance(resultado, HistoricoResultado)
    assert resultado.filas_anadidas == 2
    assert resultado.filas_sobrescritas == 0
    assert resultado.total_filas == 2


def test_actualizar_historico_append(tmp_path: Path):
    ruta = tmp_path / "historico.csv"
    df1 = crear_df_dia(FECHA_TEST_3)
    df2 = crear_df_dia(FECHA_TEST_2)

    actualizar_historico(df1, ruta)
    resultado = actualizar_historico(df2, ruta)

    assert resultado.total_filas == 4
    assert resultado.filas_sobrescritas == 0

    df_leido = pd.read_csv(ruta)
    fechas = pd.to_datetime(df_leido["fecha"]).dt.date.unique()
    assert FECHA_TEST_3 in fechas
    assert FECHA_TEST_2 in fechas


def test_actualizar_historico_sobreescribe_fecha_existente(tmp_path: Path):
    ruta = tmp_path / "historico.csv"
    df_original = crear_df_dia(FECHA_TEST)
    actualizar_historico(df_original, ruta)

    df_nuevo = crear_df_dia(FECHA_TEST)
    df_nuevo.loc[0, "open_interest"] = 9999
    resultado = actualizar_historico(df_nuevo, ruta)

    assert resultado.filas_sobrescritas == 2
    assert resultado.total_filas == 2

    df_leido = pd.read_csv(ruta)
    assert df_leido[df_leido["underlying_asset"] == "ACS"]["open_interest"].iloc[0] == 9999


# ---------------------------------------------------------------------------
# Tests: métricas derivadas
# ---------------------------------------------------------------------------

def _historico_tres_dias() -> pd.DataFrame:
    """Construye un histórico de 3 días con un subyacente para test de métricas."""
    filas = []
    valores_oi = [1000, 1200, 900]
    valores_vol = [100, 150, 80]
    fechas = [FECHA_TEST_3, FECHA_TEST_2, FECHA_TEST]
    for f, oi, vol in zip(fechas, valores_oi, valores_vol):
        filas.append({
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "ITX",
            "traded_contracts_day": vol,
            "traded_contracts_mtd": vol * 5,
            "traded_contracts_ytd": vol * 50,
            "daily_average_mtd": vol,
            "daily_average_ytd": vol,
            "open_interest": oi,
            "fecha": f,
            "es_total": False,
        })
    return pd.DataFrame(filas)


def test_calcular_metricas_variacion_dia(tmp_path: Path):
    df_hist = _historico_tres_dias()
    df_metricas = calcular_metricas_derivadas(df_hist)

    # Día 2 (FECHA_TEST_2): OI pasó de 1000 a 1200 → +20%
    fila_d2 = df_metricas[
        (df_metricas["fecha"] == FECHA_TEST_2) & (df_metricas["underlying_asset"] == "ITX")
    ].iloc[0]
    assert abs(fila_d2["variacion_dia_pct"] - 20.0) < 0.01


def test_calcular_metricas_variacion_dia_negativa():
    df_hist = _historico_tres_dias()
    df_metricas = calcular_metricas_derivadas(df_hist)

    # Día 3 (FECHA_TEST): OI pasó de 1200 a 900 → -25%
    fila_d3 = df_metricas[
        (df_metricas["fecha"] == FECHA_TEST) & (df_metricas["underlying_asset"] == "ITX")
    ].iloc[0]
    assert abs(fila_d3["variacion_dia_pct"] - (-25.0)) < 0.01


def test_calcular_metricas_primer_dia_sin_variacion():
    df_hist = _historico_tres_dias()
    df_metricas = calcular_metricas_derivadas(df_hist)

    # Primer día no tiene día anterior → variacion_dia_pct NaN
    fila_d1 = df_metricas[
        (df_metricas["fecha"] == FECHA_TEST_3) & (df_metricas["underlying_asset"] == "ITX")
    ].iloc[0]
    assert pd.isna(fila_d1["variacion_dia_pct"])


def test_calcular_metricas_zscore_nan_sin_historia():
    df_hist = _historico_tres_dias()
    df_metricas = calcular_metricas_derivadas(df_hist)
    # Con solo 3 días (< VENTANA_ZSCORE=20), z_score debe ser NaN
    assert df_metricas["z_score_volumen"].isna().all()


# ---------------------------------------------------------------------------
# Tests: detección de anomalías
# ---------------------------------------------------------------------------

def _df_metricas_con_anomalias() -> pd.DataFrame:
    """DataFrame con métricas pre-calculadas que disparan las reglas de anomalía."""
    return pd.DataFrame([
        {
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "ACS",
            "traded_contracts_day": 1000,
            "open_interest": 5000,
            "fecha": FECHA_TEST,
            "variacion_dia_pct": 30.0,     # > UMBRAL_VARIACION_OI_PCT
            "variacion_semana_pct": 5.0,
            "media_movil_5d": 800.0,
            "z_score_volumen": float("nan"),
        },
        {
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "BBVA",
            "traded_contracts_day": 5000,
            "open_interest": 10000,
            "fecha": FECHA_TEST,
            "variacion_dia_pct": 5.0,
            "variacion_semana_pct": 2.0,
            "media_movil_5d": 500.0,
            "z_score_volumen": 3.0,        # > UMBRAL_ZSCORE_VOLUMEN
        },
        {
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "ITX",
            "traded_contracts_day": 200,
            "open_interest": 500,
            "fecha": FECHA_TEST,
            "variacion_dia_pct": float("inf"),  # OI previo era 0 → actividad nueva
            "variacion_semana_pct": float("nan"),
            "media_movil_5d": 200.0,
            "z_score_volumen": float("nan"),
        },
        {
            "contract_group": "FUTURES STOCK",
            "underlying_asset": "SAN",
            "traded_contracts_day": 100,
            "open_interest": 2000,
            "fecha": FECHA_TEST,
            "variacion_dia_pct": 2.0,      # normal
            "variacion_semana_pct": 1.0,
            "media_movil_5d": 100.0,
            "z_score_volumen": 0.5,        # normal
        },
    ])


def test_detectar_anomalia_variacion_oi():
    df = _df_metricas_con_anomalias()
    anomalias = detectar_anomalias(df, FECHA_TEST)
    tipos = [a["tipo_anomalia"] for a in anomalias]
    assert "variacion_oi_extrema" in tipos
    extrema = next(a for a in anomalias if a["tipo_anomalia"] == "variacion_oi_extrema")
    assert extrema["underlying_asset"] == "ACS"


def test_detectar_anomalia_volumen_zscore():
    df = _df_metricas_con_anomalias()
    anomalias = detectar_anomalias(df, FECHA_TEST)
    tipos = [a["tipo_anomalia"] for a in anomalias]
    assert "volumen_anomalo" in tipos
    vol = next(a for a in anomalias if a["tipo_anomalia"] == "volumen_anomalo")
    assert vol["underlying_asset"] == "BBVA"


def test_detectar_anomalia_actividad_nueva():
    df = _df_metricas_con_anomalias()
    anomalias = detectar_anomalias(df, FECHA_TEST)
    tipos = [a["tipo_anomalia"] for a in anomalias]
    assert "actividad_nueva" in tipos
    nueva = next(a for a in anomalias if a["tipo_anomalia"] == "actividad_nueva")
    assert nueva["underlying_asset"] == "ITX"


def test_sin_anomalias_en_datos_normales():
    df = pd.DataFrame([{
        "contract_group": "FUTURES STOCK",
        "underlying_asset": "SAN",
        "traded_contracts_day": 100,
        "open_interest": 2000,
        "fecha": FECHA_TEST,
        "variacion_dia_pct": 2.0,
        "variacion_semana_pct": 1.0,
        "media_movil_5d": 100.0,
        "z_score_volumen": 0.5,
    }])
    anomalias = detectar_anomalias(df, FECHA_TEST)
    assert anomalias == []
