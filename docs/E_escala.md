# PARTE VIII — Sesión E · Escala

## SESIÓN E — Escala
**Modelo sugerido:** Opus, pensamiento extendido alto.
**Ejecutar antes de cargar el primer caserón completo.**

### E.1 — El problema

El canario clasificó 1.743 puntos contra 70.842 caras en 0,19 s. Escalando: 262.500 puntos contra las 92.918 caras de `Bht.dxf` da del orden de **37 segundos por malla**. Con ~8 mallas por caserón (5 litologías + 3 fallas), cerca de **5 minutos por caserón** y **20 minutos** para los cuatro.

Tolerable **una vez y en disco**. Inaceptable si se recalcula en cada interacción de la interfaz.

### E.2 — Clasificación cacheada

- La clasificación geométrica se computa **una sola vez** por combinación (caserón, conjunto de mallas, versión del registro de vocabulario).
- Resultado persistido en disco, en formato columnar (Parquet o similar).
- Clave de caché que incluya un hash del registro de vocabulario: si cambia una asignación de alias, el caché se invalida.
- **Ningún callback de Dash puede disparar una reclasificación completa.** Si el caché falta, se pide al usuario que lo genere explícitamente, con barra de progreso.

### E.3 — Parseo por bloques

El parser de XML debe procesar por bloques y liberar memoria. Con ~150 pozos por caserón, cargar todo en memoria simultáneamente no es viable en Colab.

### E.4 — Submuestreo para visualización

Ningún gráfico debe recibir 262.500 puntos. Submuestreo para la **vista**, con el conteo real siempre declarado en el gráfico ("mostrando 5.000 de 262.500"). Los cálculos usan la población completa; solo el dibujo se submuestrea.

### E.5 — Perfilado obligatorio

Antes de dar por buena esta sesión, medir con datos reales: tiempo de parseo por caserón, tiempo de clasificación por malla, memoria pico, tamaño del caché. Reportar la tabla. Si la extrapolación de 37 s por malla resulta optimista, es mejor saberlo ahora.

---

---


