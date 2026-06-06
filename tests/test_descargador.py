"""Tests del módulo de descarga y utilidades de fecha. Sin llamadas de red reales."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.descargador import DescargaResultado, construir_url, descargar_archivo
from core.utils import es_dia_habil, formatear_fecha_ddmmaaaa, obtener_ultimo_dia_habil


# ---------------------------------------------------------------------------
# Utilidades de fecha
# ---------------------------------------------------------------------------

def test_formato_fecha_ddmmaaaa():
    assert formatear_fecha_ddmmaaaa(date(2026, 6, 4)) == "04062026"


def test_formato_fecha_con_mes_y_dia_de_un_digito():
    assert formatear_fecha_ddmmaaaa(date(2026, 1, 5)) == "05012026"


def test_sabado_no_es_habil():
    sabado = date(2026, 6, 6)
    assert sabado.weekday() == 5
    assert not es_dia_habil(sabado)


def test_domingo_no_es_habil():
    domingo = date(2026, 6, 7)
    assert domingo.weekday() == 6
    assert not es_dia_habil(domingo)


def test_lunes_es_habil():
    lunes = date(2026, 6, 8)
    assert lunes.weekday() == 0
    assert es_dia_habil(lunes)


def test_festivo_nacional_no_es_habil():
    # 12 de octubre — Fiesta Nacional de España
    fiesta_nacional = date(2026, 10, 12)
    assert not es_dia_habil(fiesta_nacional)


def test_obtener_ultimo_dia_habil_desde_lunes():
    lunes = date(2026, 6, 8)
    assert obtener_ultimo_dia_habil(lunes) == lunes


def test_obtener_ultimo_dia_habil_desde_sabado():
    sabado = date(2026, 6, 6)
    viernes = date(2026, 6, 5)
    assert obtener_ultimo_dia_habil(sabado) == viernes


def test_obtener_ultimo_dia_habil_desde_domingo():
    domingo = date(2026, 6, 7)
    viernes = date(2026, 6, 5)
    assert obtener_ultimo_dia_habil(domingo) == viernes


# ---------------------------------------------------------------------------
# Construcción de URL
# ---------------------------------------------------------------------------

URL_PLANTILLA = (
    "https://www.meff.es/docs/Ficheros/ficherosest/"
    "000000000000000000000000{fecha}000000002000000010040003n0000.xlsx"
)


def test_construccion_url():
    fecha = date(2026, 6, 4)
    url = construir_url(URL_PLANTILLA, fecha)
    assert "04062026" in url
    assert url.endswith(".xlsx")
    assert "{fecha}" not in url


def test_construccion_url_formato_correcto():
    fecha = date(2026, 6, 4)
    url = construir_url(URL_PLANTILLA, fecha)
    expected = (
        "https://www.meff.es/docs/Ficheros/ficherosest/"
        "00000000000000000000000004062026000000002000000010040003n0000.xlsx"
    )
    assert url == expected


# ---------------------------------------------------------------------------
# Descarga (mockeada — sin red)
# ---------------------------------------------------------------------------

def test_descarga_exitosa(tmp_path: Path):
    destino = tmp_path / "test.xlsx"
    contenido_falso = b"PK\x03\x04" + b"\x00" * 100  # firma de ZIP/xlsx

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    mock_response.iter_content = MagicMock(return_value=[contenido_falso])
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)

    with patch("core.descargador.requests.get", return_value=mock_response):
        resultado = descargar_archivo(URL_PLANTILLA, date(2026, 6, 4), destino)

    assert resultado.exito is True
    assert resultado.ruta_archivo == destino
    assert resultado.codigo_http == 200
    assert destino.exists()


def test_descarga_404_devuelve_exito_false(tmp_path: Path):
    destino = tmp_path / "test.xlsx"

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.headers = {}

    with patch("core.descargador.requests.get", return_value=mock_response):
        resultado = descargar_archivo(URL_PLANTILLA, date(2026, 6, 4), destino)

    assert resultado.exito is False
    assert resultado.codigo_http == 404
    assert "no publicado" in resultado.mensaje.lower()
    assert not destino.exists()


def test_descarga_con_error_de_red_reintenta(tmp_path: Path):
    import requests as req

    destino = tmp_path / "test.xlsx"

    with patch("core.descargador.requests.get", side_effect=req.exceptions.ConnectionError("timeout")):
        with patch("core.descargador.time.sleep"):  # evita esperar en el test
            resultado = descargar_archivo(URL_PLANTILLA, date(2026, 6, 4), destino, reintentos=2)

    assert resultado.exito is False
    assert not destino.exists()
