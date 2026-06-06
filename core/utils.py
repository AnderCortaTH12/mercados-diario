"""
Utilidades comunes compartidas por todos los módulos del sistema.

Contiene helpers para:
- Gestión de fechas: obtener la fecha de la última sesión bursátil (lunes–viernes),
  formatear fechas en los distintos formatos que usan las URLs (DDMMAAAA, ISO, etc.).
- Logging: configurar un logger con formato consistente (timestamp + nivel + módulo)
  que escriba tanto a consola como a archivo de log rotativo.
- Carga de configuración: leer fuentes.yaml y devolver el diccionario de fuentes.
- Variables de entorno: cargar el .env local y exponer la ANTHROPIC_API_KEY de forma segura.
- Paths: resolver rutas relativas al directorio raíz del proyecto de forma portable
  (funciona tanto en local como en GitHub Actions).
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directorio raíz del proyecto (un nivel por encima de core/)
DIRECTORIO_PROYECTO: Path = Path(__file__).resolve().parent.parent


def configurar_logging(nivel: str = "INFO", archivo_log: str | None = None) -> None:
    """Configura el sistema de logging con formato consistente.

    Args:
        nivel: Nivel de logging ("DEBUG", "INFO", "WARNING", "ERROR").
        archivo_log: Si se indica, también escribe los logs a ese archivo.
    """
    ...


def cargar_configuracion() -> dict[str, Any]:
    """Lee config/fuentes.yaml y devuelve el diccionario completo de configuración.

    Returns:
        Diccionario con la clave "fuentes" y sus entradas.

    Raises:
        FileNotFoundError: Si no existe config/fuentes.yaml.
        yaml.YAMLError: Si el archivo tiene errores de sintaxis.
    """
    ...


def obtener_fuentes_activas(config: dict[str, Any]) -> dict[str, dict]:
    """Filtra y devuelve solo las fuentes con `activa: true`.

    Args:
        config: Diccionario completo leído de fuentes.yaml.

    Returns:
        Diccionario {nombre_fuente: config_fuente} con solo las fuentes activas.
    """
    ...


def ultima_sesion_bursatil(referencia: date | None = None) -> date:
    """Devuelve la fecha de la última sesión bursátil (lunes–viernes).

    Si `referencia` es día hábil, devuelve esa misma fecha.
    Si es sábado, devuelve el viernes anterior.
    Si es domingo, devuelve el viernes anterior.

    Args:
        referencia: Fecha de referencia. Por defecto, hoy.

    Returns:
        Fecha del último día hábil.
    """
    ...


def formatear_fecha(fecha: date, formato: str = "DDMMAAAA") -> str:
    """Formatea una fecha según la convención de la URL de la fuente.

    Formatos soportados:
    - "DDMMAAAA"  → "06062026"
    - "iso"       → "2026-06-06"
    - "YYYYMMDD"  → "20260606"

    Args:
        fecha: Fecha a formatear.
        formato: Convención de formato deseada.

    Returns:
        Cadena con la fecha formateada.

    Raises:
        ValueError: Si el formato no está soportado.
    """
    ...


def obtener_api_key() -> str:
    """Lee ANTHROPIC_API_KEY del entorno o del archivo .env.

    Returns:
        La clave de API como string.

    Raises:
        EnvironmentError: Si la variable no está definida.
    """
    ...
