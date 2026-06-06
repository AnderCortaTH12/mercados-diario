"""
Módulo de análisis con IA — genera el resumen ejecutivo diario con Claude API.

Responsabilidades:
- Leer el prompt desde fuentes/meff/prompt.md.
- Construir contexto compacto (CSV inline + header estructurado) para minimizar tokens.
- Llamar a la Claude API con el prompt y el contexto.
- Persistir el resumen en resumenes/meff/YYYY-MM-DD.md y .json.
- Devolver un AnalisisResultado con métricas de uso y coste estimado.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from core.utils import DIRECTORIO_PROYECTO

logger = logging.getLogger(__name__)

MODELO_DEFAULT = "claude-sonnet-4-5"
PRECIO_INPUT_POR_MTOKEN = 3.0
PRECIO_OUTPUT_POR_MTOKEN = 15.0

# Límites para la selección de contratos del día actual
TOP_VOL = 15
TOP_OI = 15
TOP_VAR = 10


@dataclass
class AnalisisResultado:
    """Resultado de una llamada de análisis a Claude API."""

    exito: bool
    fecha: date
    resumen_markdown: Optional[str]
    resumen_json: Optional[dict]
    tokens_input: int
    tokens_output: int
    coste_estimado_usd: float
    mensaje: str


def cargar_prompt(ruta: Path) -> str:
    """Lee el archivo prompt.md desde la ruta indicada.

    Args:
        ruta: Ruta al archivo prompt.md.

    Returns:
        Contenido del prompt como string.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    if not ruta.exists():
        raise FileNotFoundError(f"Prompt no encontrado: {ruta}")
    return ruta.read_text(encoding="utf-8")


def _fila_a_csv(r: pd.Series, cols: list[str]) -> str:
    """Serializa una fila del DataFrame en formato CSV inline."""
    vals = []
    for c in cols:
        v = r[c]
        if pd.isna(v) or (isinstance(v, float) and np.isinf(v)):
            vals.append("")
        elif isinstance(v, float):
            vals.append(f"{v:.2f}")
        else:
            vals.append(str(v))
    return ",".join(vals)


def construir_contexto_meff(
    df_historico: pd.DataFrame,
    df_metricas: pd.DataFrame,
    anomalias: list[dict],
    fecha: date,
    dias_contexto: int = 5,
) -> str:
    """Construye el contexto textual compacto para el prompt del MEFF.

    Estrategia de compresión:
    - DÍA ACTUAL: siempre incluye filas TOTAL; para individuales, unión de
      top-15 por volumen, top-15 por OI absoluto, top-10 por |ΔOI%|
      y filas de anomalías. Serializado en CSV inline.
    - DÍAS ANTERIORES: solo agregados por contract_group (filas es_total=True
      o suma por grupo) + serie histórica de los subyacentes seleccionados hoy.
    - Encabezado con métricas clave (vol total, comparación vs media, OI, anomalías).

    Args:
        df_historico: DataFrame del histórico completo.
        df_metricas: DataFrame con métricas derivadas calculadas.
        anomalias: Lista de dicts de anomalías detectadas.
        fecha: Fecha de la sesión objetivo.
        dias_contexto: Número de sesiones a incluir como contexto histórico.

    Returns:
        Texto compacto con header + CSV del día + contexto histórico + anomalías.
    """
    df = df_metricas.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    fechas_disponibles = sorted(df["fecha"].unique())
    dias_historia = len(fechas_disponibles)

    if fecha in fechas_disponibles:
        idx = fechas_disponibles.index(fecha)
        ventana = fechas_disponibles[max(0, idx - dias_contexto + 1): idx + 1]
    else:
        ventana = [f for f in fechas_disponibles if f <= fecha][-dias_contexto:]
    fechas_anteriores = [f for f in ventana if f != fecha]

    df_hoy = df[df["fecha"] == fecha].copy()
    has_ua = "underlying_asset" in df_hoy.columns
    has_total = "es_total" in df_hoy.columns

    # ---- HEADER CON MÉTRICAS CLAVE ----
    df_ind = df_hoy[df_hoy["underlying_asset"].notna()] if has_ua else df_hoy
    total_vol_hoy = int(df_ind["traded_contracts_day"].sum()) if not df_ind.empty else 0
    total_oi_hoy = int(df_ind["open_interest"].sum()) if not df_ind.empty else 0

    if fechas_anteriores:
        df_ant_all = df[df["fecha"].isin(fechas_anteriores)]
        df_ant_ind = df_ant_all[df_ant_all["underlying_asset"].notna()] if has_ua else df_ant_all
        vol_por_dia = df_ant_ind.groupby("fecha")["traded_contracts_day"].sum()
        media_vol = vol_por_dia.mean()
        if media_vol > 0:
            pct = (total_vol_hoy - media_vol) / media_vol * 100
            media_str = f"{media_vol:,.0f} ({pct:+.1f}% vs media {len(fechas_anteriores)}d)"
        else:
            media_str = "n/d"
    else:
        media_str = "primera sesión en histórico"

    header = (
        f"SESIÓN={fecha.isoformat()} | HISTÓRICO={dias_historia} sesiones\n"
        f"VOLUMEN_HOY={total_vol_hoy:,} | MEDIA_ANT={media_str}\n"
        f"OI_TOTAL={total_oi_hoy:,} | ANOMALÍAS={len(anomalias)}"
    )

    # ---- SELECCIÓN INTELIGENTE DEL DÍA ACTUAL ----
    mask_total = df_hoy["es_total"] == True if has_total else pd.Series(False, index=df_hoy.index)
    df_totales = df_hoy[mask_total]
    df_ind_hoy = df_hoy[~mask_total]

    top_vol_idx = set(df_ind_hoy.nlargest(TOP_VOL, "traded_contracts_day").index)
    top_oi_idx = set(df_ind_hoy.nlargest(TOP_OI, "open_interest").index)

    if "variacion_dia_pct" in df_ind_hoy.columns:
        var_abs = df_ind_hoy["variacion_dia_pct"].abs().replace([np.inf, -np.inf], np.nan)
        top_var_idx = set(var_abs.nlargest(TOP_VAR).index)
    else:
        top_var_idx = set()

    if anomalias and has_ua:
        anom_keys = {(a.get("contract_group"), a.get("underlying_asset")) for a in anomalias}
        mask_anom = df_ind_hoy.apply(
            lambda r: (r["contract_group"], r.get("underlying_asset")) in anom_keys, axis=1
        )
        top_anom_idx = set(df_ind_hoy[mask_anom].index)
    else:
        top_anom_idx = set()

    idx_sel = top_vol_idx | top_oi_idx | top_var_idx | top_anom_idx
    df_sel = df_ind_hoy.loc[list(idx_sel)] if idx_sel else df_ind_hoy

    df_dia = pd.concat([df_totales, df_sel]).drop_duplicates()
    sort_keys = ["es_total", "traded_contracts_day"] if has_total else ["traded_contracts_day"]
    df_dia = df_dia.sort_values(sort_keys, ascending=[False, False] if has_total else [False])

    subyacentes_sel = set(df_sel["underlying_asset"].dropna().unique()) if has_ua else set()

    # ---- CSV DATOS DEL DÍA ----
    cols_dia = [c for c in [
        "contract_group", "underlying_asset", "traded_contracts_day",
        "open_interest", "variacion_dia_pct", "media_movil_5d",
        "z_score_volumen", "es_total",
    ] if c in df_dia.columns]

    lineas_dia = ["## DATOS_DÍA (CSV)", ",".join(cols_dia)]
    for _, r in df_dia.iterrows():
        lineas_dia.append(_fila_a_csv(r, cols_dia))

    # ---- CONTEXTO HISTÓRICO: AGREGADOS + SERIES ----
    lineas_hist: list[str] = []
    lineas_series: list[str] = []

    if fechas_anteriores:
        df_ant = df[df["fecha"].isin(fechas_anteriores)]

        # Agregados por grupo
        if has_total and "es_total" in df_ant.columns:
            df_ag = df_ant[df_ant["es_total"] == True][
                ["fecha", "contract_group", "traded_contracts_day", "open_interest"]
            ]
        else:
            df_ag = (
                df_ant.groupby(["fecha", "contract_group"])[["traded_contracts_day", "open_interest"]]
                .sum()
                .reset_index()
            )

        if not df_ag.empty:
            lineas_hist = ["## HIST_AGREGADOS (CSV)", "fecha,contract_group,vol_dia,OI"]
            for _, r in df_ag.sort_values(["fecha", "contract_group"]).iterrows():
                lineas_hist.append(
                    f"{r['fecha']},{r['contract_group']},{int(r['traded_contracts_day'])},{int(r['open_interest'])}"
                )

        # Series temporales de subyacentes seleccionados hoy
        if subyacentes_sel and has_ua:
            df_ser = df_ant[df_ant["underlying_asset"].isin(subyacentes_sel)]
            if not df_ser.empty:
                cols_ser = ["fecha", "underlying_asset", "traded_contracts_day", "open_interest"]
                if "variacion_dia_pct" in df_ser.columns:
                    cols_ser.append("variacion_dia_pct")
                lineas_series = ["## HIST_SUBYACENTES (CSV)", ",".join(cols_ser)]
                for _, r in df_ser[cols_ser].sort_values(["underlying_asset", "fecha"]).iterrows():
                    lineas_series.append(_fila_a_csv(r, cols_ser))

    # ---- ANOMALÍAS ----
    if anomalias:
        lineas_anom = [f"## ANOMALÍAS ({len(anomalias)})"]
        for a in anomalias:
            lineas_anom.append(
                f"[{a['tipo_anomalia']}] {a.get('contract_group','')} / "
                f"{a.get('underlying_asset','n/a')}: {a.get('contexto','')}"
            )
    else:
        lineas_anom = ["## ANOMALÍAS", "Ninguna anomalía detectada."]

    # ---- ENSAMBLADO ----
    partes = ["## CABECERA\n" + header, "\n".join(lineas_dia)]
    if lineas_hist:
        partes.append("\n".join(lineas_hist))
    if lineas_series:
        partes.append("\n".join(lineas_series))
    partes.append("\n".join(lineas_anom))

    return "\n\n".join(partes)


def analizar_dia(
    fecha: date,
    ruta_historico: Path,
    ruta_anomalias: Path,
    modelo: str = MODELO_DEFAULT,
    max_tokens: int = 2000,
) -> AnalisisResultado:
    """Pipeline completo: carga datos, construye contexto, llama a Claude, devuelve resultado.

    Args:
        fecha: Fecha de la sesión a analizar.
        ruta_historico: Ruta al CSV histórico (data/meff_historico.csv).
        ruta_anomalias: Ruta al JSON de anomalías (data/anomalias/YYYY-MM-DD.json).
        modelo: ID del modelo Claude a usar.
        max_tokens: Límite de tokens en la respuesta de Claude.

    Returns:
        AnalisisResultado con el resumen generado o mensaje de error.
    """
    import anthropic
    from dotenv import load_dotenv
    from core.procesador import calcular_metricas_derivadas

    load_dotenv(DIRECTORIO_PROYECTO / ".env")
    ruta_prompt = DIRECTORIO_PROYECTO / "fuentes" / "meff" / "prompt.md"

    try:
        prompt_sistema = cargar_prompt(ruta_prompt)
    except FileNotFoundError as exc:
        return AnalisisResultado(
            exito=False, fecha=fecha, resumen_markdown=None, resumen_json=None,
            tokens_input=0, tokens_output=0, coste_estimado_usd=0.0,
            mensaje=f"Prompt no encontrado: {exc}",
        )

    if not ruta_historico.exists():
        return AnalisisResultado(
            exito=False, fecha=fecha, resumen_markdown=None, resumen_json=None,
            tokens_input=0, tokens_output=0, coste_estimado_usd=0.0,
            mensaje=f"Histórico no encontrado: {ruta_historico}",
        )

    df_historico = pd.read_csv(ruta_historico, encoding="utf-8")
    df_historico["fecha"] = pd.to_datetime(df_historico["fecha"]).dt.date
    df_metricas = calcular_metricas_derivadas(df_historico)

    anomalias: list[dict] = []
    if ruta_anomalias.exists():
        with ruta_anomalias.open(encoding="utf-8") as f:
            anomalias = json.load(f).get("anomalias", [])

    contexto = construir_contexto_meff(df_historico, df_metricas, anomalias, fecha)

    # Telemetría: tamaño del contexto antes de enviarlo
    chars_contexto = len(contexto)
    tokens_ctx_estimados = chars_contexto // 4
    logger.info(
        "Contexto construido: %d caracteres (~%d tokens estimados de entrada)",
        chars_contexto,
        tokens_ctx_estimados,
    )

    try:
        client = anthropic.Anthropic()
        respuesta = client.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            system=prompt_sistema,
            messages=[{"role": "user", "content": contexto}],
        )
    except Exception as exc:
        logger.error("Error llamando a Claude API: %s", exc)
        return AnalisisResultado(
            exito=False, fecha=fecha, resumen_markdown=None, resumen_json=None,
            tokens_input=0, tokens_output=0, coste_estimado_usd=0.0,
            mensaje=f"Error API: {exc}",
        )

    tokens_input = respuesta.usage.input_tokens
    tokens_output = respuesta.usage.output_tokens
    coste = (tokens_input * PRECIO_INPUT_POR_MTOKEN + tokens_output * PRECIO_OUTPUT_POR_MTOKEN) / 1_000_000
    texto = respuesta.content[0].text

    logger.info(
        "Claude respondió: %d tokens entrada, %d tokens salida, coste estimado $%.4f USD "
        "(contexto estimado: ~%d tokens, overhead prompt+sistema: ~%d tokens)",
        tokens_input,
        tokens_output,
        coste,
        tokens_ctx_estimados,
        tokens_input - tokens_ctx_estimados,
    )

    resumen_json = {
        "fecha": fecha.isoformat(),
        "modelo": modelo,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "coste_estimado_usd": round(coste, 6),
        "tokens_contexto_estimados": tokens_ctx_estimados,
        "chars_contexto": chars_contexto,
        "resumen": texto,
    }

    return AnalisisResultado(
        exito=True,
        fecha=fecha,
        resumen_markdown=texto,
        resumen_json=resumen_json,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        coste_estimado_usd=coste,
        mensaje="Análisis completado con éxito.",
    )


def guardar_resumen(resultado: AnalisisResultado, directorio: Path) -> tuple[Path, Path]:
    """Guarda el resumen en Markdown y JSON.

    Args:
        resultado: AnalisisResultado con el contenido a guardar.
        directorio: Directorio destino (ej: resumenes/meff/).

    Returns:
        Tupla (ruta_md, ruta_json).
    """
    directorio.mkdir(parents=True, exist_ok=True)
    nombre = resultado.fecha.isoformat()

    ruta_md = directorio / f"{nombre}.md"
    ruta_json = directorio / f"{nombre}.json"

    ruta_md.write_text(resultado.resumen_markdown or "", encoding="utf-8")
    with ruta_json.open("w", encoding="utf-8") as f:
        json.dump(resultado.resumen_json, f, ensure_ascii=False, indent=2)

    logger.info("Resumen guardado: %s y %s", ruta_md.name, ruta_json.name)
    return ruta_md, ruta_json
