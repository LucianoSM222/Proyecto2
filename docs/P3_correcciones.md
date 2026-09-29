# PARTE VII — P3 · Correcciones de uso real

## P3 — CORRECCIONES DE USO REAL
#### Defectos detectados operando la herramienta
**Modelo sugerido:** Sonnet estándar.

Cada tarea es independiente. Se pueden abordar en cualquier orden.

### 3.1 — Guardia contra entrenamiento degenerado

Si el conjunto de entrenamiento tiene una sola etiqueta distinta, o menos de un mínimo configurable de muestras por clase, el entrenamiento **no debe ejecutarse**. Un R² de 1,0 es síntoma de degeneración, no de éxito.

### 3.2 — Reporte de composición del entrenamiento

Antes de entrenar, mostrar de dónde salen los datos: total de puntos disponibles, cuántos sobreviven cada filtro y por qué. Un entrenamiento con N=1.260 sobre 12.000 puntos disponibles no puede aparecer sin explicación.

Enumerar todos los filtros aplicados, incluyendo el **corte de emboquillado**, que hoy no figura en la lista (defecto 3.8).

### 3.3 — Exportaciones distinguibles

Existen unas seis exportaciones con nombres indistinguibles y sin confirmación. Dar a cada una un nombre descriptivo que incluya sitio, caserón y fecha, y un diálogo de confirmación que muestre qué se va a exportar y cuántos registros.

### 3.4 — Renombrar "UCS confiable"

El nombre es engañoso: la variable arrastra el último valor estable en los tramos donde DI supera el umbral. Renombrar a **"UCS matriz (sin discontinuidades)"** en interfaz, exportaciones y comentarios.

### 3.5 — Selector de variable en el perfil por pozo

El perfil está fijo en DI. Agregar un selector que permita graficar cualquier variable calculada o cruda a lo largo del pozo.

### 3.6 — Histograma de SE recortado en la vista

Los valores extremos de SE (ROP tendiendo a cero) aplastan el histograma. Recortar **la vista** a los percentiles 1 y 99, sin borrar ni filtrar datos, e indicarlo en el gráfico.

### 3.7 — Pesos del DI configurables

Exponer los pesos (PP=0,35 · DP=0,25 · FP=0,20 · RP=0,20) y el umbral (1,5) desde la interfaz, con los valores de Fernández et al. 2023 como predeterminados y un botón de restauración. Cualquier cambio debe quedar registrado en las exportaciones, porque altera todo aguas abajo.

### 3.8 — Emboquillado en la lista de filtros

Ver 3.2. El corte de emboquillado se aplica pero no se declara.

### 3.9 — Estructura del reporte de justificación de variables

Construir el **armazón** del reporte, dejando los resultados para cuando existan datos:

- matriz de correlación entre predictores, con detección de multicolinealidad
- ante colinealidad alta: **reportar y sugerir cuál quitar, manteniendo ambas por defecto**
- importancia de variables del modelo entrenado
- comparación de **cinco modelos**: Lineal, KNN, Random Forest, HistGradientBoosting y MLP como control
- **dos modos de evaluación: con y sin el proxy SE**, para comparar cuál rinde mejor
- ablación con y sin cota, contrastando desempeño dentro del caserón contra LOCO-CV, como prueba de memorización espacial

---

---


