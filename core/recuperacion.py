"""
Módulo de recuperación automática — detecta y procesa días pendientes de resumen.

Responsabilidades:
- Comparar los días hábiles recientes con los resúmenes existentes en disco.
- Ejecutar el pipeline completo (descarga → parseo → análisis IA) para cada
  día que no tenga resumen generado.
- Limitar el número de ejecuciones por seguridad para evitar costes inesperados
  ante periodos largos sin ejecución.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from pathlib import Path

from core.utils import DIRECTORIO_PROYECTO, es_dia_habil

logger = logging.getLogger(__name__)

PAUSA_ENTRE_LLAMADAS_API = 2  # segundos entre llamadas a Claude para no saturar


def detectar_dias_pendientes(
    ruta_resumenes: Path,
    ruta_historico: Path,
    max_dias_atras: int = 10,
) -> list[date]:
    """Detecta días hábiles recientes que no tienen resumen generado.

    Compara los días hábiles de los últimos ``max_dias_atras`` días
    (sin incluir hoy, ya que el mercado del día actual puede no haber
    cerrado aún) con los archivos ``YYYY-MM-DD.md`` en ``ruta_resumenes``.

    Args:
        ruta_resumenes: Directorio que contiene los resúmenes generados.
        ruta_historico: Ruta al CSV histórico (no usado en la comparación,
            recibido para firma de interfaz consistente con el CLI).
        max_dias_atras: Ventana máxima de días naturales a revisar hacia atrás.

    Returns:
        Lista de fechas hábiles sin resumen, ordenadas de más antigua a más reciente.
    """
    hoy = date.today()

    # Días hábiles en la ventana (excluimos hoy: datos del mercado podrían
    # no estar publicados aún si el workflow se ejecuta antes del cierre)
    dias_habiles_ventana: list[date] = []
    for i in range(1, max_dias_atras + 1):
        candidato = hoy - timedelta(days=i)
        if es_dia_habil(candidato):
            dias_habiles_ventana.append(candidato)

    dias_habiles_ventana.sort()  # más antiguo primero

    # Resúmenes existentes: extraemos el stem del archivo (YYYY-MM-DD)
    resumenes_existentes: set[str] = set()
    if ruta_resumenes.exists():
        resumenes_existentes = {
            f.stem
            for f in ruta_resumenes.glob("*.md")
            if f.stem != ".gitkeep"
        }

    pendientes = [d for d in dias_habiles_ventana if d.isoformat() not in resumenes_existentes]

    if pendientes:
        logger.info(
            "%d días hábiles pendientes de resumen en los últimos %d días: %s",
            len(pendientes),
            max_dias_atras,
            [d.isoformat() for d in pendientes],
        )
    else:
        logger.info("Sistema al día — no hay resúmenes pendientes en los últimos %d días.", max_dias_atras)

    return pendientes


def ejecutar_pendientes(
    fechas: list[date],
    limite: int = 5,
) -> list:
    """Ejecuta el pipeline completo para cada fecha pendiente, hasta el límite.

    Para cada fecha: descarga el Excel del MEFF, lo procesa, genera el resumen
    IA y lo guarda en disco. Incluye una pausa de ``PAUSA_ENTRE_LLAMADAS_API``
    segundos entre ejecuciones para no saturar la Claude API.

    Args:
        fechas: Lista de fechas pendientes (normalmente de :func:`detectar_dias_pendientes`).
        limite: Número máximo de fechas a procesar. Si ``fechas`` tiene más de
            ``limite`` elementos, se procesan solo los primeros ``limite``
            (los más antiguos, ya que la lista viene ordenada).

    Returns:
        Lista de ``AnalisisResultado`` para cada fecha procesada.
    """
    from core.analizador import AnalisisResultado, analizar_dia, guardar_resumen
    from fuentes.meff.parser import procesar_meff

    fechas_a_procesar = fechas[:limite]
    total = len(fechas_a_procesar)

    if len(fechas) > limite:
        logger.warning(
            "Hay %d días pendientes pero el límite es %d. "
            "Se procesarán los %d más antiguos. Ejecuta de nuevo para los restantes.",
            len(fechas),
            limite,
            limite,
        )

    resultados: list[AnalisisResultado] = []
    directorio_resumenes = DIRECTORIO_PROYECTO / "resumenes" / "meff"
    ruta_historico = DIRECTORIO_PROYECTO / "data" / "meff_historico.csv"

    for i, fecha in enumerate(fechas_a_procesar):
        logger.info("[%d/%d] Procesando %s...", i + 1, total, fecha.isoformat())

        resultado_proc = procesar_meff(fecha)
        if not resultado_proc.exito:
            logger.error(
                "[%d/%d] FALLO procesando %s: %s",
                i + 1, total, fecha.isoformat(), resultado_proc.mensaje,
            )
            resultados.append(AnalisisResultado(
                exito=False,
                fecha=fecha,
                resumen_markdown=None,
                resumen_json=None,
                tokens_input=0,
                tokens_output=0,
                coste_estimado_usd=0.0,
                mensaje=f"Fallo en procesamiento: {resultado_proc.mensaje}",
            ))
            continue

        ruta_anomalias = (
            DIRECTORIO_PROYECTO / "data" / "anomalias" / f"{fecha.isoformat()}.json"
        )
        resultado = analizar_dia(
            fecha=fecha,
            ruta_historico=ruta_historico,
            ruta_anomalias=ruta_anomalias,
        )

        if resultado.exito:
            guardar_resumen(resultado, directorio_resumenes)
            logger.info(
                "[%d/%d] OK %s — %d tokens, $%.4f USD",
                i + 1, total, fecha.isoformat(),
                resultado.tokens_input + resultado.tokens_output,
                resultado.coste_estimado_usd,
            )
        else:
            logger.error(
                "[%d/%d] FALLO análisis %s: %s",
                i + 1, total, fecha.isoformat(), resultado.mensaje,
            )

        resultados.append(resultado)

        # Pausa entre llamadas para no saturar la API
        if i < total - 1:
            logger.debug("Pausa de %ds antes de la siguiente llamada.", PAUSA_ENTRE_LLAMADAS_API)
            time.sleep(PAUSA_ENTRE_LLAMADAS_API)

    exitosos = sum(1 for r in resultados if r.exito)
    logger.info(
        "Recuperación completada: %d/%d exitosos, coste total estimado: $%.4f USD",
        exitosos,
        total,
        sum(r.coste_estimado_usd for r in resultados),
    )
    return resultados
