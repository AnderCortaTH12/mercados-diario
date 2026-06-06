"""
Módulo de descarga genérica de archivos desde URL parametrizada.

Responsabilidades:
- Leer la configuración de una fuente desde fuentes.yaml.
- Construir la URL final sustituyendo el placeholder {fecha} (y variantes)
  por la fecha de descarga en el formato que requiera cada fuente.
- Descargar el archivo binario (xlsx, csv, json...) y guardarlo en un
  directorio temporal de trabajo.
- Gestionar reintentos, timeouts y errores HTTP de forma uniforme.

No contiene lógica de parseo ni de análisis — solo descarga y persiste el
archivo crudo para que el procesador lo consuma.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)


def construir_url(url_plantilla: str, fecha: date) -> str:
    """Sustituye los placeholders de fecha en la URL plantilla de la fuente.

    Args:
        url_plantilla: Cadena con placeholders {fecha}, {fecha_iso}, {anyo}, {mes}, {dia}.
        fecha: Fecha para la que se construye la URL.

    Returns:
        URL final lista para descargar.
    """
    ...


def descargar_archivo(
    url: str,
    destino: Path,
    timeout: int = 30,
    reintentos: int = 3,
) -> Path:
    """Descarga un archivo desde `url` y lo guarda en `destino`.

    Args:
        url: URL completa del archivo a descargar.
        destino: Ruta local donde se guardará el archivo descargado.
        timeout: Segundos de espera máximos por intento.
        reintentos: Número de intentos ante fallos de red.

    Returns:
        Ruta del archivo descargado.

    Raises:
        requests.HTTPError: Si el servidor responde con código de error.
        RuntimeError: Si se agotan todos los reintentos sin éxito.
    """
    ...


def descargar_fuente(
    config_fuente: dict,
    fecha: date,
    directorio_destino: Optional[Path] = None,
) -> Path:
    """Punto de entrada principal: descarga el archivo de una fuente para una fecha.

    Combina `construir_url` y `descargar_archivo`. Lee el formato del archivo
    desde `config_fuente` para nombrar el fichero descargado correctamente.

    Args:
        config_fuente: Diccionario con la configuración de la fuente (de fuentes.yaml).
        fecha: Fecha de la sesión que se quiere descargar.
        directorio_destino: Carpeta donde dejar el archivo. Por defecto usa un
            subdirectorio temporal en el directorio de trabajo.

    Returns:
        Ruta del archivo crudo descargado.
    """
    ...
