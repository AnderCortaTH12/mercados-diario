# Prompt MEFF — pendiente de diseñar en Fase 4

---

## Estructura objetivo del prompt (borrador)

El prompt final debe instruir a Claude para generar un informe ejecutivo
de una página, en el tono de una nota de mercados de Goldman Sachs o Morgan Stanley.
Las secciones previstas son:

### 1. Titular ejecutivo
Una frase de impacto que capture el mensaje clave de la sesión.
Ej: "El IBEX registra máximos de open interest en opciones put a 3 meses
mientras el volumen de futuros cae un 18% respecto a la media."

### 2. Movimientos destacados de volumen
- Top 5 subyacentes por volumen negociado en la sesión.
- Comparación con la media de las últimas 4 semanas (si hay histórico).
- Identificación de outliers o anomalías relevantes.

### 3. Lectura del Open Interest
- Qué indica el nivel actual de OI sobre el posicionamiento del mercado.
- Concentración por vencimiento: ¿dónde está el grueso del riesgo abierto?
- Ratio call/put si los datos lo permiten (señal de sentimiento).

### 4. Contexto de mercado
- Interpretación en clave macro: ¿qué mensaje envía el posicionamiento
  en derivados sobre las expectativas del mercado?
- Mención a eventos próximos relevantes (vencimientos, macro calendar)
  si se pueden inferir de los datos de vencimiento.

### 5. What to watch
- 2-3 indicadores o umbrales concretos a vigilar en las próximas sesiones.
- Redactado en tono de recomendación operativa, no de predicción.

---

*Este archivo se completará en Fase 4 del proyecto.*
