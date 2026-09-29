# PARTE IX — Sesión C · Concordancia

## SESIÓN C — Concordancia
**Modelo sugerido:** Opus, pensamiento extendido alto.
**Requiere:** P2 (sondajes) y Sesión E completadas, más al menos dos caserones cargados.

### C.0 — Encuadre

Esto es **análisis de concordancia, no validación**. La malla de Leapfrog **no es verdad terreno**: es una interpolación construida a partir de los sondajes, casi exacta junto al sondaje porque está restringida ahí, e hipótesis progresivamente más débil al alejarse.

Un desacuerdo entre MWD y malla **no es un error del MWD** hasta que se demuestre cuál de los dos falla.

Terminología obligatoria en interfaz, exportaciones y memoria: **"modelo geológico informado por MWD"**. Nunca "corregido", nunca "exacto".

### C.1 — Guardia de circularidad

**Bloqueante.** Si el modelo se entrena con etiquetas derivadas de la malla, comparar sus predicciones contra esa misma malla solo demuestra memorización.

El sistema debe **rechazar** todo reporte de concordancia que compare predicciones contra la misma malla que produjo las etiquetas de entrenamiento, e indicar por qué.

Comparaciones admitidas:

1. **Contra registros de sondaje** — fuente independiente del entrenamiento.
2. **Contra la malla del caserón excluido** — el modelo nunca vio la malla de 1541.

### C.2 — Dos niveles de contraste

**Nivel 1 — donde sondaje y MWD están colocalizados.** Único lugar con algo próximo a verdad terreno. Comparar la predicción MWD contra el logueo de testigo directamente. Extensión limitada, valor probatorio alto.

**Nivel 2 — donde solo existe la malla.** Se reporta concordancia y se analiza la estructura espacial del desacuerdo. **Nunca se llama "error" al desacuerdo.**

### C.3 — El diagnóstico principal

**Concordancia en función de la distancia al sondaje más cercano.** Graficar y reportar la pendiente.

| resultado | interpretación |
|---|---|
| Alta cerca, **decae** al alejarse | La malla se degrada lejos del dato y el MWD aporta información donde la interpolación ya no la tiene. **Mejor resultado posible**: valida el MWD y cuantifica el alcance útil de la malla. |
| Plana con la distancia | La malla es tan buena lejos como cerca; el MWD no agrega nada. |
| **Baja cerca** de los sondajes | El problema es del modelo: ahí la malla está anclada al dato duro y no puede estar equivocada. |

### C.4 — Estructura espacial del desacuerdo

Clasificar cada punto discordante por su **distancia al borde de malla más cercano**:

- A uno o dos metros de un borde → precisión de interpolación, esperable.
- En el interior macizo de un cuerpo → problema real, hay que investigarlo.

Reportar el histograma. La distinción separa "la malla está corrida" de "el modelo está mal".

### C.5 — Desfase de contactos

Para cada contacto que predice la malla, medir el desfase δ hasta la firma detectada por el MWD.

- δ con **sesgo sistemático** → la malla está desplazada, y δ cuantifica cuánto.
- δ **simétrico con dispersión** → ruido de interpolación.

Ese δ es el margen operacional de la función de anticipación: recomendar bajar PP N metros antes del contacto previsto. Reportar media, mediana, desviación y sesgo.

### C.6 — Matriz de confusión

Entre litología predicha por MWD y litología de la fuente de contraste, por unidad. Reportar concordancia global, por unidad, y los pares que más se confunden entre sí.

Cruzar con B.7: las unidades cuyas bandas de UCS se traslapan deberían ser las que más se confunden. Si se confunden unidades de bandas bien separadas, hay algo más ocurriendo.

### C.7 — Salidas

- Reporte exportable con todos los gráficos y tablas anteriores
- Tabla de concordancia por caserón y por unidad
- Listado de zonas de desacuerdo interior, con coordenadas, para revisión de geología

---

---


