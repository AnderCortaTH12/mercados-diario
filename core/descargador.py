"""
Módulo de descarga genérica de archivos desde URL parametrizada.

Responsabilidades:
- Construir la URL final sustituyendo el placeholder {fecha} en la plantilla.
- Descargar el archivo binario con reintentos y backoff exponencial.
- Devolver un DescargaResultado con el estado de la operación.
- Logging detallado de cada intento.

No contiene lógica de parseo ni de análisis — solo descarga y persiste el
archivo crudo para que el procesador lo consuma.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import requests

from core.utils import formatear_fecha_ddmmaaaa

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
}

CONTENT_TYPE_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class DescargaResultado:
    """Resultado de un intento de descarga de archivo."""

    exito: bool
    fecha: date
    mensaje: str
    ruta_archivo: Optional[Path] = None
    codigo_http: Optional[int] = None


def construir_url(url_plantilla: str, fecha: date) -> str:
    """Sustituye los placeholders de fecha en la URL plantilla de la fuente.

    Placeholders soportados:

    - ``{fecha}``     → DDMMAAAA (ej: ``"04062026"``)
    - ``{fecha_iso}`` → YYYY-MM-DD (ej: ``"2026-06-04"``)
    - ``{anyo}``      → YYYY (ej: ``"2026"``)
    - ``{mes}``       → MM (ej: ``"06"``)
    - ``{dia}``       → DD (ej: ``"04"``)

    Args:
        url_plantilla: Cadena con uno o más placeholders de los listados arriba.
        fecha: Fecha para la que se construye la URL.

    Returns:
        URL final lista para descargar.
    """
    return url_plantilla.format(
        fecha=formatear_fecha_ddmmaaaa(fecha),
        fecha_iso=fecha.isoformat(),
        anyo=fecha.strftime("%Y"),
        mes=fecha.strftime("%m"),
        dia=fecha.strftime("%d"),
    )


def descargar_archivo(
    url_plantilla: str,
    fecha: date,
    destino: Path,
    reintentos: int = 3,
    timeout: int = 30,
) -> DescargaResultado:
    """Descarga el archivo de una fuente para una fecha concreta.

    Construye la URL, ejecuta la petición GET con reintentos y backoff
    exponencial (1 s, 2 s, 4 s…), y guarda el contenido binario en ``destino``.

    Args:
        url_plantilla: Plantilla de URL con placeholder ``{fecha}``.
        fecha: Fecha de la sesión a descargar.
        destino: Ruta local donde se guardará el archivo descargado.
        reintentos: Número máximo de intentos ante fallos de red.
        timeout: Segundos de espera por intento antes de abortar.

    Returns:
        :class:`DescargaResultado` con el estado de la operación.
    """
    url = construir_url(url_plantilla, fecha)
    logger.info("Iniciando descarga | fecha=%s | url=%s", fecha.isoformat(), url)

    ultimo_error: Exception | None = None

    for intento in range(1, reintentos + 1):
        logger.debug("Intento %d/%d → %s", intento, reintentos, url)
        try:
            respuesta = requests.get(url, headers=HEADERS, timeout=timeout, stream=True)
        except requests.exceptions.Timeout as exc:
            ultimo_error = exc
            logger.warning("Intento %d/%d — timeout (%ds). %s", intento, reintentos, timeout,
                           "Reintentando..." if intento < reintentos else "Sin más intentos.")
        except requests.exceptions.ConnectionError as exc:
            ultimo_error = exc
            logger.warning("Intento %d/%d — error de conexión: %s. %s", intento, reintentos, exc,
                           "Reintentando..." if intento < reintentos else "Sin más intentos.")
        else:
            if respuesta.status_code == 404:
                logger.warning("HTTP 404 — archivo no publicado o no existe para %s", fecha.isoformat())
                return DescargaResultado(
                    exito=False,
                    fecha=fecha,
                    mensaje=f"Archivo no publicado todavía o no existe para la fecha {fecha.isoformat()}.",
                    codigo_http=404,
                )

            if respuesta.status_code != 200:
                logger.warning("HTTP %d en intento %d/%d. %s",
                               respuesta.status_code, intento, reintentos,
                               "Reintentando..." if intento < reintentos else "Sin más intentos.")
                ultimo_error = requests.HTTPError(response=respuesta)
                respuesta.close()
            else:
                content_type = respuesta.headers.get("Content-Type", "")
                if CONTENT_TYPE_XLSX not in content_type and "octet-stream" not in content_type:
                    logger.warning(
                        "Content-Type inesperado: '%s'. Se guardará el archivo igualmente.", content_type
                    )

                destino.parent.mkdir(parents=True, exist_ok=True)
                with destino.open("wb") as f:
                    for chunk in respuesta.iter_content(chunk_size=8192):
                        f.write(chunk)

                logger.info(
                    "Descarga completada | archivo=%s | tamaño=%.1f KB",
                    destino.name,
                    destino.stat().st_size / 1024,
                )
                return DescargaResultado(
                    exito=True,
                    fecha=fecha,
                    mensaje=f"Archivo descargado correctamente en {destino}",
                    ruta_archivo=destino,
                    codigo_http=200,
                )

        if intento < reintentos:
            espera = 2 ** (intento - 1)
            logger.debug("Esperando %ds antes del siguiente intento.", espera)
            time.sleep(espera)

    mensaje = f"Descarga fallida tras {reintentos} intentos: {ultimo_error}"
    logger.error(mensaje)
    return DescargaResultado(exito=False, fecha=fecha, mensaje=mensaje)
