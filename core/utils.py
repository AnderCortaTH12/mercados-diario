"""
Utilidades comunes compartidas por todos los módulos del sistema.

Contiene helpers para:
- Gestión de fechas: formateo, detección de días hábiles, último día hábil.
- Logging: configuración uniforme con salida a consola y archivo rotativo.
- Carga de configuración: lee fuentes.yaml y expone las fuentes activas.
- Variables de entorno: carga .env y expone ANTHROPIC_API_KEY de forma segura.
- Paths: raíz del proyecto portable entre local y GitHub Actions.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import holidays
import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

DIRECTORIO_PROYECTO: Path = Path(__file__).resolve().parent.parent


def configurar_logging(nivel: str = "INFO", archivo_log: str | None = None) -> None:
    """Configura el sistema de logging con formato consistente.

    Instala un handler de consola siempre. Si se indica `archivo_log` (o se
    usa el valor por defecto ``logs/ejecucion.log``), añade también un
    RotatingFileHandler que crea la carpeta si no existe.

    Args:
        nivel: Nivel de logging ("DEBUG", "INFO", "WARNING", "ERROR").
        archivo_log: Ruta del archivo de log. Por defecto ``logs/ejecucion.log``
            relativo a la raíz del proyecto.
    """
    nivel_numerico = getattr(logging, nivel.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(nivel_numerico)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    ruta_log = Path(archivo_log) if archivo_log else DIRECTORIO_PROYECTO / "logs" / "ejecucion.log"
    ruta_log.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        ruta_log, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)


def cargar_configuracion() -> dict[str, Any]:
    """Lee config/fuentes.yaml y devuelve el diccionario completo de configuración.

    Returns:
        Diccionario con la clave "fuentes" y sus entradas.

    Raises:
        FileNotFoundError: Si no existe config/fuentes.yaml.
        yaml.YAMLError: Si el archivo tiene errores de sintaxis.
    """
    ruta = DIRECTORIO_PROYECTO / "config" / "fuentes.yaml"
    if not ruta.exists():
        raise FileNotFoundError(f"No se encontró el archivo de configuración: {ruta}")
    with ruta.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def obtener_fuentes_activas(config: dict[str, Any]) -> dict[str, dict]:
    """Filtra y devuelve solo las fuentes con ``activa: true``.

    Args:
        config: Diccionario completo leído de fuentes.yaml.

    Returns:
        Diccionario ``{nombre_fuente: config_fuente}`` con solo las fuentes activas.
    """
    return {
        nombre: cfg
        for nombre, cfg in config.get("fuentes", {}).items()
        if cfg.get("activa", False)
    }


def es_dia_habil(fecha: date) -> bool:
    """Determina si una fecha es día hábil bursátil en España.

    Considera festivos nacionales españoles usando la librería ``holidays``.
    No incluye festivos regionales ni puentes de MEFF específicos.

    Args:
        fecha: Fecha a comprobar.

    Returns:
        ``True`` si es lunes–viernes y no es festivo nacional; ``False`` en caso contrario.
    """
    if fecha.weekday() >= 5:
        return False
    festivos = holidays.Spain(years=fecha.year)
    return fecha not in festivos


def obtener_ultimo_dia_habil(fecha_referencia: date | None = None) -> date:
    """Devuelve la fecha del último día hábil bursátil.

    Si ``fecha_referencia`` es día hábil, la devuelve tal cual. Si es fin de
    semana o festivo, retrocede hasta encontrar el día hábil anterior.

    Args:
        fecha_referencia: Fecha de partida. Por defecto, hoy.

    Returns:
        Fecha del último día hábil.
    """
    referencia = fecha_referencia or date.today()
    candidato = referencia
    while not es_dia_habil(candidato):
        candidato -= timedelta(days=1)
    return candidato


def formatear_fecha_ddmmaaaa(fecha: date) -> str:
    """Formatea una fecha en el formato DDMMAAAA que usa el MEFF en sus URLs.

    Args:
        fecha: Fecha a formatear.

    Returns:
        Cadena de 8 caracteres, ej: ``"04062026"`` para el 4 de junio de 2026.
    """
    return fecha.strftime("%d%m%Y")


def formatear_fecha(fecha: date, formato: str = "DDMMAAAA") -> str:
    """Formatea una fecha según la convención indicada.

    Formatos soportados:

    - ``"DDMMAAAA"``  → ``"04062026"``
    - ``"iso"``       → ``"2026-06-04"``
    - ``"YYYYMMDD"``  → ``"20260604"``

    Args:
        fecha: Fecha a formatear.
        formato: Convención de formato deseada.

    Returns:
        Cadena con la fecha formateada.

    Raises:
        ValueError: Si el formato no está soportado.
    """
    mapa = {
        "DDMMAAAA": lambda d: d.strftime("%d%m%Y"),
        "iso": lambda d: d.isoformat(),
        "YYYYMMDD": lambda d: d.strftime("%Y%m%d"),
    }
    if formato not in mapa:
        raise ValueError(f"Formato de fecha no soportado: '{formato}'. Usa uno de: {list(mapa)}")
    return mapa[formato](fecha)


def dia_habil_anterior(fecha: date) -> date:
    """Devuelve el día hábil inmediatamente anterior a ``fecha``.

    Args:
        fecha: Fecha de referencia (no incluida en la búsqueda).

    Returns:
        El día hábil más reciente estrictamente antes de ``fecha``.
    """
    candidato = fecha - timedelta(days=1)
    while not es_dia_habil(candidato):
        candidato -= timedelta(days=1)
    return candidato


def existe_resumen(fecha: date, directorio: Path) -> bool:
    """True si existe el archivo ``{directorio}/{fecha.isoformat()}.md``.

    Args:
        fecha: Fecha del resumen a comprobar.
        directorio: Directorio donde se guardan los resúmenes (ej: resumenes/meff/).

    Returns:
        ``True`` si el archivo .md existe, ``False`` en caso contrario.
    """
    return (directorio / f"{fecha.isoformat()}.md").exists()


def obtener_api_key() -> str:
    """Lee ANTHROPIC_API_KEY del entorno o del archivo .env en la raíz del proyecto.

    Returns:
        La clave de API como string.

    Raises:
        EnvironmentError: Si la variable no está definida en ninguna fuente.
    """
    load_dotenv(DIRECTORIO_PROYECTO / ".env")
    clave = os.environ.get("ANTHROPIC_API_KEY")
    if not clave:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY no está definida. "
            "Añádela al archivo .env o como variable de entorno."
        )
    return clave
