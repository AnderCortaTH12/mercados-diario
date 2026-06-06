"""
Módulo de procesamiento genérico: histórico CSV, métricas derivadas y detección de anomalías.

Responsabilidades:
- Añadir o sobreescribir filas en el CSV histórico acumulativo.
- Calcular métricas temporales (variaciones %, medias móviles, z-scores) sobre
  el histórico completo agrupando por (contract_group, underlying_asset).
- Detectar anomalías en la sesión más reciente aplicando umbrales configurables.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Umbrales de detección de anomalías — ajustar aquí sin tocar la lógica
# ---------------------------------------------------------------------------
UMBRAL_VARIACION_OI_PCT: float = 20.0    # % de variación en Open Interest para alerta
UMBRAL_ZSCORE_VOLUMEN: float = 2.0       # desviaciones estándar para alerta de volumen
UMBRAL_CONTRATOS_MINIMO: int = 100       # contratos mínimos para "actividad significativa"
VENTANA_MEDIA_MOVIL: int = 5             # días para la media móvil de volumen diario
VENTANA_ZSCORE: int = 20                 # días de historia mínima para calcular z-score
VENTANA_SEMANA: int = 5                  # días hábiles que equivalen a ~1 semana


@dataclass
class HistoricoResultado:
    """Resultado de la operación de actualización del histórico CSV."""

    filas_anadidas: int
    filas_sobrescritas: int
    total_filas: int
    ruta: Path


def actualizar_historico(df_dia: pd.DataFrame, ruta_historico: Path) -> HistoricoResultado:
    """Añade o sobreescribe en el CSV histórico los datos del día indicado.

    Si el histórico no existe lo crea desde cero. Si la fecha del ``df_dia``
    ya está presente, elimina esas filas (con aviso en el log) y las sustituye
    por las nuevas. El CSV resultante siempre queda ordenado por fecha.

    Args:
        df_dia: DataFrame con los datos de una sesión. Debe tener columna ``fecha``
            con valores de tipo :class:`datetime.date`.
        ruta_historico: Ruta del archivo CSV histórico (se crea si no existe).

    Returns:
        :class:`HistoricoResultado` con estadísticas de la operación.
    """
    fecha_dia: date = df_dia["fecha"].iloc[0]
    filas_nuevas = len(df_dia)
    filas_sobrescritas = 0

    ruta_historico.parent.mkdir(parents=True, exist_ok=True)

    if not ruta_historico.exists():
        df_dia.to_csv(ruta_historico, index=False, encoding="utf-8")
        logger.info("Histórico creado: %s (%d filas)", ruta_historico.name, filas_nuevas)
        return HistoricoResultado(
            filas_anadidas=filas_nuevas,
            filas_sobrescritas=0,
            total_filas=filas_nuevas,
            ruta=ruta_historico,
        )

    df_hist = pd.read_csv(ruta_historico, encoding="utf-8")
    df_hist["fecha"] = pd.to_datetime(df_hist["fecha"]).dt.date

    mascara_existente = df_hist["fecha"] == fecha_dia
    if mascara_existente.any():
        filas_sobrescritas = int(mascara_existente.sum())
        logger.warning(
            "Sobreescribiendo %d filas ya existentes para %s en %s",
            filas_sobrescritas,
            fecha_dia.isoformat(),
            ruta_historico.name,
        )
        df_hist = df_hist[~mascara_existente]

    df_resultado = pd.concat([df_hist, df_dia], ignore_index=True)
    df_resultado = df_resultado.sort_values("fecha").reset_index(drop=True)
    df_resultado.to_csv(ruta_historico, index=False, encoding="utf-8")

    total = len(df_resultado)
    logger.info(
        "Histórico actualizado: %d filas totales (+%d nuevas, %d sobreescritas)",
        total,
        filas_nuevas,
        filas_sobrescritas,
    )
    return HistoricoResultado(
        filas_anadidas=filas_nuevas,
        filas_sobrescritas=filas_sobrescritas,
        total_filas=total,
        ruta=ruta_historico,
    )


def calcular_metricas_derivadas(df_historico: pd.DataFrame) -> pd.DataFrame:
    """Añade métricas temporales al histórico agrupando por serie de cada contrato.

    Para cada grupo (contract_group, underlying_asset) ordenado por fecha calcula:

    - ``variacion_dia_pct``: variación porcentual de open_interest respecto al
      día anterior disponible en el histórico.
    - ``variacion_semana_pct``: variación porcentual de open_interest respecto a
      hace ``VENTANA_SEMANA`` sesiones.
    - ``media_movil_5d``: media móvil de traded_contracts_day a ``VENTANA_MEDIA_MOVIL``
      días (con min_periods=1 para no perder las primeras filas).
    - ``z_score_volumen``: desviaciones estándar del volumen respecto a la media
      de los últimos ``VENTANA_ZSCORE`` días. ``NaN`` si no hay historia suficiente.

    Args:
        df_historico: DataFrame completo del histórico (todas las fechas disponibles).

    Returns:
        Copia del DataFrame con las cuatro columnas de métricas añadidas,
        ordenado por (contract_group, underlying_asset, fecha).
    """
    df = df_historico.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    df = df.sort_values(["contract_group", "underlying_asset", "fecha"]).reset_index(drop=True)
    grupos = ["contract_group", "underlying_asset"]

    df["variacion_dia_pct"] = df.groupby(grupos, dropna=False)["open_interest"].transform(
        lambda x: x.astype(float).pct_change(1) * 100
    )
    df["variacion_semana_pct"] = df.groupby(grupos, dropna=False)["open_interest"].transform(
        lambda x: x.astype(float).pct_change(VENTANA_SEMANA) * 100
    )
    df["media_movil_5d"] = df.groupby(grupos, dropna=False)["traded_contracts_day"].transform(
        lambda x: x.astype(float).rolling(VENTANA_MEDIA_MOVIL, min_periods=1).mean()
    )

    def _zscore(x: pd.Series) -> pd.Series:
        x = x.astype(float)
        conteo = x.rolling(VENTANA_ZSCORE).count()
        z = (x - x.rolling(VENTANA_ZSCORE).mean()) / x.rolling(VENTANA_ZSCORE).std()
        z[conteo < VENTANA_ZSCORE] = np.nan
        return z

    df["z_score_volumen"] = df.groupby(grupos, dropna=False)["traded_contracts_day"].transform(_zscore)

    return df


def detectar_anomalias(df_metricas: pd.DataFrame, fecha: date) -> list[dict]:
    """Detecta anomalías en los datos de la sesión indicada.

    Reglas aplicadas:

    1. **variacion_oi_extrema**: open_interest varió más de ``UMBRAL_VARIACION_OI_PCT``%
       respecto al día anterior (excluyendo saltos desde cero).
    2. **volumen_anomalo**: |z_score_volumen| > ``UMBRAL_ZSCORE_VOLUMEN`` (solo si hay
       al menos ``VENTANA_ZSCORE`` días de historia).
    3. **actividad_nueva**: el subyacente pasa de open_interest=0 a más de
       ``UMBRAL_CONTRATOS_MINIMO`` contratos en un solo día.

    Args:
        df_metricas: DataFrame con métricas derivadas calculadas por
            :func:`calcular_metricas_derivadas`.
        fecha: Fecha de la sesión a inspeccionar.

    Returns:
        Lista de dicts con claves: ``tipo_anomalia``, ``contract_group``,
        ``underlying_asset``, ``valor``, ``contexto``.
    """
    df_dia = df_metricas[df_metricas["fecha"] == fecha]
    anomalias: list[dict] = []

    for _, fila in df_dia.iterrows():
        cg = fila["contract_group"]
        ua = fila.get("underlying_asset", None)
        if pd.isna(ua):
            ua = None

        var_oi = fila.get("variacion_dia_pct", np.nan)
        z = fila.get("z_score_volumen", np.nan)
        vol = float(fila.get("traded_contracts_day", 0))

        # Regla 1: variación extrema de OI (excluyendo saltos desde cero = inf)
        if pd.notna(var_oi) and not np.isinf(var_oi):
            if abs(var_oi) > UMBRAL_VARIACION_OI_PCT:
                anomalias.append({
                    "tipo_anomalia": "variacion_oi_extrema",
                    "contract_group": cg,
                    "underlying_asset": ua,
                    "valor": round(float(var_oi), 2),
                    "contexto": f"Open Interest varió {var_oi:+.1f}% respecto al día anterior",
                })

        # Regla 2: z-score extremo de volumen
        if pd.notna(z) and not np.isinf(z):
            if abs(z) > UMBRAL_ZSCORE_VOLUMEN:
                anomalias.append({
                    "tipo_anomalia": "volumen_anomalo",
                    "contract_group": cg,
                    "underlying_asset": ua,
                    "valor": round(float(z), 2),
                    "contexto": (
                        f"Volumen del día a {z:+.1f} desviaciones estándar "
                        f"de la media ({VENTANA_ZSCORE}d)"
                    ),
                })

        # Regla 3: actividad nueva significativa (OI previo era 0)
        if pd.notna(var_oi) and np.isinf(var_oi) and vol > UMBRAL_CONTRATOS_MINIMO:
            anomalias.append({
                "tipo_anomalia": "actividad_nueva",
                "contract_group": cg,
                "underlying_asset": ua,
                "valor": vol,
                "contexto": (
                    f"Actividad nueva: {vol:.0f} contratos negociados "
                    f"(open interest previo era 0)"
                ),
            })

    logger.info("Anomalías detectadas para %s: %d", fecha.isoformat(), len(anomalias))
    return anomalias
