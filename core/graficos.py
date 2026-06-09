"""
Módulo de generación de gráficos interactivos con Plotly para los resúmenes diarios.

Genera HTML inline (embebible en Markdown) a partir del histórico de datos del MEFF.
Claude decide qué gráficos generar mediante especificaciones JSON en su respuesta;
este módulo ejecuta esas especificaciones.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

logger = logging.getLogger(__name__)

# Paleta consultora
COLOR_ACENTO = "#1D4ED8"
COLOR_NEUTRO = "#CBD5E1"
COLOR_TEXTO = "#0F172A"
COLOR_MUTED = "#64748B"
COLOR_POSITIVO = "#10B981"
COLOR_NEGATIVO = "#EF4444"

# Delimitadores del bloque de especificaciones en la respuesta de Claude
_DELIM_INICIO = "===GRAFICOS==="
_DELIM_FIN = "===FIN GRAFICOS==="

# Posición de inserción en el markdown para cada tipo de gráfico
_INSERCION_SECCION: dict[str, tuple[str, str]] = {
    "evolucion_volumen": ("RESUMEN DEL MERCADO", "after"),
    "top_movers_oi": ("LECTURA DEL OPEN INTEREST", "after"),
    "distribucion_categorias": ("WHAT TO WATCH", "before"),
}


@dataclass
class GraficoSpec:
    """Especificación de un gráfico decidido por Claude."""

    tipo: str
    titulo: str
    parametros: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layout base
# ---------------------------------------------------------------------------

def _layout_base(titulo: str, horizontal: bool = False) -> go.Layout:
    """Devuelve el layout común a todos los gráficos."""
    xaxis = dict(showgrid=horizontal, gridcolor="rgba(0,0,0,0.04)",
                 showline=False, color=COLOR_MUTED, zeroline=False)
    yaxis = dict(showgrid=not horizontal, gridcolor="rgba(0,0,0,0.04)",
                 showline=False, color=COLOR_MUTED, zeroline=False)
    return go.Layout(
        template="plotly_white",
        font=dict(family="Inter, sans-serif", size=13, color=COLOR_TEXTO),
        title=dict(text=titulo, font=dict(size=15, color=COLOR_TEXTO), x=0, xanchor="left"),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=55, b=40),
        height=380,
        xaxis=xaxis,
        yaxis=yaxis,
        hoverlabel=dict(bgcolor="white", font_size=12, font_family="Inter, sans-serif"),
        showlegend=False,
    )


def _a_img(fig: go.Figure, titulo: str) -> str:
    """Convierte una figura Plotly en PNG base64 embebible en Markdown.

    Usa kaleido para renderizar a doble resolución (scale=2). El resultado
    es sintaxis nativa Markdown ![]() compatible con cualquier renderer
    (Astro, GitHub, VS Code) sin necesidad de allowDangerousHtml ni scripts.
    """
    img_bytes = fig.to_image(format="png", width=900, height=380, scale=2)
    img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    return f"![{titulo}](data:image/png;base64,{img_b64})"


# ---------------------------------------------------------------------------
# Generadores de gráficos
# ---------------------------------------------------------------------------

def generar_top_movers_oi(df: pd.DataFrame, fecha: date, titulo: str, top_n: int = 5) -> str:
    """Barras horizontales con los N mayores movimientos de Open Interest del día.

    Args:
        df: DataFrame con métricas derivadas (requiere variacion_dia_pct).
        fecha: Fecha de la sesión objetivo.
        titulo: Título del gráfico (la conclusión analítica).
        top_n: Número de subyacentes a mostrar.

    Returns:
        HTML inline de Plotly o cadena vacía si no hay datos suficientes.
    """
    if "variacion_dia_pct" not in df.columns:
        logger.warning("top_movers_oi: columna variacion_dia_pct no disponible")
        return ""

    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    mask = (df["fecha"] == fecha)
    if "underlying_asset" in df.columns:
        mask &= df["underlying_asset"].notna() & (df["underlying_asset"] != "")
    if "es_total" in df.columns:
        mask &= df["es_total"] != True

    df_hoy = df[mask].copy()
    df_hoy = df_hoy.dropna(subset=["variacion_dia_pct"])
    df_hoy = df_hoy[df_hoy["variacion_dia_pct"].abs() > 0]

    if df_hoy.empty:
        logger.warning("top_movers_oi: no hay datos de variacion_dia_pct para %s", fecha)
        return ""

    df_top = df_hoy.reindex(df_hoy["variacion_dia_pct"].abs().nlargest(top_n).index)
    df_top = df_top.sort_values("variacion_dia_pct")

    etiquetas = df_top["underlying_asset"].astype(str).tolist()
    valores = df_top["variacion_dia_pct"].tolist()
    colores = [COLOR_POSITIVO if v >= 0 else COLOR_NEGATIVO for v in valores]
    textos = [f"{v:+.1f}%" for v in valores]

    fig = go.Figure(
        data=[go.Bar(
            x=valores,
            y=etiquetas,
            orientation="h",
            marker_color=colores,
            text=textos,
            textposition="outside",
            hovertemplate="<b>%{y}</b><br>Var. OI: %{x:+.2f}%<extra></extra>",
        )],
        layout=_layout_base(titulo, horizontal=True),
    )
    fig.update_layout(yaxis=dict(categoryorder="array", categoryarray=etiquetas))
    return _a_img(fig, titulo)


def generar_evolucion_volumen(df: pd.DataFrame, fecha: date, titulo: str, dias: int = 10) -> str:
    """Línea temporal del volumen agregado total en los últimos N días.

    El punto del día objetivo se destaca con un marcador en color acento.

    Args:
        df: DataFrame con métricas derivadas.
        fecha: Fecha de la sesión objetivo (punto destacado).
        titulo: Título del gráfico.
        dias: Número de sesiones a mostrar.

    Returns:
        HTML inline de Plotly o cadena vacía si no hay datos suficientes.
    """
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date

    # Usar solo filas individuales para evitar doble cómputo de totales
    mask_ind = pd.Series(True, index=df.index)
    if "es_total" in df.columns:
        mask_ind = df["es_total"] != True
    if "underlying_asset" in df.columns:
        mask_ind &= df["underlying_asset"].notna() & (df["underlying_asset"] != "")

    vol_por_dia = (
        df[mask_ind]
        .groupby("fecha")["traded_contracts_day"]
        .sum()
        .reset_index()
        .sort_values("fecha")
    )

    fechas_disponibles = vol_por_dia[vol_por_dia["fecha"] <= fecha]["fecha"].tolist()
    if len(fechas_disponibles) < 2:
        logger.warning("evolucion_volumen: datos insuficientes para %s", fecha)
        return ""

    ventana = fechas_disponibles[-dias:]
    df_ventana = vol_por_dia[vol_por_dia["fecha"].isin(ventana)].copy()

    fechas_x = df_ventana["fecha"].tolist()
    vols_y = df_ventana["traded_contracts_day"].tolist()

    # Separar el punto de hoy
    colores_marcador = [COLOR_ACENTO if f == fecha else COLOR_NEUTRO for f in fechas_x]
    tamanos_marcador = [12 if f == fecha else 6 for f in fechas_x]

    fig = go.Figure(
        data=[go.Scatter(
            x=[str(f) for f in fechas_x],
            y=vols_y,
            mode="lines+markers",
            line=dict(color=COLOR_NEUTRO, width=2),
            marker=dict(color=colores_marcador, size=tamanos_marcador, line=dict(width=0)),
            hovertemplate="<b>%{x}</b><br>Volumen: %{y:,.0f} contratos<extra></extra>",
        )],
        layout=_layout_base(titulo, horizontal=False),
    )
    fig.update_layout(xaxis=dict(showgrid=False, tickangle=-30))
    return _a_img(fig, titulo)


def generar_distribucion_categorias(df: pd.DataFrame, fecha: date, titulo: str) -> str:
    """Barras horizontales del volumen del día por familia de producto (contract_group).

    Args:
        df: DataFrame con métricas derivadas.
        fecha: Fecha de la sesión objetivo.
        titulo: Título del gráfico.

    Returns:
        HTML inline de Plotly o cadena vacía si no hay datos suficientes.
    """
    df = df.copy()
    df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
    df_hoy = df[df["fecha"] == fecha]

    # Usar filas de totales por grupo si existen; si no, agregar manualmente
    if "es_total" in df_hoy.columns:
        df_cat = df_hoy[df_hoy["es_total"] == True][["contract_group", "traded_contracts_day"]].copy()
    else:
        df_cat = (
            df_hoy.groupby("contract_group")["traded_contracts_day"]
            .sum()
            .reset_index()
        )

    # Filtrar grupos sin actividad
    df_cat = df_cat[df_cat["traded_contracts_day"] > 0].sort_values("traded_contracts_day")

    if df_cat.empty:
        logger.warning("distribucion_categorias: no hay datos para %s", fecha)
        return ""

    grupos = df_cat["contract_group"].astype(str).tolist()
    vols = df_cat["traded_contracts_day"].tolist()
    vol_max = max(vols)
    colores = [COLOR_ACENTO if v == vol_max else COLOR_NEUTRO for v in vols]

    fig = go.Figure(
        data=[go.Bar(
            x=vols,
            y=grupos,
            orientation="h",
            marker_color=colores,
            hovertemplate="<b>%{y}</b><br>Volumen: %{x:,.0f} contratos<extra></extra>",
        )],
        layout=_layout_base(titulo, horizontal=True),
    )
    return _a_img(fig, titulo)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_GENERADORES = {
    "top_movers_oi": generar_top_movers_oi,
    "evolucion_volumen": generar_evolucion_volumen,
    "distribucion_categorias": generar_distribucion_categorias,
}


def generar_graficos_segun_spec(
    specs: list[GraficoSpec],
    df: pd.DataFrame,
    fecha: date,
) -> dict[str, str]:
    """Genera todos los gráficos indicados en specs.

    Args:
        specs: Lista de GraficoSpec decidida por Claude.
        df: DataFrame con métricas derivadas (ruta histórico + calcular_metricas_derivadas).
        fecha: Fecha de la sesión a analizar.

    Returns:
        Diccionario {tipo_grafico: html_string}. Tipos sin generador o con error se omiten.
    """
    resultado: dict[str, str] = {}
    for spec in specs:
        generador = _GENERADORES.get(spec.tipo)
        if generador is None:
            logger.warning("Tipo de gráfico desconocido: %s — omitido", spec.tipo)
            continue
        try:
            params = spec.parametros or {}
            html = generador(df, fecha, spec.titulo, **params)
            if html:
                resultado[spec.tipo] = html
        except Exception as exc:
            logger.warning("Error generando gráfico %s: %s — omitido", spec.tipo, exc)
    return resultado


# ---------------------------------------------------------------------------
# Parseo de specs desde respuesta de Claude
# ---------------------------------------------------------------------------

def parsear_specs_graficos(texto: str) -> tuple[list[GraficoSpec], str]:
    """Extrae el bloque ===GRAFICOS=== de la respuesta de Claude y lo parsea.

    Args:
        texto: Respuesta completa de Claude (análisis + bloque de gráficos).

    Returns:
        Tupla (lista de GraficoSpec, texto sin el bloque). Si el bloque no existe
        o el JSON está malformado, devuelve ([], texto_limpio) sin lanzar excepción.
    """
    patron = re.compile(
        r"\s*" + re.escape(_DELIM_INICIO) + r"\s*(.*?)\s*" + re.escape(_DELIM_FIN) + r"\s*",
        re.DOTALL,
    )
    match = patron.search(texto)
    if not match:
        return [], texto

    texto_limpio = patron.sub("", texto).rstrip()
    bloque_json = match.group(1).strip()

    try:
        datos = json.loads(bloque_json)
        specs = [
            GraficoSpec(
                tipo=g["tipo"],
                titulo=g.get("titulo", g["tipo"]),
                parametros=g.get("parametros", {}),
            )
            for g in datos.get("graficos", [])
            if "tipo" in g
        ]
        return specs, texto_limpio
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Bloque ===GRAFICOS=== malformado: %s — sin gráficos", exc)
        return [], texto_limpio


# ---------------------------------------------------------------------------
# Inserción de gráficos en el Markdown final
# ---------------------------------------------------------------------------

def _insertar_html_en_md(md: str, seccion: str, html: str, posicion: str) -> str:
    """Inserta un bloque HTML antes o después de una sección markdown.

    Args:
        md: Texto markdown completo.
        seccion: Nombre de la sección (sin #) a buscar.
        html: HTML a insertar.
        posicion: "after" inserta al final de la sección; "before" inserta antes de ella.

    Returns:
        Markdown con el HTML insertado. Si la sección no se encuentra, el HTML
        se añade al final como fallback.
    """
    lines = md.splitlines()

    sec_idx: Optional[int] = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("#") and seccion in stripped:
            sec_idx = i
            break

    if sec_idx is None:
        return md + "\n\n" + html

    if posicion == "before":
        insert_at = sec_idx
    else:
        # Busca el siguiente encabezado de cualquier nivel
        insert_at = len(lines)
        for i in range(sec_idx + 1, len(lines)):
            if lines[i].strip().startswith("#"):
                insert_at = i
                break

    html_block = ["", html, ""]
    result = lines[:insert_at] + html_block + lines[insert_at:]
    return "\n".join(result)


def insertar_graficos_en_md(md: str, graficos: dict[str, str]) -> str:
    """Inserta todos los gráficos HTML en sus posiciones lógicas del markdown.

    Orden de inserción definido por _INSERCION_SECCION. Tipos no reconocidos
    se añaden al final.
    """
    # Insertar en orden predefinido para coherencia
    orden = list(_INSERCION_SECCION.keys()) + [t for t in graficos if t not in _INSERCION_SECCION]
    for tipo in orden:
        if tipo not in graficos:
            continue
        html = graficos[tipo]
        if tipo in _INSERCION_SECCION:
            seccion, posicion = _INSERCION_SECCION[tipo]
            md = _insertar_html_en_md(md, seccion, html, posicion)
        else:
            md = md + "\n\n" + html
    return md
