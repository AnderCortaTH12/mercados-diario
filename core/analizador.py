"""
Módulo de análisis con IA — genera el resumen ejecutivo diario con Claude API.

Responsabilidades:
- Leer el prompt específico de la fuente desde fuentes/<nombre>/prompt.md.
- Serializar el DataFrame normalizado a un formato compacto (CSV o Markdown)
  para incluirlo en el contexto del prompt.
- Construir el mensaje completo y llamar a la Claude API (modelo configurable).
- Recibir el resumen generado y persistirlo en:
    · resumenes/<fuente>/YYYY-MM-DD.md  → versión legible en Markdown
    · resumenes/<fuente>/YYYY-MM-DD.json → metadatos estructurados (fecha,
      fuente, modelo usado, tokens consumidos, texto del resumen)
- Devolver el texto del resumen y los metadatos de la llamada.

El tono, estructura y profundidad del análisis se controlan íntegramente desde
el archivo prompt.md de cada fuente, no desde este módulo.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import date
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

MODELO_DEFAULT = "claude-opus-4-8"


def cargar_prompt(nombre_fuente: str) -> str:
    """Lee el archivo prompt.md de la fuente indicada.

    Args:
        nombre_fuente: Clave de la fuente (ej: "meff").

    Returns:
        Contenido del prompt como string.

    Raises:
        FileNotFoundError: Si no existe prompt.md para esa fuente.
    """
    ...


def dataframe_a_contexto(df: pd.DataFrame, max_filas: int = 200) -> str:
    """Convierte el DataFrame a texto compacto para incluir en el prompt.

    Genera una tabla Markdown con las filas más relevantes (por volumen o
    interés abierto), truncando si el DataFrame supera `max_filas`.

    Args:
        df: DataFrame normalizado con los datos de la sesión.
        max_filas: Número máximo de filas a incluir en el contexto.

    Returns:
        Representación textual del DataFrame lista para insertar en el prompt.
    """
    ...


def llamar_claude(
    prompt_sistema: str,
    contexto_datos: str,
    modelo: str = MODELO_DEFAULT,
    max_tokens: int = 2048,
) -> dict:
    """Llama a la Claude API y devuelve el texto generado y los metadatos.

    Args:
        prompt_sistema: Instrucciones del sistema (contenido de prompt.md).
        contexto_datos: Datos de la sesión serializados como texto.
        modelo: ID del modelo Claude a usar.
        max_tokens: Límite de tokens en la respuesta.

    Returns:
        Diccionario con claves: `texto` (str), `modelo` (str),
        `tokens_entrada` (int), `tokens_salida` (int).

    Raises:
        anthropic.APIError: Si la llamada a la API falla.
    """
    ...


def guardar_resumen(
    resumen: dict,
    fuente: str,
    fecha: date,
    directorio_base: Optional[Path] = None,
) -> tuple[Path, Path]:
    """Persiste el resumen en Markdown y JSON.

    Args:
        resumen: Diccionario devuelto por `llamar_claude`.
        fuente: Identificador de la fuente.
        fecha: Fecha de la sesión.
        directorio_base: Raíz de la carpeta resumenes/. Por defecto `resumenes/`.

    Returns:
        Tupla (ruta del .md, ruta del .json).
    """
    ...


def analizar(
    df: pd.DataFrame,
    config_fuente: dict,
    fecha: date,
    modelo: str = MODELO_DEFAULT,
) -> tuple[str, Path, Path]:
    """Punto de entrada principal: genera y persiste el resumen ejecutivo.

    Args:
        df: DataFrame normalizado con los datos de la sesión.
        config_fuente: Configuración de la fuente desde fuentes.yaml.
        fecha: Fecha de la sesión.
        modelo: Modelo Claude a usar.

    Returns:
        Tupla (texto del resumen, ruta del .md, ruta del .json).
    """
    ...
