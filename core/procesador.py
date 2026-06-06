"""
Módulo de procesamiento y normalización de datos descargados.

Responsabilidades:
- Recibir el archivo crudo descargado (xlsx, csv...) y la clave de la fuente.
- Delegar el parseo al parser específico de esa fuente (fuentes/<nombre>/parser.py).
- Recibir el DataFrame resultante del parser y aplicar transformaciones genéricas:
    · Añadir columna `fecha` con la fecha de la sesión.
    · Añadir columna `fuente` con el identificador de la fuente.
    · Validar que las columnas mínimas requeridas estén presentes.
    · Normalizar tipos de datos (números como float, fechas como datetime).
- Guardar el DataFrame normalizado como CSV en data/<fuente>/YYYY-MM-DD.csv.
- Devolver el DataFrame y la ruta del CSV guardado para que el analizador lo use.

Este módulo nunca sabe cómo está estructurado el Excel de MEFF ni ninguna otra
fuente — eso es responsabilidad exclusiva del parser específico.
"""

from __future__ import annotations

import logging
from pathlib import Path
from datetime import date
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def cargar_parser(nombre_fuente: str):
    """Importa dinámicamente el módulo `parser` de la fuente indicada.

    Args:
        nombre_fuente: Clave de la fuente (ej: "meff"), que coincide con el
            nombre de la carpeta en fuentes/.

    Returns:
        Módulo Python con al menos la función `parsear(ruta: Path) -> pd.DataFrame`.

    Raises:
        ImportError: Si no existe el parser para esa fuente.
    """
    ...


def normalizar_dataframe(df: pd.DataFrame, fuente: str, fecha: date) -> pd.DataFrame:
    """Aplica transformaciones genéricas al DataFrame devuelto por el parser.

    Añade metadatos (columnas `fuente` y `fecha`), verifica tipos y elimina
    filas completamente vacías.

    Args:
        df: DataFrame crudo devuelto por el parser específico.
        fuente: Identificador de la fuente (ej: "meff").
        fecha: Fecha de la sesión.

    Returns:
        DataFrame normalizado y listo para persistir.
    """
    ...


def guardar_csv(df: pd.DataFrame, fuente: str, fecha: date, directorio_base: Optional[Path] = None) -> Path:
    """Persiste el DataFrame como CSV en data/<fuente>/YYYY-MM-DD.csv.

    Crea el directorio si no existe. Si ya hay un archivo para esa fecha,
    lo sobreescribe con un aviso en el log.

    Args:
        df: DataFrame normalizado a guardar.
        fuente: Identificador de la fuente.
        fecha: Fecha de la sesión (determina el nombre de archivo).
        directorio_base: Raíz de la carpeta data/. Por defecto `data/` relativa al proyecto.

    Returns:
        Ruta del CSV guardado.
    """
    ...


def procesar_archivo(
    ruta_archivo: Path,
    config_fuente: dict,
    fecha: date,
) -> tuple[pd.DataFrame, Path]:
    """Punto de entrada principal: parsea, normaliza y persiste los datos de una fuente.

    Args:
        ruta_archivo: Ruta del archivo crudo descargado.
        config_fuente: Configuración de la fuente desde fuentes.yaml.
        fecha: Fecha de la sesión.

    Returns:
        Tupla (DataFrame normalizado, ruta del CSV guardado).
    """
    ...
