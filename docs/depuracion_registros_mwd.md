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

Se excluyen del entrenamiento los registros con alguna variable fuera del
rango de operación sana del equipo:

| Variable | Mínimo | Máximo | Unidad |
|---|---:|---:|---|
| PR, velocidad de penetración | 0,1 | 1,5 | m/min |
| PP, presión de percusión | 90 | 225 | bar |
| FP, presión de avance | 20 | 150 | bar |
| DP, presión del dámper | 25 | 150 | bar |
| RP, presión de rotación | 30 | 60 | bar |
| FLP, presión del flujo de barrido | 2 | 10 | bar |

El límite inferior de la PR deja fuera, en particular, todo registro sin
avance (PR = 0) que no corresponda a un cambio de barra. Un registro sin
avance no está perforando roca: corresponde a detenciones propias del equipo,
como el lavado del bit, y en él la presión específica de penetración
(PEP = (PP + RP + FP) / PR) no está definida.

Estos registros se mantienen en la serie del DI, por cuanto corresponden a una
medición real de la perforación. La única excepción es la PR sobre 10 m/min,
el máximo alcanzable al atravesar una cavidad: un valor superior no tiene
sentido físico y el registro sale también de la serie del DI.

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
saltos. Al igual que el filtro anterior, estos registros se mantienen en la
serie del DI.

## Síntesis

El cambio de barra y el emboquillado se retiran de la serie antes de calcular
la varianza móvil y la estandarización por pozo, de modo que el DI se calcula
sobre una serie depurada. Por su parte, los límites operacionales del equipo y
la continuidad del registro solo excluyen registros del entrenamiento del
modelo de resistencia, salvo la PR sobre 10 m/min, que sale de ambos.

| Orden | Filtro | Criterio | Serie del DI | Entrenamiento |
|---|---|---|---|---|
| 1 | Cambio de barra | PR = 0 sobre la grilla de 1,756 m del pozo (±6 cm, ≥ 3 uniones), más los 2 registros siguientes | Excluye | Excluye |
| 2 | Emboquillado | Hasta que la PP se mantiene pareja 20 cm sobre el 70% de su nivel de régimen (sin meseta: 2 m) | Excluye | Excluye |
| 3 | Límites del equipo | Alguna variable fuera de su rango sano (tabla anterior) | Mantiene, salvo PR > 10 m/min | Excluye |
| 4 | Continuidad del registro | Ventana del DI que cruza un salto > 2,95 cm | Mantiene | Excluye |

> Las cantidades de registros de cada filtro se informan en Resultados, con las
> cifras de la corrida final de `final_calc.py`.
