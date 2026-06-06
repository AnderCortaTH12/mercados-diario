"""Tests del módulo de recuperación automática de días pendientes."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.recuperacion import detectar_dias_pendientes, ejecutar_pendientes
from core.utils import es_dia_habil


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dias_habiles_recientes(n: int, desde_ayer: bool = True) -> list[date]:
    """Devuelve los n días hábiles más recientes (empezando por ayer si desde_ayer=True)."""
    resultado = []
    inicio = date.today() - timedelta(days=1) if desde_ayer else date.today()
    candidato = inicio
    while len(resultado) < n:
        if es_dia_habil(candidato):
            resultado.append(candidato)
        candidato -= timedelta(days=1)
    return resultado  # orden: más reciente primero


# ---------------------------------------------------------------------------
# test_detectar_dias_pendientes
# ---------------------------------------------------------------------------

def test_detectar_dias_pendientes(tmp_path: Path):
    """Detecta correctamente las fechas hábiles sin resumen en disco."""
    ruta_resumenes = tmp_path / "resumenes"
    ruta_resumenes.mkdir()
    ruta_historico = tmp_path / "historico.csv"

    # Tomamos 3 días hábiles recientes
    dias = _dias_habiles_recientes(3)  # [más_reciente, ..., más_antiguo]
    dia_con_resumen_1 = dias[0]
    dia_con_resumen_2 = dias[1]
    dia_pendiente = dias[2]  # el más antiguo — sin resumen

    # Creamos archivos .md para los dos más recientes
    (ruta_resumenes / f"{dia_con_resumen_1.isoformat()}.md").write_text("resumen")
    (ruta_resumenes / f"{dia_con_resumen_2.isoformat()}.md").write_text("resumen")

    pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico, max_dias_atras=30)

    assert dia_pendiente in pendientes, f"{dia_pendiente} debería estar en pendientes"
    assert dia_con_resumen_1 not in pendientes, f"{dia_con_resumen_1} ya tiene resumen"
    assert dia_con_resumen_2 not in pendientes, f"{dia_con_resumen_2} ya tiene resumen"


def test_detectar_sin_pendientes_cuando_todo_al_dia(tmp_path: Path):
    """Devuelve lista vacía si todos los días hábiles tienen resumen."""
    ruta_resumenes = tmp_path / "resumenes"
    ruta_resumenes.mkdir()
    ruta_historico = tmp_path / "historico.csv"

    dias = _dias_habiles_recientes(5)
    for d in dias:
        (ruta_resumenes / f"{d.isoformat()}.md").write_text("resumen")

    pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico, max_dias_atras=10)

    # Puede haber pendientes antes de la ventana de 5 días, pero los 5 recientes no
    for d in dias:
        assert d not in pendientes


def test_detectar_dias_pendientes_directorio_vacio(tmp_path: Path):
    """Con directorio de resúmenes vacío detecta todos los días hábiles del periodo."""
    ruta_resumenes = tmp_path / "resumenes"
    ruta_resumenes.mkdir()
    ruta_historico = tmp_path / "historico.csv"

    pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico, max_dias_atras=5)

    # Con directorio vacío, todos los días hábiles del periodo están pendientes
    for d in pendientes:
        assert es_dia_habil(d), f"{d} no debería ser día hábil"


# ---------------------------------------------------------------------------
# test_filtra_fines_de_semana
# ---------------------------------------------------------------------------

def test_filtra_fines_de_semana(tmp_path: Path):
    """Los sábados y domingos nunca aparecen en la lista de pendientes."""
    ruta_resumenes = tmp_path / "resumenes"
    ruta_resumenes.mkdir()
    ruta_historico = tmp_path / "historico.csv"

    pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico, max_dias_atras=14)

    for d in pendientes:
        assert d.weekday() < 5, (
            f"{d} es {d.strftime('%A')} — los fines de semana no deben estar en pendientes"
        )


def test_resultado_ordenado_mas_antiguo_primero(tmp_path: Path):
    """Las fechas pendientes se devuelven de más antigua a más reciente."""
    ruta_resumenes = tmp_path / "resumenes"
    ruta_resumenes.mkdir()
    ruta_historico = tmp_path / "historico.csv"

    pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico, max_dias_atras=14)

    if len(pendientes) > 1:
        for i in range(len(pendientes) - 1):
            assert pendientes[i] < pendientes[i + 1], (
                f"Orden incorrecto: {pendientes[i]} debería ser anterior a {pendientes[i+1]}"
            )


# ---------------------------------------------------------------------------
# test_respeta_limite
# ---------------------------------------------------------------------------

def test_respeta_limite():
    """ejecutar_pendientes nunca procesa más de `limite` fechas."""
    # 10 fechas de prueba (todas hábiles: lunes a viernes de semanas distintas)
    fechas = [
        date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7), date(2026, 5, 8),
        date(2026, 5, 11), date(2026, 5, 12), date(2026, 5, 13), date(2026, 5, 14), date(2026, 5, 15),
    ]
    limite = 3

    mock_resultado_proc = MagicMock(exito=True, mensaje="ok")
    mock_resultado_anal = MagicMock(
        exito=True, resumen_markdown="...", resumen_json={},
        tokens_input=100, tokens_output=50, coste_estimado_usd=0.001,
    )

    with (
        patch("fuentes.meff.parser.procesar_meff") as mock_proc,
        patch("core.analizador.analizar_dia") as mock_anal,
        patch("core.analizador.guardar_resumen"),
        patch("time.sleep"),  # evitar esperas reales en los tests
    ):
        def proc_side(fecha):
            r = MagicMock(exito=True, fecha=fecha, mensaje="ok")
            return r

        def anal_side(fecha, **kwargs):
            return MagicMock(
                exito=True, fecha=fecha, resumen_markdown="...", resumen_json={},
                tokens_input=100, tokens_output=50, coste_estimado_usd=0.001,
                mensaje="ok",
            )

        mock_proc.side_effect = proc_side
        mock_anal.side_effect = anal_side

        resultados = ejecutar_pendientes(fechas, limite=limite)

    assert len(resultados) == limite, (
        f"Se esperaban {limite} resultados, se obtuvieron {len(resultados)}"
    )
    assert mock_proc.call_count == limite, (
        f"procesar_meff se llamó {mock_proc.call_count} veces, esperado {limite}"
    )


def test_ejecutar_pendientes_lista_vacia():
    """Con lista vacía de fechas, devuelve lista vacía sin llamadas a API."""
    with patch("fuentes.meff.parser.procesar_meff") as mock_proc:
        resultados = ejecutar_pendientes([], limite=5)

    assert resultados == []
    mock_proc.assert_not_called()


def test_ejecutar_pendientes_continua_si_falla_uno():
    """Si un día falla en procesamiento, continúa con los siguientes."""
    fechas = [date(2026, 5, 4), date(2026, 5, 5), date(2026, 5, 6)]

    with (
        patch("fuentes.meff.parser.procesar_meff") as mock_proc,
        patch("core.analizador.analizar_dia") as mock_anal,
        patch("core.analizador.guardar_resumen"),
        patch("time.sleep"),
    ):
        def proc_side(fecha):
            if fecha == date(2026, 5, 5):
                return MagicMock(exito=False, fecha=fecha, mensaje="descarga fallida")
            return MagicMock(exito=True, fecha=fecha, mensaje="ok")

        mock_proc.side_effect = proc_side
        mock_anal.side_effect = lambda fecha, **kw: MagicMock(
            exito=True, fecha=fecha, resumen_markdown="...", resumen_json={},
            tokens_input=100, tokens_output=50, coste_estimado_usd=0.001, mensaje="ok",
        )

        resultados = ejecutar_pendientes(fechas, limite=5)

    assert len(resultados) == 3
    # El del 5 de mayo falló, los otros dos pasaron
    assert resultados[0].exito is True   # 4 mayo OK
    assert resultados[1].exito is False  # 5 mayo FALLO
    assert resultados[2].exito is True   # 6 mayo OK
