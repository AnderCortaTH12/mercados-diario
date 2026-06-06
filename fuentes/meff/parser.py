"""
Parser específico para los archivos Excel del MEFF
(Mercado Español de Futuros y Opciones — BME).

El Excel del MEFF tiene una sola hoja (Sheet1) con 1 fila de cabecera y hasta
~112 filas de datos. Las columnas son fijas pero la cabecera original tiene un
typo conocido: "Traded Conctracts Ytd" (se normaliza a "traded_contracts_ytd").
Las filas con Underlying Asset vacío son filas agregadas: algunas son TOTALes
explícitos (campo Contract Group contiene "TOTAL") y otras son sub-categorías.

Responsabilidades de este módulo:
- Orquestar la descarga del Excel diario (descargar_meff).
- Parsear y normalizar el Excel descargado (parsear_excel).
- Validar la integridad del DataFrame resultante (validar_dataframe).
- Orquestar el pipeline completo descarga→parseo→histórico→métricas→anomalías (procesar_meff).
- Exponer un punto de entrada CLI (python -m fuentes.meff.parser).
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from core.descargador import DescargaResultado, descargar_archivo
from core.procesador import (
    actualizar_historico,
    calcular_metricas_derivadas,
    detectar_anomalias,
)
from core.utils import (
    DIRECTORIO_PROYECTO,
    cargar_configuracion,
    configurar_logging,
    dia_habil_anterior,
    es_dia_habil,
    existe_resumen,
    obtener_ultimo_dia_habil,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Esquema de columnas
# ---------------------------------------------------------------------------

# Mapa de nombre original → snake_case (incluye el typo del Excel real del MEFF)
COLUMN_MAP: dict[str, str] = {
    "Contract Group": "contract_group",
    "Underlying Asset": "underlying_asset",
    "Traded Contracts Day": "traded_contracts_day",
    "Traded Contracts Mtd": "traded_contracts_mtd",
    "Traded Conctracts Ytd": "traded_contracts_ytd",  # typo original del MEFF
    "Traded Contracts Ytd": "traded_contracts_ytd",    # por si BME lo corrige
    "Daily Average Mtd": "daily_average_mtd",
    "Daily Average Ytd": "daily_average_ytd",
    "Open Interest": "open_interest",
}

COLUMNAS_NUMERICAS: list[str] = [
    "traded_contracts_day",
    "traded_contracts_mtd",
    "traded_contracts_ytd",
    "daily_average_mtd",
    "daily_average_ytd",
    "open_interest",
]

COLUMNAS_ESPERADAS: list[str] = [
    "contract_group",
    "underlying_asset",
    "traded_contracts_day",
    "traded_contracts_mtd",
    "traded_contracts_ytd",
    "daily_average_mtd",
    "daily_average_ytd",
    "open_interest",
    "fecha",
    "es_total",
]


# ---------------------------------------------------------------------------
# Dataclasses de resultado
# ---------------------------------------------------------------------------

@dataclass
class ValidacionResultado:
    """Resultado de la validación de un DataFrame del MEFF."""

    valido: bool
    errores: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProcesamientoResultado:
    """Resultado del pipeline completo de procesamiento de una sesión del MEFF."""

    exito: bool
    fecha: date
    filas_procesadas: int
    anomalias_detectadas: list[dict]
    mensaje: str
    ruta_historico: Optional[Path] = None


# ---------------------------------------------------------------------------
# Configuración de la fuente
# ---------------------------------------------------------------------------

def cargar_config_meff() -> dict[str, Any]:
    """Lee config/fuentes.yaml y devuelve únicamente la sección de la fuente MEFF.

    Returns:
        Diccionario con la configuración completa de la entrada ``meff``.

    Raises:
        KeyError: Si la fuente ``meff`` no existe en fuentes.yaml.
        FileNotFoundError: Si no existe config/fuentes.yaml.
    """
    config = cargar_configuracion()
    if "meff" not in config.get("fuentes", {}):
        raise KeyError("La fuente 'meff' no está definida en config/fuentes.yaml")
    return config["fuentes"]["meff"]


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------

def descargar_meff(fecha: date | None = None) -> DescargaResultado:
    """Orquesta la descarga del Excel diario del MEFF para una fecha concreta.

    Si ``fecha`` es ``None`` usa el último día hábil. Si la fecha indicada no
    es día hábil devuelve ``exito=False`` sin intentar la descarga. Si el
    archivo ya existe en disco lo reutiliza.

    El archivo se guarda en ``data/raw/meff/YYYY-MM-DD.xlsx``.

    Args:
        fecha: Fecha de la sesión. ``None`` → último día hábil.

    Returns:
        :class:`~core.descargador.DescargaResultado` con el estado de la operación.
    """
    fecha_sesion = fecha or obtener_ultimo_dia_habil()
    logger.info("Sesión objetivo: %s", fecha_sesion.isoformat())

    if not es_dia_habil(fecha_sesion):
        mensaje = f"{fecha_sesion.isoformat()} no es día hábil. El MEFF no publica datos."
        logger.warning(mensaje)
        return DescargaResultado(exito=False, fecha=fecha_sesion, mensaje=mensaje)

    config = cargar_config_meff()
    ruta_destino = DIRECTORIO_PROYECTO / "data" / "raw" / "meff" / f"{fecha_sesion.isoformat()}.xlsx"

    if ruta_destino.exists():
        logger.info("Archivo ya disponible en disco: %s", ruta_destino)
        return DescargaResultado(
            exito=True,
            fecha=fecha_sesion,
            mensaje=f"Archivo ya disponible: {ruta_destino}",
            ruta_archivo=ruta_destino,
        )

    return descargar_archivo(
        url_plantilla=config["url_plantilla"],
        fecha=fecha_sesion,
        destino=ruta_destino,
        reintentos=config.get("reintentos", 3),
        timeout=config.get("timeout_segundos", 30),
    )


# ---------------------------------------------------------------------------
# Parseo del Excel
# ---------------------------------------------------------------------------

def parsear_excel(ruta_xlsx: Path, fecha: date) -> pd.DataFrame:
    """Lee el Excel del MEFF y devuelve un DataFrame normalizado.

    Aplica el mapeo de columnas (resolviendo el typo "Conctracts"),
    rellena NaN numéricos con 0, añade las columnas ``fecha`` y ``es_total``,
    y hace strip de strings en las columnas de texto.

    Args:
        ruta_xlsx: Ruta al archivo .xlsx descargado del MEFF.
        fecha: Fecha de la sesión (se añade como columna).

    Returns:
        DataFrame con las columnas definidas en ``COLUMNAS_ESPERADAS``.

    Raises:
        FileNotFoundError: Si ``ruta_xlsx`` no existe.
        ValueError: Si el archivo no tiene las columnas esperadas del MEFF.
    """
    if not ruta_xlsx.exists():
        raise FileNotFoundError(f"Archivo no encontrado: {ruta_xlsx}")

    logger.debug("Leyendo Excel: %s", ruta_xlsx.name)
    df = pd.read_excel(ruta_xlsx, header=0, engine="openpyxl")

    # Renombrar columnas (tolerante al typo del MEFF)
    columnas_encontradas = {col: COLUMN_MAP[col] for col in df.columns if col in COLUMN_MAP}
    columnas_sin_mapeo = [col for col in df.columns if col not in COLUMN_MAP]
    if columnas_sin_mapeo:
        logger.warning("Columnas no reconocidas en el Excel: %s", columnas_sin_mapeo)
    df = df.rename(columns=columnas_encontradas)

    # Strip de strings en columnas de texto
    for col in ["contract_group", "underlying_asset"]:
        if col in df.columns:
            df[col] = df[col].apply(lambda x: x.strip() if isinstance(x, str) else x)

    # Rellenar NaN numéricos con 0
    for col in COLUMNAS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Columna de fecha
    df["fecha"] = fecha

    # Columna es_total: True si NaN en underlying_asset Y "TOTAL" en contract_group
    df["es_total"] = (
        df["underlying_asset"].isna()
        & df["contract_group"].str.contains("TOTAL", na=False)
    )

    logger.info("Excel parseado: %d filas, %d columnas", len(df), len(df.columns))
    return df


def validar_dataframe(df: pd.DataFrame) -> ValidacionResultado:
    """Valida la integridad del DataFrame parseado del MEFF.

    Comprueba:
    - Que están presentes todas las columnas esperadas.
    - Que no hay valores negativos en columnas numéricas.
    - Que no hay duplicados en la clave (contract_group, underlying_asset, fecha).
    - Que hay al menos una fila de datos.

    Args:
        df: DataFrame resultado de :func:`parsear_excel`.

    Returns:
        :class:`ValidacionResultado` con el resultado y los mensajes de error/warning.
    """
    errores: list[str] = []
    warnings: list[str] = []

    # Columnas presentes
    faltantes = [c for c in COLUMNAS_ESPERADAS if c not in df.columns]
    if faltantes:
        errores.append(f"Columnas ausentes: {faltantes}")

    if df.empty:
        errores.append("El DataFrame está vacío.")
        return ValidacionResultado(valido=False, errores=errores, warnings=warnings)

    # Sin valores negativos en columnas numéricas
    for col in COLUMNAS_NUMERICAS:
        if col in df.columns:
            negativos = (df[col] < 0).sum()
            if negativos:
                errores.append(f"Columna '{col}' tiene {negativos} valores negativos.")

    # Sin duplicados (NaN en underlying_asset se trata como "__NA__" para la comparación)
    df_check = df.copy()
    df_check["_ua_check"] = df_check["underlying_asset"].fillna("__NA__")
    dupes = df_check.duplicated(subset=["contract_group", "_ua_check", "fecha"]).sum()
    if dupes:
        errores.append(f"Hay {dupes} filas duplicadas en (contract_group, underlying_asset, fecha).")

    # Aviso si hay pocas filas (puede indicar descarga incompleta)
    if len(df) < 10:
        warnings.append(f"Solo {len(df)} filas — posible archivo incompleto.")

    valido = len(errores) == 0
    if valido:
        logger.info("Validación OK: %d filas, %d warnings", len(df), len(warnings))
    else:
        logger.error("Validación fallida: %s", errores)

    return ValidacionResultado(valido=valido, errores=errores, warnings=warnings)


# ---------------------------------------------------------------------------
# Pipeline orquestador
# ---------------------------------------------------------------------------

def procesar_meff(fecha: date | None = None) -> ProcesamientoResultado:
    """Ejecuta el pipeline completo para una sesión del MEFF.

    Pasos:
    1. Determinar la fecha de sesión.
    2. Verificar o descargar el Excel crudo.
    3. Parsear y validar el DataFrame.
    4. Actualizar el histórico CSV.
    5. Calcular métricas derivadas sobre el histórico completo.
    6. Detectar anomalías.
    7. Guardar las anomalías en ``data/anomalias/YYYY-MM-DD.json``.

    Args:
        fecha: Fecha de la sesión. ``None`` → último día hábil.

    Returns:
        :class:`ProcesamientoResultado` con el estado y resultados de la operación.
    """
    fecha_sesion = fecha or obtener_ultimo_dia_habil()

    # Paso 1: obtener el Excel (descargarlo si es necesario)
    ruta_xlsx = DIRECTORIO_PROYECTO / "data" / "raw" / "meff" / f"{fecha_sesion.isoformat()}.xlsx"
    if not ruta_xlsx.exists():
        logger.info("Excel no encontrado en disco, iniciando descarga...")
        resultado_descarga = descargar_meff(fecha_sesion)
        if not resultado_descarga.exito:
            return ProcesamientoResultado(
                exito=False,
                fecha=fecha_sesion,
                filas_procesadas=0,
                anomalias_detectadas=[],
                mensaje=f"Descarga fallida: {resultado_descarga.mensaje}",
            )

    # Paso 2: parsear
    try:
        df_dia = parsear_excel(ruta_xlsx, fecha_sesion)
    except (FileNotFoundError, ValueError) as exc:
        return ProcesamientoResultado(
            exito=False,
            fecha=fecha_sesion,
            filas_procesadas=0,
            anomalias_detectadas=[],
            mensaje=f"Error en parseo: {exc}",
        )

    # Paso 3: validar
    validacion = validar_dataframe(df_dia)
    for w in validacion.warnings:
        logger.warning("Validación warning: %s", w)
    if not validacion.valido:
        return ProcesamientoResultado(
            exito=False,
            fecha=fecha_sesion,
            filas_procesadas=len(df_dia),
            anomalias_detectadas=[],
            mensaje=f"Validación fallida: {validacion.errores}",
        )

    # Paso 4: actualizar histórico
    ruta_historico = DIRECTORIO_PROYECTO / "data" / "meff_historico.csv"
    actualizar_historico(df_dia, ruta_historico)

    # Paso 5: métricas derivadas
    df_hist_completo = pd.read_csv(ruta_historico, encoding="utf-8")
    df_hist_completo["fecha"] = pd.to_datetime(df_hist_completo["fecha"]).dt.date
    df_metricas = calcular_metricas_derivadas(df_hist_completo)

    # Paso 6: anomalías
    anomalias = detectar_anomalias(df_metricas, fecha_sesion)

    # Paso 7: guardar anomalías
    ruta_anomalias_dir = DIRECTORIO_PROYECTO / "data" / "anomalias"
    ruta_anomalias_dir.mkdir(parents=True, exist_ok=True)
    ruta_json = ruta_anomalias_dir / f"{fecha_sesion.isoformat()}.json"
    with ruta_json.open("w", encoding="utf-8") as f:
        json.dump(
            {"fecha": fecha_sesion.isoformat(), "anomalias": anomalias},
            f,
            ensure_ascii=False,
            indent=2,
        )
    logger.info("Anomalías guardadas en %s", ruta_json.name)

    return ProcesamientoResultado(
        exito=True,
        fecha=fecha_sesion,
        filas_procesadas=len(df_dia),
        anomalias_detectadas=anomalias,
        ruta_historico=ruta_historico,
        mensaje=(
            f"Procesamiento completado: {len(df_dia)} filas, "
            f"{len(anomalias)} anomalías detectadas."
        ),
    )


# ---------------------------------------------------------------------------
# Búsqueda inteligente del día pendiente más reciente
# ---------------------------------------------------------------------------

def buscar_y_procesar_proximo_dia_pendiente(
    max_dias_atras: int = 3,
    ruta_resumenes: Path | None = None,
) -> dict:
    """Busca el día hábil más reciente sin resumen y lo procesa.

    Estrategia: empieza por el último día hábil y retrocede hasta
    ``max_dias_atras`` veces si el día ya tiene resumen o la descarga falla.

    Args:
        max_dias_atras: Número máximo de días hábiles a intentar.
        ruta_resumenes: Directorio de resúmenes. Por defecto ``resumenes/meff``.

    Returns:
        Dict con claves ``estado`` (``'procesado'|'todos_al_dia'|'no_disponible'|'error'``),
        ``fecha_procesada``, ``dias_intentados`` y ``mensaje``.
    """
    from core.analizador import analizar_dia, guardar_resumen

    if ruta_resumenes is None:
        ruta_resumenes = DIRECTORIO_PROYECTO / "resumenes" / "meff"

    candidato = obtener_ultimo_dia_habil()
    dias_intentados: list[date] = []
    dias_con_resumen = 0

    for intento in range(max_dias_atras):
        dias_intentados.append(candidato)

        if existe_resumen(candidato, ruta_resumenes):
            logger.info(
                "[%d/%d] %s ya tiene resumen → retrocediendo.",
                intento + 1, max_dias_atras, candidato.isoformat(),
            )
            dias_con_resumen += 1
            candidato = dia_habil_anterior(candidato)
            continue

        logger.info(
            "[%d/%d] Intentando descargar datos de %s...",
            intento + 1, max_dias_atras, candidato.isoformat(),
        )
        resultado_descarga = descargar_meff(candidato)

        if not resultado_descarga.exito:
            logger.warning(
                "[%d/%d] Datos de %s no disponibles (%s) → retrocediendo.",
                intento + 1, max_dias_atras, candidato.isoformat(), resultado_descarga.mensaje,
            )
            candidato = dia_habil_anterior(candidato)
            continue

        resultado_proc = procesar_meff(candidato)
        if not resultado_proc.exito:
            return {
                "estado": "error",
                "fecha_procesada": None,
                "dias_intentados": dias_intentados,
                "mensaje": f"Procesado fallido para {candidato.isoformat()}: {resultado_proc.mensaje}",
            }

        ruta_historico = DIRECTORIO_PROYECTO / "data" / "meff_historico.csv"
        ruta_anomalias = (
            DIRECTORIO_PROYECTO / "data" / "anomalias" / f"{candidato.isoformat()}.json"
        )
        resultado_analisis = analizar_dia(
            fecha=candidato,
            ruta_historico=ruta_historico,
            ruta_anomalias=ruta_anomalias,
        )

        if not resultado_analisis.exito:
            return {
                "estado": "error",
                "fecha_procesada": None,
                "dias_intentados": dias_intentados,
                "mensaje": f"Análisis fallido para {candidato.isoformat()}: {resultado_analisis.mensaje}",
            }

        guardar_resumen(resultado_analisis, ruta_resumenes)
        logger.info(
            "Resumen generado para %s — %d tokens, $%.4f USD",
            candidato.isoformat(),
            resultado_analisis.tokens_input + resultado_analisis.tokens_output,
            resultado_analisis.coste_estimado_usd,
        )
        return {
            "estado": "procesado",
            "fecha_procesada": candidato,
            "dias_intentados": dias_intentados,
            "mensaje": f"Resumen generado para {candidato.isoformat()}.",
        }

    if dias_con_resumen == len(dias_intentados):
        return {
            "estado": "todos_al_dia",
            "fecha_procesada": None,
            "dias_intentados": dias_intentados,
            "mensaje": f"Todos los últimos {len(dias_intentados)} días hábiles ya tienen resumen.",
        }
    return {
        "estado": "no_disponible",
        "fecha_procesada": None,
        "dias_intentados": dias_intentados,
        "mensaje": (
            f"Ningún Excel disponible en los últimos {len(dias_intentados)} días hábiles "
            f"intentados: {', '.join(d.isoformat() for d in dias_intentados)}."
        ),
    }


# ---------------------------------------------------------------------------
# Punto de entrada CLI
# ---------------------------------------------------------------------------

def main() -> None:
    """Punto de entrada de línea de comandos para el MEFF.

    Uso::

        python -m fuentes.meff.parser                          # descarga último día hábil
        python -m fuentes.meff.parser 2026-06-04               # descarga fecha concreta
        python -m fuentes.meff.parser 2026-06-04 --procesar    # pipeline completo
        python -m fuentes.meff.parser --procesar               # pipeline con último día hábil
        python -m fuentes.meff.parser 2026-06-04 --analizar    # procesa + genera resumen IA
        python -m fuentes.meff.parser --analizar               # analiza último día hábil
        python -m fuentes.meff.parser --recuperar              # recupera días pendientes
    """
    from core.analizador import analizar_dia, guardar_resumen

    configurar_logging()

    args = sys.argv[1:]
    procesar = "--procesar" in args
    analizar = "--analizar" in args
    recuperar = "--recuperar" in args
    args_fecha = [a for a in args if not a.startswith("--")]

    fecha: date | None = None
    if args_fecha:
        try:
            fecha = datetime.strptime(args_fecha[0], "%Y-%m-%d").date()
        except ValueError:
            logger.error("Formato de fecha inválido: '%s'. Usa YYYY-MM-DD.", args_fecha[0])
            sys.exit(1)

    if recuperar:
        from core.recuperacion import detectar_dias_pendientes, ejecutar_pendientes

        ruta_resumenes = DIRECTORIO_PROYECTO / "resumenes" / "meff"
        ruta_historico = DIRECTORIO_PROYECTO / "data" / "meff_historico.csv"

        pendientes = detectar_dias_pendientes(ruta_resumenes, ruta_historico)
        if not pendientes:
            logger.info("Sistema al día — no hay resúmenes pendientes.")
            sys.exit(0)

        logger.info(
            "%d días pendientes: %s",
            len(pendientes),
            [d.isoformat() for d in pendientes],
        )
        resultados = ejecutar_pendientes(pendientes)

        exitosos = sum(1 for r in resultados if r.exito)
        fallidos = len(resultados) - exitosos
        logger.info("Recuperación completada: %d OK, %d fallidos.", exitosos, fallidos)
        sys.exit(0 if fallidos == 0 else 1)

    elif analizar:
        if fecha is None:
            # Modo automático: busca el día pendiente más reciente con retry
            resultado = buscar_y_procesar_proximo_dia_pendiente()
            estado = resultado["estado"]
            if estado == "procesado":
                logger.info("OK — %s", resultado["mensaje"])
                sys.exit(0)
            elif estado == "todos_al_dia":
                logger.info("Sistema al día — %s", resultado["mensaje"])
                sys.exit(0)
            elif estado == "no_disponible":
                logger.warning("Archivos no disponibles — %s", resultado["mensaje"])
                sys.exit(0)
            else:  # "error"
                logger.error("FALLO — %s", resultado["mensaje"])
                sys.exit(1)
        else:
            # Modo explícito: el usuario especificó una fecha concreta
            directorio_resumenes = DIRECTORIO_PROYECTO / "resumenes" / "meff"
            if existe_resumen(fecha, directorio_resumenes):
                logger.warning(
                    "El resumen de %s ya existe en %s. No se reprocesa.",
                    fecha.isoformat(), directorio_resumenes,
                )
                sys.exit(0)

            resultado_proc = procesar_meff(fecha)
            if not resultado_proc.exito:
                logger.error("FALLO en procesamiento — %s", resultado_proc.mensaje)
                sys.exit(1)
            logger.info("Procesamiento OK — %s", resultado_proc.mensaje)

            fecha_sesion = resultado_proc.fecha
            ruta_historico = DIRECTORIO_PROYECTO / "data" / "meff_historico.csv"
            ruta_anomalias = (
                DIRECTORIO_PROYECTO / "data" / "anomalias" / f"{fecha_sesion.isoformat()}.json"
            )

            resultado_analisis = analizar_dia(
                fecha=fecha_sesion,
                ruta_historico=ruta_historico,
                ruta_anomalias=ruta_anomalias,
            )

            if resultado_analisis.exito:
                ruta_md, ruta_json = guardar_resumen(resultado_analisis, directorio_resumenes)
                logger.info(
                    "Análisis OK — tokens: %d entrada / %d salida — coste estimado: $%.4f USD",
                    resultado_analisis.tokens_input,
                    resultado_analisis.tokens_output,
                    resultado_analisis.coste_estimado_usd,
                )
                logger.info("Resumen guardado: %s | %s", ruta_md, ruta_json)
                sys.exit(0)
            else:
                logger.error("FALLO en análisis — %s", resultado_analisis.mensaje)
                sys.exit(1)

    elif procesar:
        resultado = procesar_meff(fecha)
        if resultado.exito:
            logger.info("OK — %s", resultado.mensaje)
            sys.exit(0)
        else:
            logger.error("FALLO — %s", resultado.mensaje)
            sys.exit(1)
    else:
        resultado_descarga = descargar_meff(fecha)
        if resultado_descarga.exito:
            logger.info("OK — %s", resultado_descarga.mensaje)
            sys.exit(0)
        else:
            logger.error("FALLO — %s", resultado_descarga.mensaje)
            sys.exit(1)


if __name__ == "__main__":
    main()
