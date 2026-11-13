# Cambios para la memoria — semana del 5 al 11 de noviembre de 2026

Este documento reúne todo lo que cambió en la herramienta y en los resultados
durante la semana, y dice qué hay que tocar en la memoria: texto, cifras,
figuras y tablas. La numeración de figuras y tablas es la del cuerpo de la
última versión en PDF (Capítulo 5, Figuras 5.1 a 5.19 y Tablas 5.1 a 5.5).

- **Figuras y tablas de reemplazo:** `figuras/tesis_2026-11-13/reemplazo/`,
  con el número de la memoria en el nombre del archivo.
- **Tablas en Excel:** `figuras/tesis_2026-11-13/reemplazo/tablas_capitulo5.xlsx`.
- **Corrida:** `memoria_final/final/final_calc.py`, 11 de noviembre de 2026,
  sobre los cuatro caserones (928 barrenos, 982.420 registros).

---

## 1. Qué se decidió esta semana

| # | Decisión | Efecto |
|---|---|---|
| 1 | Siglas del XML IREDES en todo: **PR** (velocidad de penetración), **FP** (avance), **FLP** (flujo de barrido) | Reemplazan a ROP, AP y FP = flujo. SE pasa a **PEP** |
| 2 | Vocabulario: **barreno** (no barreno ni barreno) | Texto y figuras |
| 3 | DI en dos clases: **roca continua** (DI ≤ 1) y **roca discontinua** (DI > 1) | Reemplaza a intacta/fracturada y a sana/transición/fracturada. «Roca intacta» queda solo para la UCS de ensayo |
| 4 | **Cambio de barra**: PR = 0 sobre la grilla de 1,756 m del barreno, más los 2 registros siguientes | Reemplaza a la percusión de empate |
| 5 | El filtro de caída relativa de la PP (percusión de empate o regulación automática) **sale** de la limpieza | Desaparecen la Ec. 4.1, la Tabla 5.2 y la Figura 5.2 actuales |
| 6 | **Emboquillado por meseta de PP**, barreno por barreno | Reemplaza al corte fijo de 2 m |
| 7 | **Límites del equipo** para las seis variables | Reemplaza al rango de PP solo |
| 8 | Criterio **equipo / roca**: lo que es del equipo sale antes del DI; lo que puede ser roca se queda en el DI y solo sale del entrenamiento | Cambia qué filtros van antes del DI |
| 9 | La continuidad del registro pasa a filtrarse **antes** del DI | Antes solo afectaba al entrenamiento |
| 10 | La PEP se mantiene como está | Sin cambios, pese a la observación del profesor guía |

---

## 2. Metodología (Capítulo 3)

### 2.1 Sección 3.2.2, Limpieza de datos: se reescribe

El texto listo para la memoria está en `docs/depuracion_registros_mwd.md`. En
resumen, la sección pasa de «dos filtros antes del DI y dos solo de
entrenamiento» a cuatro filtros ordenados por un criterio único:

| Orden | Filtro | Criterio | Serie del DI | Entrenamiento |
|---|---|---|---|---|
| 1 | Cambio de barra | PR = 0 sobre la grilla de 1,756 m del barreno (±6 cm, ≥ 3 uniones), más los 2 registros siguientes | Excluye | Excluye |
| 2 | Emboquillado | Hasta que la PP se mantiene pareja 20 cm sobre el 70% de su nivel de régimen (sin meseta: 2 m) | Excluye | Excluye |
| 3a | Límites del equipo: no perfora | PR = 0, PP < 90 bar, FP < 20 bar, FLP > 10 bar o PR > 10 m/min | Excluye | Excluye |
| 3b | Límites del equipo: respuesta de la roca | PR, RP o DP fuera de su rango | Mantiene | Excluye |
| 4 | Continuidad del registro | Ventana del DI que cruza un salto > 2,95 cm | Excluye | Excluye |

Qué sale del texto actual:

- El párrafo del **filtro de variación interna** y la **Ec. 4.1** (caída
  relativa). Si se quiere conservar, va como antecedente de lo que se probó.
- La frase «entre 90 y **250** [bar]»: el rango es 90 a **230** bar.
- La descripción del emboquillado como «distancia de los primeros metros a
  eliminar»: ahora se determina por la estabilización de la PP en cada barreno.
- La definición de continuidad como «tramos asociados a registros aislados o
  reperforación»: es un salto de más de 2,95 cm entre muestras consecutivas,
  cerca de 1,5 veces el espaciamiento nominal de 2 cm.

Límites del equipo (Tabla nueva, archivo `Tabla_5.2_limites_del_equipo`):

| Variable | Mínimo | Máximo | Unidad |
|---|---:|---:|---|
| PR | 0,1 | 1,5 | m/min |
| PP | 90 | 230 | bar |
| FP | 20 | 150 | bar |
| DP | 25 | 150 | bar |
| RP | 30 | 80 | bar |
| FLP | 2 | 10 | bar |

Los topes de PP y RP se respaldan con los registros: la meseta más alta que
se mantiene al menos 5 m es de 225,1 bar en la PP y de 81,0 bar en la RP.

### 2.2 Sección 3.3, Cálculo del DI

- La frase final del primer párrafo queda: «El cálculo se realiza sobre la
  serie filtrada del cambio de barra, del emboquillado, de los registros en
  que el equipo no perfora y de los saltos de continuidad (3.2.2)». Hoy
  menciona la regulación automática de la percusión, que ya no se aplica.
- «En la serie previamente filtrada, el DI varía entre 0 y 11, y el 83% de
  los registros es menor o igual a 1» → **el 81,9%** (704.859 de 860.821).
- Ventana: el código usa una ventana centrada de semiancho 7, es decir
  **15 muestras (≈ 30 cm)**. Si se mantiene «14 muestras», conviene aclararlo.
- Definición de β en la Ec. 3.4: los pesos suman 1 y se eligen maximizando la
  correlación de Spearman contra el RQD (no con el índice de similitud S_T de
  Fernández), como ya dice el párrafo siguiente.

---

## 3. Resultados (Capítulo 5), sección por sección

### 5.1 Procesamiento de datos

**Tabla 5.1** → `Tabla_5.1_resumen_filtros`.

| Etapa | Filtro | Excluidos | Restantes |
|---|---|---:|---:|
| Carga | Registros MWD de 928 barrenos | — | 982.420 |
| Antes del DI | Emboquillado (meseta de PP) | 75.104 | 907.316 |
| | Cambio de barra (detención y 2 registros siguientes) | 31.255 | 876.061 |
| | Equipo sin perforar | 14.114 | 861.947 |
| | Continuidad del registro | 1.123 | 860.824 |
| | Registros sin DI calculable | 3 | **860.821** (serie filtrada) |
| Solo entrenamiento | PR, RP, DP o PP fuera del rango del equipo | 24.939 | **835.885** (entrenables) |
| Discontinuidad | DI > 1 | 145.465 | **690.420** (entrenamiento) |

Cada registro se cuenta en un solo filtro, en el orden de la tabla. Los 3 registros sin DI calculable siguen siendo entrenables (el filtro de
discontinuidad solo excluye DI > 1), por eso los entrenables son 835.885.

Cifras del texto que cambian:

| En la memoria | Nuevo |
|---|---|
| Emboquillado 86.785 registros | 75.104 (corte mediano 1,50 m; 11 barrenos con el corte de respaldo de 2 m) |
| Percusión de empate 8.911 | Se elimina. Cambio de barra: 11.070 detenciones + 20.185 de margen = 31.255 |
| 65 registros sin DI calculable | 3 |
| Serie filtrada 886.659 | 860.821 |
| Rango de PP y continuidad: 17.200 | Límites del equipo (roca): 24.939 |
| Entrenables 869.459 | 835.885 |
| Total excluido 112.961 | 146.535 |
| Roca intacta 723.601 | Roca continua 690.420 |

Detalle para el texto (`Tabla_5.1b_NUEVA_detalle_limites_equipo_roca`):

- Equipo sin perforar (14.114): PR = 0 fuera de la grilla de barra 5.997,
  PP < 90 bar 5.246, FLP > 10 bar 2.642, FP < 20 bar 164, PR > 10 m/min 65.
- Solo entrenamiento (24.939): PR > 1,5 m/min 23.217, RP < 30 bar 1.090,
  RP > 80 bar 518, PR < 0,1 m/min 106, DP > 150 bar 69, PP > 230 bar 4,
  DP < 25 bar 2.

### 5.2 Índice de Discontinuidad

**Figura 5.1** → `Figura_5.1_correlacion_pearson` (misma matriz de 7
variables, con las siglas nuevas, sobre los 860.824 registros de la serie
filtrada).

- El par de presiones más correlacionado sigue siendo **FP–DP**, ahora con
  r = **0,52** (antes 0,61). El argumento para dejar fuera el avance se
  mantiene.
- Le siguen PP–FP (0,41), FP–FLP (0,30) y PP–DP (0,30). Ninguno supera la
  tolerancia de 0,6. El «r = 0,55» entre percusión y amortiguación del texto
  pasa a 0,30.
- RP–FLP: −0,37. PR–PEP: −0,72.

**Tabla 5.2 y Figura 5.2 (percusión de empate): se reemplazan.** El bloque de
texto entre «Un segundo criterio previo a calibrar…» y «…se aplica antes del
cálculo del DI» se sustituye por la validación del cambio de barra:

- `Tabla_5.2b_NUEVA_validacion_largo_barra`: la distancia más frecuente
  entre detenciones de un mismo barreno es 1,755 m (39.938 parejas), con un
  segundo pico en 3,510 m. La grilla de 1,756 m alinea 10.124 de 14.229
  detenciones; ubicadas al azar se alinean 2.470. El largo por barreno es
  1,7549 m, con 1,2 mm de desviación estándar entre 795 barrenos.
- `Figura_5.2b_NUEVA_periodicidad_cambio_barra`: histograma de distancias y
  barrido del largo entre 1,20 y 2,40 m.
- `Figura_5.2c_NUEVA_transitorio_cambio_barra`: sobre 10.972 cambios de
  barra, antes de la detención no hay transitorio; al reanudar, la primera
  muestra trae la PR al 62% y la PP al 76% de su nivel, y la segunda la PR
  al 84%. Por eso se excluyen los 2 registros siguientes.
- `Figura_5.2_antes_despues_depuracion`: cambia de barreno, a
  PCS_1059_PR01_P202_H11, donde la periodicidad y el emboquillado se ven
  mejor. Registros excluidos: 72 de emboquillado (corte a 1,55 m, donde la PP
  pasa de unos 130 a 225 bar), 17 de cambio de barra (17 uniones, ninguna
  detención fuera de la grilla), 32 de margen y 5 fuera de rango que solo
  salen del entrenamiento. Quedan 1.376 registros en la serie del DI. La
  versión con PR (`Figura_5.2_OBSERVACION_con_PR`) es solo para observar.

**Tabla 5.3** → `Tabla_5.3_sensibilidad_radio_RQD`.

| Radio [m] | Pares | Sondajes | PP | RP | DP | FLP | ρ ajuste | ρ validación |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 5 | 2 | 0,00 | 0,89 | 0,01 | 0,10 | +0,500 | — |
| 3 | 12 | 4 | 0,20 | 0,43 | 0,05 | 0,31 | +0,273 | +0,714 |
| **5** | **33** | **4** | **0,22** | **0,21** | **0,02** | **0,55** | **+0,261** | **−0,009** |
| 7,5 | 50 | 4 | 0,41 | 0,34 | 0,02 | 0,24 | +0,247 | +0,236 |
| 10 | 62 | 4 | 0,52 | 0,22 | 0,03 | 0,22 | +0,289 | +0,094 |
| 15 | 75 | 4 | 0,54 | 0,23 | 0,04 | 0,19 | +0,337 | +0,261 |
| 25 | 111 | 5 | 0,71 | 0,23 | 0,06 | 0,00 | +0,243 | +0,133 |

Lo que cambia en la lectura de la tabla:

- A 5 m los pesos son PP 0,22 · RP 0,21 · DP 0,02 · FLP 0,55 (antes PP 0,01 ·
  RP 0,39 · DP 0,07 · FLP 0,54). El flujo de barrido sigue con el mayor peso;
  la percusión gana peso y la rotación lo pierde.
- La calibración usa **33 pares** (antes 32).
- La correlación de validación a 5 m es **−0,009** (antes +0,151). La frase
  «crece con el radio desde +0,151 a 5 m hasta +0,287 a 25 m» ya no vale: la
  validación no crece de forma ordenada (+0,71 a 3 m, −0,01 a 5 m, +0,24 a
  7,5 m, +0,13 a 25 m).
- «El flujo de barrido es la señal más persistente, con el mayor peso en
  seis de los siete radios» ya no vale: tiene el mayor peso solo a 5 m. Desde
  7,5 m domina la percusión. La conclusión de que los pesos son inestables se
  refuerza.

**Figura 5.3** → `Figura_5.3_perfil_DI_P20_H12`. Los tramos de RQD del
sondaje DDH13-LP-50 dentro de 5 m son 16 (el texto dice 3); conviene revisar
esa frase contra la figura.

**Figura 5.4** → `Figura_5.4_sensibilidad_ventana_DI`. Sobre los cuatro
caserones:

| Ventana | Zonas discontinuas por 100 m | Registros sobre el umbral |
|---|---:|---:|
| 10 muestras (20 cm) | 39,6 | 16,2% |
| 14 muestras (28 cm) | **36,9** | **18,1%** |
| 20 muestras (40 cm) | 33,5 | 20,3% |

En el texto, «38,9 zonas por cada 100 m y 17,0%» pasa a 36,9 y 18,1%. Las
cuentas del barreno P20_H12 (20, 17 y 17 zonas) hay que leerlas de la leyenda de
la figura nueva.

Párrafo de cierre de 5.2: «sobre los 886.659 registros… 735.674 (83,0%) como
roca intacta y 150.985 (17,0%) como roca discontinua. De los registros de
roca intacta, 12.073…» pasa a: sobre los **860.821** registros de la serie
filtrada, **704.859 (81,9%)** son roca continua y **155.962 (18,1%)** roca
discontinua; de los primeros, **14.439** quedan fuera de los límites del
equipo, por lo que el entrenamiento usa **690.420** registros.

### 5.3 Ordenamiento de la resistencia de la roca

**Figura 5.5** → `Figura_5.5_RMSE_LOOCV_caseron`.

| Aproximación | RMSE antes | RMSE nuevo | ρ antes | ρ nuevo |
|---|---:|---:|---:|---:|
| Línea base | 48,9 | 48,9 | — | — |
| Banda por unidad | 96,5 | 95,4 | +0,024 | +0,027 |
| Relación directa PEP ↔ UCS | 79,5 | 82,7 | +0,022 | +0,021 |
| Random Forest | 50,6 | 50,8 | +0,111 | +0,115 |

La lectura no cambia.

**Figura 5.6** → `Figura_5.6_PEP_vs_UCS`. El ajuste parabólico sobre roca
continua da R² = **0,218** (antes 0,228); la ecuación está en la leyenda de
la figura. La correlación entre la PEP y la UCS referencial pasa de +0,203 a
**+0,192**.

**Figura 5.7** → `Figura_5.7_boxplot_UCS_lab_vs_ML`.

| Litología | UCS referencial | P50 antes | P50 nuevo | n |
|---|---:|---:|---:|---:|
| Lavas superiores (Kpcls) | 60,0 | 133,0 | 132,9 | 49.091 |
| Brecha mixta | 111,5 | 154,6 | 154,4 | 16.004 |
| Brecha hidrotermal (Bht) | 128,1 | 137,6 | 137,0 | 212.765 |
| Lavas inferiores (Kpcli) | 180,0 | 167,3 | 167,5 | 412.447 |

La etiqueta de 180 MPa se usa en **412.520** registros (antes 426.935), el
**59,7%** del entrenamiento.

**Figura 5.8, comparación de algoritmos: es el cambio que más cuidado
requiere.** Esta comparación no usa todos los datos: sortea barrenos completos
hasta un tope de 60.000 registros. Con el conjunto de entrenamiento nuevo el
sorteo es otro (59.820 registros de 77 barrenos) y el R² de prueba sale
**negativo en los cinco algoritmos**:

| Algoritmo | Entrenamiento | Prueba (antes) | Prueba (nuevo) |
|---|---:|---:|---:|
| Lineal | +0,045 | +0,097 | −0,118 |
| KNN | +0,712 | −0,055 | −0,452 |
| Random Forest | +0,422 | +0,161 | **−0,045** |
| HistGradientBoosting | +0,602 | +0,126 | −0,182 |
| MLP (control) | +0,503 | +0,054 | −0,371 |

Para saber cuánto depende del sorteo, se repitió la comparación con seis
sorteos distintos de barrenos (`comparacion_sorteos.py`):

| Algoritmo | Sorteo 1 | 2 | 3 | 4 | 5 | 6 | Media | Desv. est. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Lineal | −0,118 | −0,123 | −0,110 | +0,072 | +0,032 | +0,048 | −0,033 | 0,085 |
| KNN | −0,452 | −0,392 | −0,376 | −0,131 | −0,112 | −0,037 | −0,250 | 0,161 |
| **Random Forest** | −0,045 | −0,054 | −0,046 | +0,112 | +0,096 | +0,177 | **+0,040** | 0,092 |
| HistGradientBoosting | −0,182 | −0,197 | −0,138 | +0,046 | +0,091 | +0,134 | −0,041 | 0,135 |
| MLP (control) | −0,371 | −0,342 | −0,282 | −0,080 | −0,009 | +0,033 | −0,175 | 0,162 |

- **Lo que se sostiene:** el Random Forest es el mejor en los seis sorteos, y
  KNN y la MLP son los que más se sobreajustan.
- **Lo que no se sostiene:** el valor del R² de prueba. Va de −0,05 a +0,18
  según los barrenos sorteados. La frase «el Random Forest obtiene el mayor R² en
  barrenos excluidos (+0,166)» debe pasar a hablar del orden, no del valor.
- **Qué figura usar:** recomiendo
  `Figura_5.8_ALTERNATIVA_comparacion_algoritmos_6_sorteos` (media de los seis
  sorteos con su desviación) junto con `Tabla_5.8_NUEVA_R2_por_sorteo`. La
  versión de un solo sorteo también está en la carpeta.
- El modelo de producción no se ve afectado: se valida con todos los
  registros (Figura 5.9).

**Figura 5.9** → `Figura_5.9_spearman_por_esquema`.

| | Antes | Nuevo |
|---|---:|---:|
| Validación por barreno: R² | +0,290 ± 0,022 | +0,284 ± 0,028 |
| Validación por barreno: RMSE [MPa] | 30,4 | 30,2 |
| Validación por barreno: ρ de Spearman | +0,564 | +0,561 |
| R² de entrenamiento | +0,323 | +0,326 |
| LOOCV-Caserón: R² medio | −2,77 | −2,81 |
| LOOCV-Caserón: ρ de Spearman | +0,111 | +0,115 |

La lectura no cambia. Importancia por permutación: FLP 0,219 · RP 0,131 ·
FP 0,053 · PP 0,049 · PEP 0,049 · PR 0,014 · DP 0,008.

### 5.4 Coherencia geológica

**Figuras 5.10 a 5.13 y Anexo C** → `Figura_5.10` a `Figura_5.13` y
`Anexo_C_*`.

| Conjunto | | Zonas | Precisión | Azar | Diferencia | Recall | Media [m] | Mediana [m] | σ [m] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Cuatro caserones | antes | 4.127 | 50,2% | 46,2% | 4,0 | 92% | −2,13 | −0,57 | 7,31 |
| | nuevo | 3.859 | 48,7% | 46,6% | **2,0** | 88,5% | −2,46 | −0,78 | 7,48 |
| PCC_0042 (calibración) | antes | 1.527 | 36,6% | 31,1% | 5,5 | 96% | −6,49 | −4,24 | 8,62 |
| | nuevo | 1.438 | 35,1% | 31,5% | **3,6** | 92,4% | −6,97 | −4,83 | 8,70 |
| PCC_1541 (prueba) | antes | — | 58,0% | 52,6% | 5,4 | 92,8% | −0,08 | +0,15 | — |
| | nuevo | 1.200 | 57,2% | 53,3% | **3,9** | 91,3% | −0,29 | +0,05 | 5,57 |

- La concordancia sigue sobre el azar en los tres conjuntos, pero la ventaja
  **baja**: de 4,0 a 2,0 puntos en el total, de 5,5 a 3,6 en PCC_0042 y de
  5,4 a 3,9 en PCC_1541.
- La frase «este caserón mantiene prácticamente la misma diferencia sobre el
  azar que el de calibración (5,4 y 5,5 puntos)» pasa a 3,9 y 3,6 puntos. La
  conclusión de que los pesos se transfieren a PCC_1541 se mantiene, con una
  ventaja menor.
- El desfase sistemático de PCC_0042 se mantiene (mediana −4,8 m).
- Barrenos con cruces: 450, 143 y 187, sin cambio.

**Figura 5.14** → `Figura_5.14_perfil_PCS1043_P07_H4`. Revisar los tres
hallazgos numerados contra la figura nueva, porque el emboquillado y el DI
del barreno cambiaron.

### 5.5 Soporte a la tronadura

**Figura 5.15** → `Figura_5.15_seccion_tronadura` (Norte ≈ 6.958.906 m).

**Figura 5.16** → `Figura_5.16_clasificacion_DI_UCS`, ahora con dos clases de
DI.

| | < 125 MPa | 125–150 MPa | 150–175 MPa | ≥ 175 MPa | Total |
|---|---:|---:|---:|---:|---:|
| Roca continua (DI ≤ 1) | 528 (3,5%) | 4.918 (32,3%) | 8.006 (52,5%) | 328 (2,2%) | 13.780 (90,4%) |
| Roca discontinua (DI > 1) | 17 (0,1%) | 612 (4,0%) | 827 (5,4%) | 6 (0,0%) | 1.462 (9,6%) |

Cifras del texto que cambian:

- 14.913 bloques y 233.016 m³ → **15.242 bloques y 238.156 m³**.
- «El 91,5% corresponde a roca sana, el 7,8% a transición y el 0,7% a roca
  fracturada (103 bloques, 1.609 m³)» → **90,4% roca continua y 9,6% roca
  discontinua (1.462 bloques, 22.844 m³)**. El párrafo que describe tres
  clases hay que redactarlo de nuevo con dos.
- «El 97% de los bloques en transición o fracturados tiene UCS entre 125 y
  175 MPa» → el **98,4%** de los bloques de roca discontinua (1.439 de 1.462).
- «Solo el 4,1% queda bajo 125 MPa y el 2,5% sobre 175 MPa» → **3,6%** y
  **2,2%**.

### 5.6 Soporte en la perforación

**Tabla 5.4** → `Tabla_5.4_dominios`. Los grupos pasan de 50 a **63** y su
numeración cambia.

| Grupo | Litología | Estructura | UCS ML media [MPa] | DI medio | Registros |
|---|---|---|---:|---:|---:|
| G2 | Kpcli | — | 165,5 | 0,620 | 395.040 |
| G1 | Bht | — | 138,5 | 0,712 | 192.611 |
| G45 | Kpcls | — | 134,9 | 0,898 | 59.665 |
| G4 | Kpcli | — | 155,0 | 1,256 | 45.050 |
| G12 | Kpcli | — | 137,4 | 0,641 | 35.561 |
| G14 | Bht | FM | 139,7 | 0,701 | 20.249 |
| G3 | Brecha_mixta | — | 153,7 | 0,636 | 17.683 |
| G8 | Bht | — | 169,1 | 0,550 | 14.324 |

En el texto: G2 reúne el **47,3%** de los registros entrenables (395.040
registros en **4.482** tramos; antes 47,0%, 408.718 en 4.385). Bht sin
estructura, **23,0%**; Lavas superiores, **7,1%**.

Correlaciones de la PEP (Anexo D y texto previo a la Figura 5.17): con la PR
ρ = **−0,890** (antes −0,904), con la UCS referencial **+0,192** (antes
+0,203) y con la PP **+0,086** (antes +0,071).

**Figuras 5.17 y 5.18** → `Figura_5.17_PEP_PR_PP_roca_continua` y
`Figura_5.18_PEP_PR_PP_roca_discontinua`. El título de la 5.18 pasa a «roca
discontinua». Los valores citados en el texto (1,07 m/min en Bht, 390–400
bar·min/m en Brecha mixta, etc.) hay que releerlos de las figuras nuevas.

**Tabla 5.5** → `Tabla_5.5_ranking_G2`. El ranking completo cambió. Lo que
se sostiene y lo que no:

- Mínima variación: sigue eligiendo tramos de 5 a 6 registros, cuatro de
  ellos con la PP entre 223 y 225 bar. Se mantiene la advertencia sobre los
  tramos cortos.
- Mínima PEP: ahora los tramos tienen PEP de 190 a 210 bar·min/m con PR de
  1,1 a 1,5 m/min. Ya no aparecen los tramos con PR de 1,8 m/min, que quedan
  fuera por el límite de 1,5 m/min.
- Máxima PR: 1,46 a 1,48 m/min, con PP entre 196 y 222 bar. La frase «los
  criterios de máxima PR y mínima PEP coinciden en dos tramos, con PR cercana
  a 1,8 m/min» pasa a: coinciden en **un** tramo (PCC_0042_PR01_TH_P35_H5,
  PR 1,46 m/min).
- La RP del ranking de máxima PR va de 42 a 66 bar; la frase «presión de
  rotación baja, de 37 a 53 bar» hay que ajustarla.

**Figura 5.19** → `Figura_5.19_PR_vs_presiones`.

| Presión | ρ antes | ρ nuevo |
|---|---:|---:|
| PP | +0,235 | **+0,242** |
| FP (avance) | +0,106 | **+0,104** |
| RP | −0,181 | **−0,194** |
| DP | −0,035 (figura) | **−0,051** |

Sobre **690.420** registros de roca continua de **920** barrenos (el texto dice
718.032 registros de 900 barrenos, y la figura actual 723.603).

---

## 4. Lo que hay que saber antes de pegar

1. **La calibración del DI cambió y valida peor.** Con la serie filtrada
   nueva, los pesos a 5 m son otros y la correlación de validación es −0,009.
   La conclusión de la memoria («calibración preliminar que debe validarse por
   coherencia geológica») se mantiene, pero ya no se puede decir que la
   validación mejora con el radio.
2. **La concordancia con las mallas bajó** de 4–5 puntos sobre el azar a
   2–4 puntos. Sigue siendo positiva en los tres conjuntos.
3. **La comparación de algoritmos depende del sorteo de barrenos** (ver 5.3). El
   orden es estable; el valor no.
4. **El emboquillado por meseta da cortes muy distintos entre barrenos.** De los
   917 barrenos con meseta, 275 cortan antes de 0,5 m y 225 entre 2,0 y 2,5 m;
   35 cortan después de 6 m, con un máximo de 30,3 m. En el barreno de ejemplo
   de la Figura 5.2 el corte es a 0,29 m, aunque la PP sigue oscilando hasta
   cerca de los 4 m. Conviene revisar algunos de estos casos antes de
   defender la regla.
5. **Tres defectos del programa corregidos durante la corrida**, todos con su
   test:
   - Un barreno cuya serie filtrada quedaba más corta que la ventana conservaba
     el DI calculado antes de la limpieza (2.633 registros). Era el origen de
     la diferencia 886.659 / 885.030 que se había detectado.
   - La varianza móvil fallaba con una serie de exactamente 14 registros.
   - Al guardar y cargar un proyecto se perdía la marca de emboquillado
     aplicado, y la serie del DI recalculada volvía a incluirlo.

---

## 5. Lo que no se regeneró

- **Figura 4.1** (predicción de UCS del diagnóstico inicial) y **Figura 5.20**
  (flujo de la herramienta y sus principales resultados): no salen de esta
  corrida. Si la 5.20 lleva cifras, hay que actualizarlas a mano.
- **Evaluación económica** (Tablas 5.6 a 5.10 y Figura 5.21): no depende de
  la limpieza.
- En la carpeta `figuras/tesis_2026-11-11/` quedan otras figuras que no están
  en la memoria. Algunas se dibujan con análisis que no se recalcularon
  (`F6_03c`, `F6_13c`, `F6_13b*` y `F6_13_PEP_UCS_ROP_PP*`): no usarlas sin
  volver a correr sus scripts.

---

## 6. Detalles del PDF que conviene corregir de paso

- El índice numera las figuras y tablas de resultados como 6.x y el cuerpo
  como 5.x.
- Página 54 y página 58: la referencia cruzada al Anexo C quedó rota («se
  presentan en el Fuente: Elaboración propia, 2026.»).
- Página 56: «En las Figuras 6.9 y 6.10» debería ser 5.10 y 5.11.
- Figura 5.7: «Box plot omparativo».
- Figura 5.6: el eje todavía dice «(PP + RP + AP) / ROP»; la figura nueva ya
  usa FP y PR.
- Sección 3.2.2: «entre 90 y 250 [bar]».
- Capítulo 5 usa «barreno» en casi todo el texto; la decisión fue «barreno».

---

## 7. Archivos de reemplazo

| En la memoria | Archivo en `figuras/tesis_2026-11-13/reemplazo/` |
|---|---|
| Tabla 5.1 | `Tabla_5.1_resumen_filtros` |
| (nueva) | `Tabla_5.1b_NUEVA_detalle_limites_equipo_roca` |
| Figura 5.1 | `Figura_5.1_correlacion_pearson` |
| Tabla 5.2 | `Tabla_5.2_limites_del_equipo` y `Tabla_5.2b_NUEVA_validacion_largo_barra` |
| Figura 5.2 | `Figura_5.2_antes_despues_depuracion` |
| (nuevas) | `Figura_5.2b_NUEVA_periodicidad_cambio_barra`, `Figura_5.2c_NUEVA_transitorio_cambio_barra` |
| Tabla 5.3 | `Tabla_5.3_sensibilidad_radio_RQD` |
| Figura 5.3 | `Figura_5.3_perfil_DI_P20_H12` |
| Figura 5.4 | `Figura_5.4_sensibilidad_ventana_DI` |
| Figura 5.5 | `Figura_5.5_RMSE_LOOCV_caseron` |
| Figura 5.6 | `Figura_5.6_PEP_vs_UCS` |
| Figura 5.7 | `Figura_5.7_boxplot_UCS_lab_vs_ML` |
| Figura 5.8 | `Figura_5.8_ALTERNATIVA_comparacion_algoritmos_6_sorteos` (recomendada) o `Figura_5.8_comparacion_algoritmos_un_sorteo` |
| (nueva) | `Tabla_5.8_NUEVA_R2_por_sorteo` |
| Figura 5.9 | `Figura_5.9_spearman_por_esquema` |
| Figuras 5.10 a 5.13 | `Figura_5.10_desfase_muestra_total`, `Figura_5.11_umbral_muestra_total`, `Figura_5.12_desfase_PCC0042`, `Figura_5.13_umbral_PCC0042` |
| Anexo C | `Anexo_C_desfase_PCC1541`, `Anexo_C_umbral_PCC1541` |
| Figura 5.14 | `Figura_5.14_perfil_PCS1043_P07_H4` |
| Figura 5.15 | `Figura_5.15_seccion_tronadura` |
| Figura 5.16 | `Figura_5.16_clasificacion_DI_UCS` |
| Tabla 5.4 | `Tabla_5.4_dominios` |
| Figuras 5.17 y 5.18 | `Figura_5.17_PEP_PR_PP_roca_continua`, `Figura_5.18_PEP_PR_PP_roca_discontinua` |
| Tabla 5.5 | `Tabla_5.5_ranking_G2` |
| Figura 5.19 | `Figura_5.19_PR_vs_presiones` |

Las tablas están como imagen (`.png`) con el formato de la memoria, como
`.csv` y en `tablas_capitulo5.xlsx`.
