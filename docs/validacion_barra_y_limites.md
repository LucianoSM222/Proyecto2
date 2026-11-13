# Validación del largo de barra y de los límites de limpieza

Cuatro caserones de MPC, 928 barrenos y 982.420 registros. Scripts:
`memoria_final/barra/validacion_barra.py` y
`memoria_final/barra/limites_por_grupo.py`, con sus JSON (2026-11-11).

## 1. Periodicidad de la barra

La pregunta es si las detenciones (PR = 0) se repiten cada 1,756 m. Se
respondió de tres formas, ninguna de las cuales supone el largo de antemano.

| Prueba | Resultado |
|---|---|
| Distancia más frecuente entre detenciones del mismo barreno (39.938 parejas a menos de 4 m) | **1,7549 m** (bin de 1 cm con 10.115 parejas) |
| Segundo pico, el doble del largo | 3,5096 m → 1,7548 m por barra |
| Largo que mejor alinea las detenciones, barriendo de 1,20 a 2,40 m | 1,756–1,760 m: alinea 10.124–10.132 de 14.229 detenciones |
| Mismas detenciones ubicadas al azar en el barreno | 2.471 alineadas en promedio (máximo 3.308 en 5 repeticiones) |
| Largo por barreno, regresión posición–número de unión (795 barrenos con ≥ 4 uniones) | mediana 1,7549 m, desviación estándar 1,2 mm |

Cuántas detenciones alinea la grilla según el largo probado:

| Largo probado [m] | 1,70 | 1,72 | 1,74 | 1,75 | **1,756** | 1,76 | 1,78 | 1,80 | 1,83 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Detenciones alineadas | 2.929 | 2.977 | 6.760 | 9.961 | **10.124** | 10.132 | 4.305 | 2.807 | 1.073 |

**Conclusión.** El avance por barra que registra el equipo es 1,755 m, con una
dispersión de un milímetro entre barrenos. El valor de 1,756 m difiere en 1 mm.
En un barreno de 35 m (20 barras) esa diferencia acumula 2 cm, dentro de la
tolerancia de ±6 cm del filtro. Un largo de 1,83 m (6 pies) alinearía 1.073
detenciones, menos que el azar.

## 2. Margen alrededor del cambio de barra

Sobre 10.972 cambios de barra (racha mediana: 1 registro con PR = 0), cada
variable se expresó como fracción de su nivel. El nivel es la mediana de las
muestras 10 a 20 antes y después de la detención. Como control se usaron
2.769 puntos al azar sin detención, que dan 1,00 en todas las posiciones.

| Variable | −4 | −3 | −2 | −1 | detención | +1 | +2 | +3 | +4 | +5 |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---:|---:|
| PR | 1,00 | 0,99 | 0,98 | 0,98 | 0 | **0,62** | **0,84** | 0,97 | 1,00 | 1,00 |
| PP | 1,00 | 1,00 | 1,00 | 1,00 | | **0,76** | 0,95 | 0,98 | 0,99 | 0,99 |
| FP | 1,09 | 1,10 | 1,11 | 1,11 | | **0,79** | **0,84** | 0,89 | 0,92 | 0,94 |
| DP | 0,96 | 0,95 | 0,94 | 0,94 | | **0,83** | **0,86** | 0,91 | 0,97 | 0,99 |
| RP | 1,01 | 1,01 | 1,01 | 1,01 | | 0,96 | 0,95 | 0,96 | 0,97 | 0,98 |
| FLP | 1,00 | 1,00 | 1,00 | 1,00 | | 0,94 | 0,95 | 0,96 | 0,96 | 0,97 |

- **Antes de la detención no hay transitorio.** PR, PP, RP y FLP están en
  0,98–1,01. La FP está un 10% sobre el nivel y la DP un 5% bajo él desde la
  muestra −8 en adelante. Es un cambio de nivel entre una barra y la
  siguiente, no un transitorio: después de la detención la FP se queda en
  0,95.
- **Al reanudar sí hay transitorio**, y dura dos muestras. En la primera, la
  PR cae al 62% y la PP al 76%. En la segunda, la PR está en 84% y la FP y la
  DP siguen en 84–86%. Desde la tercera, PR y PP quedan a ±3%. La DP vuelve
  a la cuarta muestra.

**Aplicado:** margen de 0 registros antes y 2 después (`barra.margen_antes`,
`barra.margen_despues`).

## 3. Límites del equipo

Base: 891.058 registros fuera del emboquillado, del cambio de barra y de los
saltos de continuidad, antes de cualquier límite de rango. Hoy, con PP en
90–230 bar, la base pierde 6.289 registros.

| Variable | Rango | Bajo el mínimo | Sobre el máximo | Fuera | % | Solo por esta variable |
|---|---|---:|---:|---:|---:|---:|
| PR [m/min] | 0,1–1,5 | 5.896 | 25.342 | 31.238 | 3,5 | 25.670 |
| PP [bar] | 90–225 | 6.283 | 99.287 | 105.570 | 11,8 | 90.190 |
| FP [bar] | 20–150 | 250 | 0 | 250 | 0,03 | 143 |
| DP [bar] | 25–150 | 1.240 | 328 | 1.568 | 0,2 | 38 |
| RP [bar] | 30–60 | 2.620 | 110.578 | 113.198 | 12,7 | 98.842 |
| FLP [bar] | 2–10 | 0 | 363 | 363 | 0,04 | 314 |
| **Alguna fuera** | | | | **232.196** | **26,1** | |

Quedan 658.862 registros entrenables. De la base, 5.569 tienen PR = 0 fuera
de la grilla de barra, y el mínimo de 0,1 m/min los saca a todos. En la
serie del DI hay 72 registros con PR > 10 m/min (110 en el total).

**Por caserón y por litología:**

| Grupo | Base | Fuera | por PP > 225 | por RP > 60 | por PR |
|---|---:|---:|---:|---:|---:|
| PCC_0042 | 437.553 | 28,5% | 8,9% | 19,7% | 2,3% |
| PCC_1541 | 179.823 | 22,3% | 13,7% | 1,4% | 7,8% |
| PCS_1043 | 141.995 | 10,5% | 0,9% | 8,5% | 1,6% |
| PCS_1059 | 131.687 | **39,8%** | **31,0%** | 9,6% | 3,9% |
| Kpcli | 512.165 | **32,2%** | 15,2% | 17,5% | 2,4% |
| Bht | 278.728 | 15,4% | 5,9% | 5,8% | 4,4% |
| Kpcls | 80.414 | 22,9% | 13,5% | 2,1% | 8,1% |
| Brecha_mixta | 19.751 | **29,3%** | 0,9% | **28,4%** | 0,7% |

(Los porcentajes por variable se superponen: un registro puede estar fuera en
más de una.)

**Advertencia.** Casi todo el recorte viene de dos límites, PP > 225 y
RP > 60, y no cae parejo:

- Cuatro de cada diez registros de PCS_1059 quedan fuera, y casi un tercio de
  Kpcli y de la Brecha mixta.
- La mediana de la PP de entrenamiento es 217,6 bar, así que el corte en 225
  cae dentro del régimen habitual de perforación, no en su borde.
- Una RP alta acompaña a la roca que cuesta rotar. Sacarla puede quitarle al
  modelo justamente la roca más competente de esas unidades.

Conviene confirmar que 225 bar y 60 bar son límites del equipo y no valores
de operación normal en estos caserones.

## 3b. Topes de PP y RP: la meseta más alta sostenida

La tabla anterior corresponde a la primera propuesta (PP hasta 225 y RP hasta
60 bar). Para fijar los topes se buscó, en cada barreno, la meseta estable más
alta que se mantiene al menos 5 m: una ventana de 5 m de registros de
perforación con el 90% dentro de una banda en torno a su mediana (±15 bar
para la PP, ±10 bar para la RP). Script: `memoria_final/barra/meseta_maxima.py`.

| | PP | RP |
|---|---:|---:|
| Barrenos con alguna meseta de 5 m | 719 | 817 |
| Meseta más alta | **225,1 bar** | **81,0 bar** |
| Mediana de la meseta más alta por barreno | 223,3 bar | 48,7 bar |
| Máximo registrado en un registro aislado | 230,5 bar | 142,6 bar |

| Tope de PP [bar] | 220 | 225 | 228 | **230** |
|---|---:|---:|---:|---:|
| Registros sobre el tope | 365.483 | 99.754 | 78 | **4** |
| Barrenos con meseta sobre el tope | 435 | 55 | 0 | 0 |

| Tope de RP [bar] | 60 | 65 | 70 | 75 | **80** | 90 |
|---|---:|---:|---:|---:|---:|---:|
| Registros sobre el tope | 109.345 | 41.048 | 8.448 | 1.838 | **578** | 72 |
| Barrenos con meseta sobre el tope | 127 | 57 | 10 | 2 | 1 | 0 |

- **PP.** El equipo trabaja con la percusión fijada en torno a 225 bar: hay 55
  barrenos con mesetas de 225,0–225,1 bar. Un tope de 225 parte ese punto de
  operación por la mitad. Sobre 228 bar no queda ninguna meseta, y sobre
  230 bar hay 4 registros.
- **RP.** Hay 127 barrenos que perforan 5 m o más con la RP sobre 60 bar: es un
  régimen de perforación, no una anomalía. La meseta más alta es de 81 bar.

**Aplicado:** PP 90–230 bar y RP 30–80 bar.

## 3c. Limpieza vigente: equipo fuera del DI, roca dentro

Criterio (decisión del autor, 2026-11-11): lo que responde al equipo sale
también de la serie del DI; lo que puede responder a la roca se queda en el
DI y solo sale del entrenamiento. Corrida completa:
`memoria_final/barra/limpieza_vigente.py`.

| | Registros | % del total |
|---|---:|---:|
| Total | 982.420 | 100 |
| En la serie del DI | 860.824 | 87,6 |
| Fuera de la serie del DI | 121.596 | 12,4 |
| Entrenables | 835.885 | 85,1 |
| No entrenables | 146.535 | 14,9 |

| Filtro | Registros |
|---|---:|
| Emboquillado (corte mediano 1,50 m; 11 barrenos con el corte de respaldo de 2 m) | 75.104 |
| Cambio de barra con sus 2 registros siguientes (los no excluidos ya por otro filtro) | 19.424 |
| Límites del equipo (los no excluidos ya por el emboquillado) | 46.806 |
| Continuidad (los no excluidos ya por otro filtro) | 5.201 |

Registros fuera de cada límite, contados sobre todo el registro (se
superponen entre sí y con el emboquillado): PR 56.673, PP 19.181, RP 7.458,
DP 3.665, FLP 3.568 y FP 584.

Condiciones de equipo fuera del emboquillado, que salen de la serie del DI:
PR = 0 en 17.074 registros (incluye los cambios de barra), PP bajo 90 bar en
7.997, FP bajo 20 bar en 393 y PR sobre 10 m/min en 72. También salen la FLP
sobre 10 bar (bit tapado) y las ventanas que cruzan un salto de continuidad:
entre las dos retiran 3.765 registros más de la serie, que pasó de 864.589 a
860.824.

Entrenables por caserón y por litología:

| Grupo | Total | Entrenables | % |
|---|---:|---:|---:|
| PCC_0042 | 479.316 | 415.452 | 86,7 |
| PCC_1541 | 202.827 | 161.405 | 79,6 |
| PCS_1043 | 157.195 | 135.635 | 86,3 |
| PCS_1059 | 143.082 | 123.393 | 86,2 |
| Kpcli | 558.344 | 486.601 | 87,2 |
| Bht | 306.552 | 258.468 | 84,3 |
| Kpcls | 96.865 | 71.888 | 74,2 |
| Brecha_mixta | 20.659 | 18.928 | 91,6 |

Con los topes nuevos el recorte queda parejo entre caserones (80–87%). La
unidad que más pierde es Kpcls (74%).

## 4. Umbral de continuidad (2,95 cm)

| | |
|---|---|
| Separaciones entre muestras consecutivas | 981.420 |
| Mediana | 2,00 cm |
| Media | 2,06 cm |
| Separaciones entre 1,9 y 2,3 cm | 97,65% |
| Separaciones sobre 2,95 cm | 0,37% |
| 2,95 cm / 2,00 cm | 1,475 |

El umbral equivale a 1,5 veces el espaciamiento nominal de 2 cm: deja pasar
completo el régimen de muestreo y marca solo los saltos. Redondearlo a 3,0 cm
cambia poco, porque entre 2,9 y 3,1 cm hay solo 105 separaciones.
