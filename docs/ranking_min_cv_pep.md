# Ranking de 5 recomendaciones históricas — criterio «mínima variación de PEP»

Cómo se calcula el criterio de mínimo coeficiente de variación (CV) de la PEP
en la Tabla 6.4, qué mide y qué cuidados tiene. Código: `top_drilling()` y
`_segments_by_domain()` en `geomech_wizard.py`; corrida final en
`memoria_final/final/final.json` (clave `ranking`, dominio G2, Kpcli).

## 1. Qué se compara: tramos, no registros sueltos

El ranking no ordena registros individuales: ordena **tramos** de perforación.
Un tramo es una secuencia de registros **consecutivos de un mismo pozo** que
cumplen todas estas condiciones a la vez:

| Condición | Valor | Por qué |
|---|---|---|
| Mismo grupo de dominio geomecánico | el dominio evaluado (G2) | no se mezclan rocas distintas |
| Registro entrenable | pasa la limpieza estándar | sin emboquillado, empate, PP fuera de 90–230 bar ni saltos de registro |
| Roca continua | DI ≤ 1,0 | la recomendación se basa en roca sana |
| PEP válida | finita y < 800 bar·min/m | descarta ROP ≈ 0 (lavado del bit) |
| ROP válida | finita | — |
| Largo mínimo del tramo | ≥ 5 registros consecutivos (≈ 10 cm) | fijo en el código (`min_len=5`) |
| Largo mínimo del pozo | ≥ 20 m (`top.largo_min_pozo_m`) | un tiro corto está dominado por el emboquillado y la maniobra |

Basta con que **un** registro no cumpla una condición (por ejemplo, un DI > 1
o una muestra de empate) para que el tramo se corte ahí y empiece uno nuevo.

## 2. Cómo se calcula el CV

Para cada tramo se toman las PEP de **sus propios registros internos** y se
calcula:

    CV = desviación estándar (PEP del tramo) / media (PEP del tramo)

Es decir, el CV mide **cuánto varía la PEP dato a dato dentro del tramo**
(a resolución de ~2 cm). Un CV bajo significa que la perforación fue pareja:
la energía por metro casi no cambió a lo largo del tramo.

El ranking ordena los tramos de **menor a mayor CV** y entrega los cinco
primeros. Para cada uno informa el promedio de PP, RP, AP, DP y FP, la ROP y la
PEP media del tramo, el pozo y la profundidad del centro del tramo.

## 3. Los otros dos criterios, para comparar

| Criterio | Ordena por | Prioriza |
|---|---|---|
| Mín. variación de PEP | CV de la PEP del tramo (menor) | perforación estable |
| Mínima PEP | PEP media del tramo (menor) | menor energía por metro |
| Máxima ROP | ROP media del tramo (mayor) | mayor velocidad |

Los tres usan exactamente los mismos tramos; solo cambia la cifra por la que se
ordenan.

## 4. Resultado de la corrida final (dominio G2, Kpcli)

| N° | Pozo | Prof. del centro [m] | Registros del tramo | CV PEP | PEP media |
|---|---|---|---|---|---|
| 1 | PCS_1059_PR01_P205_H8 | 18,0 | 8 | 0,005 | 501 |
| 2 | PCS_1059_PR01_P204_H6 | 23,4 | 5 | 0,010 | 373 |
| 3 | PCS_1059_PR01_P204_H16 | 11,0 | 7 | 0,012 | 402 |
| 4 | PCS_1059_PR01_P103_HU10 | 28,9 | 5 | 0,013 | 400 |
| 5 | PCC_0042_PR01_TH_P32_H15 | 17,4 | 10 | 0,017 | 326 |

## 5. Cuidados al interpretarlo

1. **El CV favorece a los tramos cortos.** Con 5 a 10 registros (10 a 20 cm),
   es fácil que la PEP salga casi constante por azar; en un tramo de varios
   metros eso es mucho más difícil. Los cinco primeros tienen entre 5 y 10
   registros, así que el criterio premia sobre todo tramos muy cortos y no
   necesariamente perforaciones estables en un largo útil para la operación.
   *(Corrección: en el chat se dijo que los cinco tenían 5 registros; en
   realidad tienen 8, 5, 7, 5 y 10.)*
2. **Un CV bajo no implica eficiencia.** El primero del ranking tiene la PEP
   media más alta de los cinco (501): perforó parejo, pero gastando más
   energía por metro. Estabilidad y eficiencia son criterios distintos, y por
   eso el ranking muestra los tres.
3. **El corte de PEP es 800, no 1.000.** El resto de las figuras usa
   PEP ≤ 1.000 bar·min/m; el ranking usa < 800 (fijo en el código). La
   diferencia afecta pocos registros, pero conviene declararla o unificarla.
4. **Son recomendaciones históricas, no óptimos.** Describen tramos que ya se
   perforaron así en ese dominio; no prueban que esos seteos causen la
   estabilidad (la PEP y las presiones de reacción dependen también de la roca
   y del estado de la broca).

## 6. Mejora posible (no aplicada)

Exigir un largo mínimo de tramo mayor, por ejemplo 1 m (≈ 50 registros), haría
que el CV comparara perforaciones de largo operativo y redujera el sesgo del
punto 1. Requiere convertir `min_len` en un parámetro del perfil de faena y
volver a correr el ranking.
