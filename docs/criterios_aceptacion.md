# PARTE X — Criterios de aceptación consolidados

### Criterios de aceptación

**Adenda B**
- [ ] Bht registrado con `ucs_central` 128,1, banda 100–145, dispersión 64,5–296,9, CV 0,57, mi 14,77, calidad 1
- [ ] Esquema ampliado con `ucs_central`, `dispersion_min`, `dispersion_max`, `ucs_cv`
- [ ] La trampa del promedio 198,19 y la naturaleza de la hoja `RocData` documentadas
- [ ] Distinción banda de confianza / dispersión explícita en código y documentación
- [ ] Advertencia de variabilidad con `ucs_cv > 0,35`
- [ ] Matriz de traslape recalculada, reportada con ambos criterios
- [ ] Parser usa 7 campos y **reporta una vez** los excedentes
- [ ] Alteraciones registradas como dimensión opcional, no obligatoria

**Sesión E**
- [ ] Clasificación cacheada en disco, con hash del registro en la clave
- [ ] Ningún callback dispara reclasificación completa
- [ ] Parseo por bloques
- [ ] Gráficos submuestreados con conteo real declarado
- [ ] Tabla de perfilado con datos reales

**Sesión C**
- [ ] La guardia de circularidad **rechaza** la comparación inválida
- [ ] Gráfico de concordancia contra distancia al sondaje, con pendiente reportada
- [ ] Histograma de desacuerdo por distancia al borde de malla
- [ ] Distribución de δ con media, mediana, desviación y sesgo
- [ ] Matriz de confusión cruzada con el traslape de bandas
- [ ] En ninguna salida aparece "corregido" ni "exacto"

---


