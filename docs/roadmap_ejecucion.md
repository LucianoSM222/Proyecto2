# PARTE I — Hoja de ruta de ejecución

## Hoja de ruta de ejecución — MWD GeoMech Wizard
### Secuencia de sesiones, modelo, esfuerzo y economía de tokens en Claude Code

**Emitido:** agosto 2026
**Contexto:** archivo único ~3.300 líneas. La regeneración completa por turno es el mayor desperdicio de tokens del proyecto; Claude Code lo elimina trabajando sobre disco.

---

## PASO 0 — Preparación del repositorio
**Costo:** unos minutos. **Ahorro:** el bloque de convenciones (~1.500 tokens) dejaría de pegarse en cada sesión.

### 0.1 — Crear `CLAUDE.md` en la raíz

Claude Code lo carga automáticamente en cada sesión. Todo lo que esté aquí **no se vuelve a pegar nunca**.

```markdown
# MWD GeoMech Wizard

Plataforma Python/Dash de archivo único para Colab. Memoria de título de
Ingeniería Civil en Minas (USACH), en convenio con Pucobre. Lee MWD en IREDES
XML de Epiroc Simba E70S con COPROD, lo cruza contra modelos DXF litológicos y
estructurales, y aplica ML para caracterizar el macizo. Sub Level Stoping,
mina subterránea de cobre.

## Convenciones inmutables — NO modificar

- Orden de campos `Val`: `LT | ROP | PP | FP | DP | RP | FLP`. Exactamente 7.
  Todo campo excedente se descarta del uso pero se REPORTA UNA VEZ en la carga.
- TMatrix del DQ: fila0 -> Norte, fila1 -> Este, fila2 -> Cota.
- Ejes DXF: X = Este, Y = Norte, Z = Cota.
- Ray casting VERTICAL (0,0,1). El grid XY de aceleración solo vale con rayo
  vertical. Cambiarlo sin rehacer el grid llevó la exactitud de 82,4% a 7,1%.
- DI: ventana 14 (~26 cm), pesos PP=0,35 DP=0,25 FP=0,20 RP=0,20, umbral 1,5.
  Fernández et al. 2023, doi:10.1016/j.ijmst.2023.02.004. El autor es el
  profesor guía.
- SE_reacción = (PP + RP + AP) / ROP. Distinto de Teale 1965: son presiones de
  reacción hidráulica, no valores impuestos. La distinción se preserva en todo
  comentario.
- UCS: límites físicos 0 a 450 MPa. Sin truncamiento silencioso jamás.
- PP: 90 a 230 bar. Es la ÚNICA variable manipulada por el operador.
- Validación: GroupKFold por pozo. Con varios caserones, LOCO-CV.

## Prohibiciones

- Coordenadas (X, Y, Z, cota) NUNCA como predictoras del modelo de
  caracterización. El yacimiento es estratiforme y la cota es proxy directo de
  litología. Solo admisible como ablación explícita.
- Ningún default silencioso. Todo dato faltante se declara y bloquea o advierte.
- Un archivo de trabajo = una mina.
- RMR nunca como predictor.
- Filtrado por percentiles prohibido. Solo límites físicos y criterios
  trazables (modo de rotura ISRM, ensayos marcados inválidos).
- Terminología: "modelo geológico informado por MWD". Nunca "corregido" ni
  "exacto".

## Sitio activo

Punta del Cobre (MPC). Envolvente UTM de sondajes:
E 376.521 - 377.005 | N 6.958.752 - 6.959.323. Margen por defecto 1.500 m.
Mina Granate está a ~3.050 m del centroide: cualquier objeto a esa distancia
es de otra mina.

## Caserones

Entrenan: 1043 (PCS), 0042 (PCC nivel 295), 1059 (PCS).
Prueba: 1541 (PCC). Demostración, fuera de entrenamiento: CAP 5.
MPC Centro y MPC Sur son contiguos y comparten geología.
Asignación entrena/prueba = parámetro de ejecución, no constante.

## Escala

~15 abanicos x 10 tiros x 35 m = ~5.250 m y ~262.500 registros por caserón,
~150 pozos. Cuatro caserones superan el millón de puntos.

## Especificaciones

Viven en `docs/`. Leer solo la que corresponda a la sesión en curso.

## Cómo trabajar aquí

- Test primero: escribir el test de aceptación, luego implementar, iterar
  contra el test.
- Entregar diffs, no el archivo completo.
- Ejecutar los tests en vez de razonar en prosa sobre si el código es correcto.
- Leer de forma dirigida (grep, funciones puntuales), no el archivo entero.
```

### 0.2 — Colocar las especificaciones en `docs/`

```
docs/
  P1_fundaciones.md              (de Prompts_S1_S3_PuntaDelCobre.md)
  P1b_roles_composicion.md       (Adenda_P1_roles_y_composicion.md)
  P1c_adendaB_bht.md             (sección Adenda B del plan consolidado)
  P2_sondajes.md
  P3_correcciones.md
  E_escala.md
  C_concordancia.md
  decisiones.md                  (registro de decisiones cerradas)
```

**Borrar `Adenda_datos_reales_PuntaDelCobre.md`.** Sus valores de Bht quedaron obsoletos con el ajuste Hoek-Brown; si queda en el repositorio, alguien va a ejecutar el equivocado.

---

## Criterio de asignación de modelo

No es por dificultad, es por **visibilidad del error**.

> **Opus** donde un error es invisible y se propaga: fuga de datos, circularidad, confusión estadística, decisiones de arquitectura caras de migrar. Ahí un test verde no prueba nada porque el error está en el planteamiento.
>
> **Sonnet** donde la especificación es precisa y el error lo atrapa un test. La mayor parte del trabajo mecánico cae acá y usar Opus sería gasto sin retorno.

El esfuerzo de razonamiento se pide explícitamente en el prompt cuando hace falta; por defecto conviene el estándar.

---

## Secuencia

| # | Sesión | Modelo | Esfuerzo | Tokens est. | Depende de |
|---|---|---|---|---|---|
| 0 | Preparación del repositorio | — | — | mínimo | — |
| 1 | **P1** Fundaciones | Opus | alto | *en curso* | — |
| 1b | **Adenda roles** y composición | Opus | medio | 40–60k | P1 |
| 1c | **Adenda B** registro de Bht | Sonnet | bajo | 30–50k | P1, 1b |
| 2 | **P2** Sondajes | Sonnet | extendido | 100–150k | P1 |
| 3 | **P3** Correcciones de uso | Sonnet | estándar | 80–120k | — |
| 4 | **E** Escala | Sonnet | extendido | 80–120k | P2 |
| — | *Carga de los 4 caserones* | — | — | — | E |
| 5 | **Entrenamiento** y LOCO-CV | Opus | alto | 150–200k | E + datos |
| 6 | **C** Concordancia | Opus | alto | 120–180k | 5 |
| 7 | **Curvas PP** y prescripción | Opus | alto | 120–180k | 5 |
| 8 | **Discriminador** fractura/contacto | Sonnet | extendido | 100–150k | P2, 5 |
| 9 | **Modelo de bloques** IDW | Sonnet | extendido | 100–150k | 5, 6 |
| 10 | **Kit Capítulo 5** | Sonnet | estándar | 60–100k | todas |

Las sesiones 1b, 1c y 3 son independientes entre sí y pueden ir en cualquier orden. Las sesiones 5 a 9 requieren los caserones cargados.

---

## Disciplina de tokens

1. **Nunca pegar el archivo fuente.** Claude Code lo lee de disco. Si un prompt incluye código del proyecto, algo se está haciendo mal.
2. **Nunca pegar las especificaciones.** Referenciar la ruta: *"implementa `docs/P2_sondajes.md`"*.
3. **Test primero.** El test de aceptación es la especificación ejecutable, y permite al agente iterar sin intervención. Es el mayor ahorro individual.
4. **Lectura dirigida.** Pedir `grep` de una función antes que leer 3.300 líneas.
5. **Una sesión, una preocupación.** `/clear` entre tareas no relacionadas. Arrastrar contexto muerto es caro y además degrada la calidad.
6. **Diffs, no archivos.** Pedir el parche.
7. **Techo de contexto.** Si una sesión pasa del 60% del contexto, detenerse y entregar una nota de estado escrita para continuar en sesión nueva. Los últimos turnos de una ventana llena son los peores y los más caros.

---

## Prompts por sesión

Cortos por diseño: las convenciones están en `CLAUDE.md` y las especificaciones en `docs/`.

---

### 1b · Adenda de roles y composición
**Opus · esfuerzo medio · 40–60k**

Opus porque cambia el esquema del registro y migrar después obliga a rehacer datos ya cargados.

```
Implementa docs/P1b_roles_composicion.md sobre el registro de vocabulario ya
construido en P1.

Piensa con cuidado antes de tocar el esquema: A.4 corrige un defecto activo.
La regla actual de bloqueo por calidad=0 haría que las alteraciones bloquearan
el entrenamiento de forma permanente, porque nunca van a tener banda de UCS.

Orden sugerido:
1. Escribe primero los siete tests sintéticos de A.6. No requieren datos reales.
2. Migra el esquema (campo `rol`) y corre los tests de P1 para verificar que
   nada se rompió.
3. Implementa alias por rol y descomposición sugerida.
4. Corrige el bloqueo de T1.5.

Al terminar reporta: atributos por rol, cuántos con calidad 0, y el resultado
de cada criterio de aceptación uno por uno.
```

---

### 1c · Registro de Brecha Hidrotermal
**Sonnet · esfuerzo bajo · 30–50k**

Sonnet porque son entradas de registro y campos nuevos: el trabajo intelectual ya está hecho en el documento.

```
Implementa docs/P1c_adendaB_bht.md.

Es principalmente poblar el registro y ampliar el esquema con cuatro campos.
Lo único que requiere atención es la distinción entre banda de confianza
(100-145) y dispersión observada (64,5-296,9): tienen que quedar en campos
separados y documentados, porque confundirlas afirmaría una homogeneidad que
los datos no respaldan.

Verifica que la matriz de traslape se recalcule y reporte con ambos criterios.
```

---

### 2 · Sondajes
**Sonnet · esfuerzo extendido · 100–150k**

Especificación precisa y verificable contra archivos reales. El desurvey ya viene resuelto en el documento.

```
Implementa docs/P2_sondajes.md.

El código de desurvey por curvatura mínima está en la especificación y ya fue
validado contra los 11 pozos MPC: úsalo tal cual.

Criterio de aceptación numérico: la banda sur debe reproducir 6 pozos,
1.102,4 m de litología y 148 estructuras en cota 263-359. Si no da eso, algo
está mal en el desurvey o en el reparto.

Escribe el test con esos números antes de implementar.
```

---

### 3 · Correcciones de uso
**Sonnet · esfuerzo estándar · 80–120k**

Nueve tareas independientes y pequeñas. Puede partirse en dos sesiones si el contexto se llena.

```
Implementa docs/P3_correcciones.md.

Las nueve tareas son independientes. Aborda de a una, corriendo la suite
después de cada una, y entrégame el diff de cada tarea por separado.

Empieza por 3.1 y 3.2 (guardia de entrenamiento degenerado y reporte de
composición), que son las que evitan resultados sin sentido.
```

---

### 4 · Escala
**Sonnet · esfuerzo extendido · 80–120k**

Sonnet basta porque el patrón —cachear, trocear, submuestrear— es conocido y la especificación es precisa. **Escalar a Opus si el perfilado revela que la extrapolación de 37 s por malla estaba muy equivocada**, porque ahí habría que rediseñar en vez de implementar.

```
Implementa docs/E_escala.md.

Empieza por E.5, el perfilado, con los archivos reales que hay en el
repositorio. Extrapola a 262.500 puntos y 8 mallas por caserón y muéstrame la
tabla ANTES de implementar el caché. Si los números salen muy distintos de la
estimación de 37 s por malla, detente y avísame: cambia el diseño.

La clave de caché tiene que incluir un hash del registro de vocabulario. Si
cambia una asignación de alias, el caché debe invalidarse solo.
```

---

### 5 · Entrenamiento y LOCO-CV
**Opus · esfuerzo alto · 150–200k**

Opus sin discusión: la fuga de datos no se ve en las métricas. Un R² alto por fuga se ve idéntico a un R² alto legítimo.

```
Piensa a fondo antes de escribir código.

Implementa el entrenamiento del modelo de caracterización con LOCO-CV sobre
los caserones cargados.

Riesgos que tienes que descartar explícitamente antes de reportar cualquier
métrica:
- Coordenadas entrando como predictoras por alguna vía indirecta.
- Puntos del mismo pozo repartidos entre entrenamiento y validación.
- Etiquetas derivadas de la malla usadas para evaluar contra esa misma malla.
- Litologías presentes en el caserón excluido y ausentes del entrenamiento:
  eso mide el hueco de muestreo, no el método.

Incluye la ablación con y sin cota, comparando desempeño dentro del caserón
contra LOCO. Si agregar cota mejora lo primero y empeora lo segundo, esa es la
firma de memorización espacial y quiero verla medida.

Reporta la composición del entrenamiento antes que cualquier métrica.
```

---

### 6 · Concordancia
**Opus · esfuerzo alto · 120–180k**

Opus por la circularidad: un reporte circular se ve exactamente como un buen resultado.

```
Piensa a fondo antes de escribir código.

Implementa docs/C_concordancia.md.

C.1 es bloqueante y es el corazón de la sesión: el sistema tiene que RECHAZAR
todo reporte que compare predicciones contra la misma malla que produjo las
etiquetas de entrenamiento. Escribe ese test primero y verifica que falla
cuando debe fallar.

El diagnóstico principal es C.3, concordancia contra distancia al sondaje más
cercano. Reporta la pendiente, no solo el gráfico.

En ninguna salida puede aparecer "corregido" ni "exacto".
```

---

### 7 · Curvas de respuesta PP y prescripción
**Opus · esfuerzo alto · 120–180k**

Opus por el confundimiento: el operador sube PP en roca dura, así que el análisis ingenuo concluye que subir PP endurece la roca.

```
Piensa a fondo antes de escribir código.

Separa el modelo de caracterización (roca <- MWD, PP como covariable de
contexto) del modelo de prescripción (desempeño <- dominio y PP, PP como
variable de decisión optimizable).

PP es la única variable que el operador manipula, y la manipula EN RESPUESTA a
la roca. Todo análisis de PP tiene que ir estratificado por dominio; agregado
va a mostrar la relación invertida.

Construye curvas PP -> (ROP, SE, CV(SE)) por dominio, con punto de saturación.

Para la función de anticipación: el desfase medio de contactos que salió de la
sesión de concordancia es el margen operacional. Si no hay casos históricos
comparables, advertir sin recomendar PP.
```

---

### 8 · Discriminador fractura / contacto
**Sonnet · esfuerzo extendido · 100–150k**

Las reglas físicas ya están definidas y las etiquetas existen. Es implementación y ajuste, no diseño.

```
Implementa el discriminador de fractura contra contacto sobre el DI existente.
No es un DI nuevo: es clasificación posterior de los picos.

Firmas físicas definidas por el usuario:
- Zona fracturada: el dámper CAE, la percusión cae, la velocidad aumenta.
- Contacto: el dámper NO CAE, la percusión se desestabiliza (sube o baja, con
  varianza no esperada), la rotación varía fuerte, la velocidad pierde su patrón.

Etiquetas de entrenamiento: las estructuras de la tabla de sondaje, y los
contactos derivados de los límites de la tabla de litología generados en P2.
Sector sur: 148 estructuras.

Implementa además RQD_MWD por definición de Deere: porcentaje de tramos
continuos de 10 cm o más sin discontinuidad. Es indicador AGREGADO por pozo y
por caserón, orientado a tronadura. El DI sigue siendo la variable de trabajo
en todo el resto del pipeline.
```

---

### 9 · Modelo de bloques
**Sonnet · esfuerzo extendido · 100–150k**

```
Implementa la interpolación a modelo de bloques con IDW anisotrópico y máscara
de soporte: los bloques sin dato cercano quedan VACÍOS, nunca interpolados
desde lejos.

Exportación dual: CSV (X, Y, Z, tamaño, UCS, DI, confianza) y DXF con capas por
banda. Bloque de 2,5 m, coherente con el burden y espaciamiento de la operación.

La confianza tiene que incorporar la calidad de la etiqueta: un dominio anclado
en un ensayo de laboratorio del sitio y otro anclado en literatura no pueden
salir con la misma confianza.

Terminología en toda salida: "modelo geológico informado por MWD".
```

---

### 10 · Kit del Capítulo 5
**Sonnet · esfuerzo estándar · 60–100k**

```
Genera el kit de resultados para el Capítulo 5: todas las figuras y tablas
exportadas con nomenclatura consistente y numeración estable, más un índice que
mapee cada archivo a la sección donde va.

Incluye la matriz de traslape con ambos criterios, la comparación de los cinco
modelos, el reporte de justificación de variables, la ablación de cota, y los
diagnósticos de concordancia.
```

---

## Nota sobre el Capítulo 4

El caso de verificación de ray casting con 82,4% usa datos de Mina Granate. Como test de regresión se conserva. Como ejemplo dentro de una memoria sobre Punta del Cobre queda descolocado: cuando estén cargadas las mallas de MPC, rehacerlo con datos del sitio y reescribir esa sección.

---


