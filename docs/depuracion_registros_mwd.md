# Depuración de los registros MWD

Antes del cálculo del Índice de Discontinuidad (DI) y del entrenamiento del
modelo de resistencia, los registros MWD se someten a cuatro filtros. Cada uno
identifica registros que no describen la respuesta del macizo rocoso a la
perforación, sino eventos propios del equipo o del registro. Según su
naturaleza, el registro se excluye de la serie con que se calcula el DI, del
conjunto de entrenamiento del modelo, o de ambos. En ningún caso se elimina:
queda marcado y conserva su posición en el pozo.

Los filtros se aplican en el orden siguiente. El cambio de barra precede al
emboquillado porque este lo utiliza para detectar la meseta de percusión. El
conjunto final de registros excluidos no depende del orden, por cuanto
corresponde a la unión de los cuatro filtros.

## 1. Cambio de barra

Al acoplar una nueva barra a la sarta de perforación, el equipo detiene el
avance y la velocidad de penetración (PR) registra un valor nulo. Este evento
se repite a lo largo del pozo a intervalos iguales al avance de una barra. Por
ello se identifican, en cada pozo, las secuencias de registros con PR = 0 y se
busca la grilla de puntos separados por un largo de barra que reúne el mayor
número de ellas, con una tolerancia de ±6 cm. La grilla se acepta solo si se
repite en al menos tres uniones del pozo. Los registros con PR = 0 que caen
sobre esa grilla corresponden a cambios de barra; una detención fuera de la
grilla no se considera como tal.

El largo de barra se verificó sobre los propios registros, sin suponerlo de
antemano:

- **Distancia entre detenciones.** Entre las 39.938 parejas de detenciones de
  un mismo pozo separadas por menos de 4 m, la distancia más frecuente es
  1,755 m. El segundo pico está en 3,510 m, el doble.
- **Barrido del largo.** Al probar largos entre 1,20 y 2,40 m, la grilla de
  1,756 m alinea 10.124 de las 14.229 detenciones fuera del emboquillado. Con
  las mismas detenciones ubicadas al azar se alinean 2.471 en promedio. A
  1,74 m se alinean 6.760, y a 1,80 m, 2.807.
- **Largo por pozo.** En los 795 pozos con al menos cuatro uniones, la
  regresión de la posición de cada detención sobre su número de unión da un
  largo de 1,7549 m, con una desviación estándar de 1,2 mm entre pozos.

El largo de 1,756 m queda así confirmado por los datos con una diferencia de
1 mm, que en un pozo de 35 m (20 barras) acumula 2 cm, dentro de la
tolerancia de ±6 cm.

Junto con la detención se excluyen los dos registros siguientes. Al comparar
cada variable con su nivel en las muestras 10 a 20 de cada lado, sobre 10.972
cambios de barra, se observa que:

- antes de la detención no hay transitorio: PR, PP, RP y FLP se mantienen
  entre 0,98 y 1,01 de su nivel en las cuatro muestras previas;
- al reanudar, la primera muestra registra la PR al 62% y la PP al 76% de su
  nivel, y la segunda la PR al 84% y la PP al 95%; desde la tercera, ambas
  quedan dentro de ±3%.

En puntos tomados al azar fuera de las detenciones, las mismas posiciones
relativas quedan en 1,00 para todas las variables. Estos registros se excluyen
de la serie del DI y del entrenamiento.

## 2. Emboquillado

Al inicio de cada pozo la broca aún no está empotrada en la roca y el operador
perfora con una percusión reducida, hasta que esta alcanza su nivel de
perforación. En lugar de un largo fijo, el fin del emboquillado se determina en
cada pozo a partir de la estabilización de la PP:

- Primero se descartan los registros de cambio de barra y los que no tienen
  avance (PR = 0), para que sus caídas no interrumpan la estabilidad.
- Luego se establece el nivel de régimen del pozo como la PP más frecuente, en
  intervalos de 5 bar.
- El emboquillado termina en el primer punto desde el cual la PP se mantiene
  pareja durante 20 cm (al menos el 90% de los registros dentro de ±15 bar de
  su mediana), con esa mediana en al menos el 70% del nivel de régimen. La
  segunda condición evita confundir la meseta de perforación con el nivel bajo
  y estable que la PP puede mostrar durante el propio emboquillado.
- En los pozos que no alcanzan esta condición se aplica un corte fijo de 2 m,
  declarado pozo por pozo.

Los parámetros del criterio se ajustaron a un conjunto de pozos revisados
manualmente. Todos los registros anteriores al fin del emboquillado se excluyen
de la serie del DI y del entrenamiento.

## 3. Límites operacionales del equipo

Se definió, para cada variable, el rango de operación sana del equipo:

| Variable | Mínimo | Máximo | Unidad |
|---|---:|---:|---|
| PR, velocidad de penetración | 0,1 | 1,5 | m/min |
| PP, presión de percusión | 90 | 230 | bar |
| FP, presión de avance | 20 | 150 | bar |
| DP, presión del dámper | 25 | 150 | bar |
| RP, presión de rotación | 30 | 80 | bar |
| FLP, presión del flujo de barrido | 2 | 10 | bar |

Los topes de la PP y de la RP se verificaron sobre los registros: la meseta
más alta que se mantiene estable durante al menos 5 m es de 225 bar en la PP y
de 81 bar en la RP, de modo que 230 y 80 bar dejan dentro todo el régimen de
perforación observado.

Un registro fuera de estos rangos se trata de dos formas, según su origen:

- **Condición del equipo.** Corresponde a registros en que el equipo no está
  perforando: sin avance (PR = 0, como las detenciones para el lavado del bit),
  sin percusión efectiva (PP bajo 90 bar) o sin empuje (FP bajo 20 bar). A
  ellos se suma la PR sobre 10 m/min, que no tiene sentido físico. Estos
  registros no describen la roca y se excluyen desde el inicio, tanto de la
  serie del DI como del entrenamiento.
- **Respuesta de la roca.** Una PR alta puede corresponder a una cavidad, y una
  RP, DP o FLP fuera de rango, a roca que opone más o menos resistencia a la
  rotación, al contacto o al barrido. Aunque escapan de lo esperado, estos
  registros informan sobre el macizo: se mantienen en la serie del DI y solo
  se excluyen del entrenamiento del modelo de resistencia. La salvedad es la
  FLP alta, que también puede deberse a un bit tapado.

## 4. Continuidad del registro

El equipo registra una muestra cada 2 cm de avance: la mediana de la
separación entre muestras consecutivas es 2,0 cm, y el 97,7% de ellas queda
entre 1,9 y 2,3 cm. Cuando el registro se interrumpe, dos muestras
consecutivas quedan separadas por un salto mayor. Como la ventana móvil del DI
abarca muestras consecutivas y supone un espaciamiento uniforme, una ventana
que cruza ese salto compara roca que no es contigua.

Se considera salto toda separación superior a 2,95 cm, cerca de 1,5 veces el
espaciamiento nominal de 2 cm. El umbral deja pasar completo el régimen
nominal de muestreo y marca solo el 0,37% de las separaciones. Se excluyen
del entrenamiento los registros cuya ventana de DI abarcaría uno de esos
saltos. Estos registros se mantienen en la serie del DI.

## Síntesis

El criterio que ordena los filtros es el origen del registro. Lo que responde
al equipo o a la operación —el cambio de barra, el emboquillado y los
registros en que el equipo no está perforando— se retira de la serie antes de
calcular la varianza móvil y la estandarización por pozo, de modo que el DI se
calcula sobre una serie depurada. Lo que puede responder a la roca se mantiene
en la serie del DI, aunque quede fuera del rango esperado, y solo se excluye
del entrenamiento del modelo de resistencia.

| Orden | Filtro | Criterio | Serie del DI | Entrenamiento |
|---|---|---|---|---|
| 1 | Cambio de barra | PR = 0 sobre la grilla de 1,756 m del pozo (±6 cm, ≥ 3 uniones), más los 2 registros siguientes | Excluye | Excluye |
| 2 | Emboquillado | Hasta que la PP se mantiene pareja 20 cm sobre el 70% de su nivel de régimen (sin meseta: 2 m) | Excluye | Excluye |
| 3a | Límites del equipo: no perfora | PR = 0, PP < 90 bar, FP < 20 bar o PR > 10 m/min | Excluye | Excluye |
| 3b | Límites del equipo: respuesta de la roca | PR, RP, DP o FLP fuera de su rango sano (tabla anterior) | Mantiene | Excluye |
| 4 | Continuidad del registro | Ventana del DI que cruza un salto > 2,95 cm | Mantiene | Excluye |

> Las cantidades de registros de cada filtro se informan en Resultados, con las
> cifras de la corrida final de `final_calc.py`.
