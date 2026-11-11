# Depuración de los registros MWD

Antes del cálculo del Índice de Discontinuidad (DI) y del entrenamiento del
modelo de resistencia, los registros MWD se someten a cinco filtros. Cada uno
identifica registros que no describen la respuesta del macizo rocoso a la
perforación, sino eventos propios del equipo o del registro. Según su
naturaleza, el registro se excluye de la serie con que se calcula el DI, del
conjunto de entrenamiento del modelo, o de ambos. En ningún caso se elimina:
queda marcado y conserva su posición en el pozo.

Los filtros se aplican en el orden siguiente. Los dos primeros preceden al
emboquillado porque este los utiliza para detectar la meseta de percusión. El
conjunto final de registros excluidos no depende del orden, por cuanto
corresponde a la unión de los cinco filtros.

## 1. Cambio de barra

Al acoplar una nueva barra a la sarta de perforación, el equipo detiene el
avance y la velocidad de penetración (PR) registra un valor nulo. Este evento
se repite a intervalos regulares a lo largo del pozo, iguales al largo de la
barra del Simba E70S (1,756 m). Por ello se identifican, en cada pozo, las
secuencias de registros con PR = 0 y se busca la grilla de puntos separados por
un largo de barra que reúne el mayor número de ellas, con una tolerancia de
±6 cm. La grilla se acepta solo si se repite en al menos tres uniones del pozo.
Los registros con PR = 0 que caen sobre esa grilla corresponden a cambios de
barra; una detención fuera de la grilla no se considera como tal. Estos
registros se excluyen de la serie del DI y del entrenamiento.

## 2. Regulación automática de la percusión

La presión de percusión (PP) es la variable que fija el operador y, en
condiciones normales, se mantiene estable. Sin embargo, cuando el resto de las
presiones sale del rango normal de operación del equipo, el sistema de control
ajusta la percusión en forma automática, lo que se manifiesta como una caída
breve de la PP que se recupera de inmediato. Se identifica un registro de
regulación cuando su PP cae al menos un 25% respecto del promedio de sus dos
registros vecinos y estos difieren entre sí menos de un 12,5%. Esta segunda
condición distingue una caída aislada que se recupera de una disminución
sostenida, que sí puede responder a un cambio en el macizo. Dado que el
fenómeno responde al equipo y no a la roca, estos registros se excluyen de la
serie del DI y del entrenamiento.

## 3. Emboquillado

Al inicio de cada pozo la broca aún no está empotrada en la roca y el operador
perfora con una percusión reducida, hasta que esta alcanza su nivel de
perforación. En lugar de un largo fijo, el fin del emboquillado se determina en
cada pozo a partir de la estabilización de la PP:

- Primero se descartan los registros de cambio de barra y de regulación, para
  que sus caídas no interrumpan la estabilidad.
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

## 4. Presión de percusión fuera de rango

Se excluyen del entrenamiento los registros con PP fuera del rango operacional
del equipo, entre 90 y 230 bar. Bajo ese intervalo la percusión no realiza un
trabajo efectivo de destrucción de roca, y sobre él el valor no es consistente
con la operación del equipo. Estos registros se mantienen en la serie del DI,
por cuanto corresponden a una medición real de la perforación.

## 5. Continuidad del registro

El equipo registra una muestra aproximadamente cada 2 cm de avance. Cuando el
registro se interrumpe, dos muestras consecutivas quedan separadas por un salto
mayor. Como la ventana móvil del DI abarca 14 muestras consecutivas (≈ 28 cm) y
supone un espaciamiento uniforme, una ventana que cruza ese salto compara roca
que no es contigua. Se consideran saltos las separaciones superiores a 2,95 cm
entre muestras consecutivas, y se excluyen del entrenamiento los registros cuya
ventana de DI abarcaría uno de ellos. Al igual que el filtro anterior, estos
registros se mantienen en la serie del DI.

## Síntesis

El emboquillado, el cambio de barra y la regulación automática de la percusión
se retiran de la serie antes de calcular la varianza móvil y la estandarización
por pozo, de modo que el DI se calcula sobre una serie depurada. Por su parte,
la presión de percusión fuera de rango y la continuidad del registro solo
excluyen registros del entrenamiento del modelo de resistencia.

| Orden | Filtro | Criterio | Serie del DI | Entrenamiento |
|---|---|---|---|---|
| 1 | Cambio de barra | PR = 0 sobre la grilla de 1,756 m del pozo (±6 cm, ≥ 3 uniones) | Excluye | Excluye |
| 2 | Regulación automática de la percusión | Caída de PP ≥ 25% respecto de sus vecinos, con recuperación | Excluye | Excluye |
| 3 | Emboquillado | Hasta que la PP se mantiene pareja 20 cm sobre el 70% de su nivel de régimen (sin meseta: 2 m) | Excluye | Excluye |
| 4 | PP fuera de rango | PP < 90 o > 230 bar | Mantiene | Excluye |
| 5 | Continuidad del registro | Ventana del DI que cruza un salto > 2,95 cm | Mantiene | Excluye |

> Las cantidades de registros de cada filtro se informan en Resultados, con las
> cifras de la corrida final de `final_calc.py`.
