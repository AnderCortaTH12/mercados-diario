"""Tests de buscar_y_procesar_proximo_dia_pendiente y el modo explícito de main()."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fuentes.meff.parser import buscar_y_procesar_proximo_dia_pendiente, main

# Fechas fijas usadas en todos los tests (semana laboral conocida)
FECHA_1 = date(2026, 6, 4)  # jueves — "día más reciente"
FECHA_2 = date(2026, 6, 3)  # miércoles
FECHA_3 = date(2026, 6, 2)  # martes


def _mock_descarga_ok() -> MagicMock:
    return MagicMock(exito=True, mensaje="OK")


def _mock_descarga_404() -> MagicMock:
    return MagicMock(exito=False, mensaje="404 — archivo no publicado.")


def _mock_proc_ok(fecha: date) -> MagicMock:
    return MagicMock(exito=True, fecha=fecha, filas_procesadas=112,
                     anomalias_detectadas=[], mensaje="OK")


def _mock_analisis_ok(fecha: date) -> MagicMock:
    return MagicMock(
        exito=True, fecha=fecha, resumen_markdown="# Resumen", resumen_json={},
        tokens_input=500, tokens_output=200, coste_estimado_usd=0.005, mensaje="OK",
    )


def _run_main(*argv: str) -> int:
    """Ejecuta main() con los args dados y devuelve el código de salida."""
    with patch("sys.argv", ["parser"] + list(argv)), \
         patch("fuentes.meff.parser.configurar_logging"):
        with pytest.raises(SystemExit) as exc_info:
            main()
    return exc_info.value.code


# ---------------------------------------------------------------------------
# buscar_y_procesar_proximo_dia_pendiente — modo automático
# ---------------------------------------------------------------------------

def test_busca_dia_pendiente_exito(tmp_path: Path) -> None:
    """Procesa correctamente el primer día sin resumen que se puede descargar."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)

    with (
        patch("fuentes.meff.parser.obtener_ultimo_dia_habil", return_value=FECHA_1),
        patch("fuentes.meff.parser.descargar_meff", return_value=_mock_descarga_ok()),
        patch("fuentes.meff.parser.procesar_meff", return_value=_mock_proc_ok(FECHA_1)),
        patch("core.analizador.analizar_dia", return_value=_mock_analisis_ok(FECHA_1)),
        patch("core.analizador.guardar_resumen"),
    ):
        resultado = buscar_y_procesar_proximo_dia_pendiente(
            max_dias_atras=3, ruta_resumenes=ruta_resumenes
        )

    assert resultado["estado"] == "procesado"
    assert resultado["fecha_procesada"] == FECHA_1
    assert FECHA_1 in resultado["dias_intentados"]


def test_busca_retrocede_si_existe(tmp_path: Path) -> None:
    """Si el día más reciente ya tiene resumen, retrocede y procesa el anterior."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)
    # FECHA_1 ya tiene resumen
    (ruta_resumenes / f"{FECHA_1.isoformat()}.md").write_text("resumen existente")

    with (
        patch("fuentes.meff.parser.obtener_ultimo_dia_habil", return_value=FECHA_1),
        patch("fuentes.meff.parser.descargar_meff", return_value=_mock_descarga_ok()),
        patch("fuentes.meff.parser.procesar_meff", return_value=_mock_proc_ok(FECHA_2)),
        patch("core.analizador.analizar_dia", return_value=_mock_analisis_ok(FECHA_2)),
        patch("core.analizador.guardar_resumen"),
    ):
        resultado = buscar_y_procesar_proximo_dia_pendiente(
            max_dias_atras=3, ruta_resumenes=ruta_resumenes
        )

    assert resultado["estado"] == "procesado"
    assert resultado["fecha_procesada"] == FECHA_2


def test_busca_retrocede_si_404(tmp_path: Path) -> None:
    """Si el día más reciente da 404, retrocede y procesa el anterior."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)

    mock_descarga = MagicMock()
    mock_descarga.side_effect = [
        _mock_descarga_404(),   # FECHA_1 → 404
        _mock_descarga_ok(),    # FECHA_2 → OK
    ]

    with (
        patch("fuentes.meff.parser.obtener_ultimo_dia_habil", return_value=FECHA_1),
        patch("fuentes.meff.parser.descargar_meff", mock_descarga),
        patch("fuentes.meff.parser.procesar_meff", return_value=_mock_proc_ok(FECHA_2)),
        patch("core.analizador.analizar_dia", return_value=_mock_analisis_ok(FECHA_2)),
        patch("core.analizador.guardar_resumen"),
    ):
        resultado = buscar_y_procesar_proximo_dia_pendiente(
            max_dias_atras=3, ruta_resumenes=ruta_resumenes
        )

    assert resultado["estado"] == "procesado"
    assert resultado["fecha_procesada"] == FECHA_2
    assert mock_descarga.call_count == 2


def test_busca_todos_al_dia(tmp_path: Path) -> None:
    """Si los últimos N días ya tienen resumen, devuelve 'todos_al_dia'."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)
    for fecha in (FECHA_1, FECHA_2, FECHA_3):
        (ruta_resumenes / f"{fecha.isoformat()}.md").write_text("resumen")

    with patch("fuentes.meff.parser.obtener_ultimo_dia_habil", return_value=FECHA_1):
        resultado = buscar_y_procesar_proximo_dia_pendiente(
            max_dias_atras=3, ruta_resumenes=ruta_resumenes
        )

    assert resultado["estado"] == "todos_al_dia"
    assert resultado["fecha_procesada"] is None


def test_busca_ninguno_disponible(tmp_path: Path) -> None:
    """Si ningún día puede descargarse, devuelve 'no_disponible'."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)

    with (
        patch("fuentes.meff.parser.obtener_ultimo_dia_habil", return_value=FECHA_1),
        patch("fuentes.meff.parser.descargar_meff", return_value=_mock_descarga_404()),
    ):
        resultado = buscar_y_procesar_proximo_dia_pendiente(
            max_dias_atras=3, ruta_resumenes=ruta_resumenes
        )

    assert resultado["estado"] == "no_disponible"
    assert resultado["fecha_procesada"] is None
    assert len(resultado["dias_intentados"]) == 3


# ---------------------------------------------------------------------------
# main() — modo explícito (fecha dada)
# ---------------------------------------------------------------------------

def test_fecha_especifica_ya_existe(tmp_path: Path) -> None:
    """Con fecha explícita y resumen existente → warning + exit 0, sin reprocesar."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)
    (ruta_resumenes / "2026-06-04.md").write_text("resumen previo")

    with patch("fuentes.meff.parser.DIRECTORIO_PROYECTO", tmp_path):
        exit_code = _run_main("2026-06-04", "--analizar")

    assert exit_code == 0


def test_fecha_especifica_no_disponible(tmp_path: Path) -> None:
    """Con fecha explícita y descarga fallida → exit 1."""
    ruta_resumenes = tmp_path / "resumenes" / "meff"
    ruta_resumenes.mkdir(parents=True)

    mock_proc_fallo = MagicMock(exito=False, mensaje="Descarga fallida: 404")

    with (
        patch("fuentes.meff.parser.DIRECTORIO_PROYECTO", tmp_path),
        patch("fuentes.meff.parser.procesar_meff", return_value=mock_proc_fallo),
    ):
        exit_code = _run_main("2026-12-31", "--analizar")

    assert exit_code == 1
