# MWD GeoMech Wizard — Documento maestro
## Punta del Cobre · Especificaciones, plan de ejecución y prompts

**Luciano San martín Cid** — Memoria de Título, Ingeniería Civil en Minas, USACH
En convenio con Pucobre · Emitido agosto 2026

---

> **Nota de uso.** Este documento reúne todo en un solo archivo, útil como
> referencia y respaldo. **Para trabajar en Claude Code conviene igualmente
> partirlo**: `CLAUDE.md` en la raíz con las convenciones (Parte I, sección 0.1)
> y una especificación por archivo en `docs/`. Si el agente carga este documento
> completo para implementar una sola sesión, se paga contexto que no se usa.
>
> **Documento obsoleto:** `Adenda_datos_reales_PuntaDelCobre.md` quedó superado
> por la Parte V. Sus valores de Brecha Hidrotermal son anteriores al ajuste
> Hoek-Brown y no deben usarse.

---

## Índice

1. [PARTE I — Hoja de ruta de ejecución](#parte-i-hoja-de-ruta-de-ejecución)
2. [PARTE II — Decisiones cerradas](#parte-ii-decisiones-cerradas)
3. [PARTE III — P1 · Fundaciones (referencia, ya ejecutada)](#parte-iii-p1-fundaciones-referencia-ya-ejecutada)
4. [PARTE IV — P1b · Roles y composición](#parte-iv-p1b-roles-y-composición)
5. [PARTE V — P1c · Adenda B · Registro de Brecha Hidrotermal](#parte-v-p1c-adenda-b-registro-de-brecha-hidrotermal)
6. [PARTE VI — P2 · Sondajes](#parte-vi-p2-sondajes)
7. [PARTE VII — P3 · Correcciones de uso real](#parte-vii-p3-correcciones-de-uso-real)
8. [PARTE VIII — Sesión E · Escala](#parte-viii-sesión-e-escala)
9. [PARTE IX — Sesión C · Concordancia](#parte-ix-sesión-c-concordancia)
10. [PARTE X — Criterios de aceptación consolidados](#parte-x-criterios-de-aceptación-consolidados)
11. [ANEXO — Bloque común de convenciones (versión larga)](#anexo-bloque-común-de-convenciones-versión-larga)

---


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


# PARTE II — Decisiones cerradas

### Decisiones cerradas en esta ronda

**Caserones.** Descartados 1501, 1502 y 1055 (sin capas ni sondaje). Selección:

| rol | caserón | sector | aporte |
|---|---|---|---|
| entrena | **1043** | PCS | gran variedad litológica, mucho MWD |
| entrena | **0042** | PCC, nivel 295 | Bht + lavas, mucho MWD, capas en mano |
| entrena | **1059** | PCS | aporta brecha mixta |
| **prueba** | **1541** | PCC | estrecho: lavas + albitófiro, ambas presentes en los de entrenamiento |
| demostración | CAP 5 | PCS | dos diques de resistencia desconocida — **fuera del entrenamiento** |

Geología confirma que 1043, 0042 y 1059 contienen las litologías presentes en 1541. **MPC Centro y MPC Sur son contiguos y comparten el mismo tipo de geología**, de modo que el conjunto es geológicamente coherente.

La asignación entrenamiento/prueba es **parámetro de ejecución**, no constante de código.

**Alteraciones.** No son dimensión obligatoria del dominio. Los dominios se definen por litología + estructura. La alteración se **registra cuando viene en el dato** (la carga puntual trae Silícea; CAP 5 trae magnetita) y se activa como dimensión solo en un experimento nombrado.

**Campos `Val`.** Se usan exactamente siete: `LT | ROP | PP | FP | DP | RP | FLP`. Todo campo excedente se descarta del uso, pero **se reporta una vez en la carga** ("se encontraron 8 campos, se usaron 7"). Descarte silencioso está prohibido.

**Volumen.** 15 abanicos × 10 tiros × 35 m ≈ **5.250 m y 262.500 registros por caserón**, ~150 pozos. Cuatro caserones superan el millón de puntos.

---


# PARTE III — P1 · Fundaciones (referencia, ya ejecutada)

## P1 — FUNDACIONES
#### Partición por sitio y registro de vocabulario
**Modelo sugerido:** Opus con pensamiento extendido alto.

### Objetivo

Construir la capa que hace la herramienta portable a otras minas y que impide que un dato de un sitio contamine otro. Es la pieza que convierte los datos faltantes (como el UCS de Bht) en estados manejados en lugar de bloqueos.

### Tarea 1.1 — Constante de sitio y guardián por coordenadas

Declarar en configuración el sitio activo: identificador, nombre para mostrar, envolvente UTM y margen configurable (por defecto 1.500 m).

Implementar un guardián que, ante cualquier objeto cargado —malla DXF, XML de MWD, collar de sondaje— calcule su centroide y su distancia al centroide del sitio declarado. Si excede el margen:

- **No** cargar silenciosamente.
- Mostrar la distancia medida y el umbral.
- Exigir confirmación explícita para continuar.

El principio: **las coordenadas son la autoridad de pertenencia a un sitio, no el nombre del archivo ni el desplegable que eligió el usuario.**

*Criterio de aceptación:* cargar un archivo con coordenadas de Granate (E ≈ 373.936, N ≈ 6.960.177) debe disparar la advertencia reportando ~3.050 m. Cargar cualquier archivo MPC no debe disparar nada.

### Tarea 1.2 — Registro de atributos canónicos

Estructura de cada atributo:

```
id
nombre_oficial          "Albitófiro"
sitio                   "MPC"
nivel                   "unidad" | "subunidad"
padre                   id del atributo unidad que la contiene (None si es unidad)
ucs_min, ucs_max, ucs_media, ucs_sd, ucs_n
fuente                  texto libre: "Karzulovic & Asoc. 2005, Tabla 3.2"
calidad                 0 sin_asignar
                        1 ensayo_del_sitio
                        2 componente_RMR_local
                        3 analogo_del_distrito
                        4 literatura
fecha
mi, modulo_E, poisson, densidad     (opcionales)
notas
```

El campo `calidad` **no es decorativo**: debe modular el ancho del intervalo de predicción del modelo. Un ancla de laboratorio con una probeta y un análogo de otra mina no pueden producir la misma confianza.

Todos los campos numéricos editables desde la interfaz, para absorber futuras campañas de ensayo sin tocar código.

**Prepoblar** con la tabla de Karzulovic del Bloque Común y con los códigos de sondaje conocidos:

- `Kfa` → Albitófiro · unidad · 274,3 / 304,9 / media 289,6 · sd None · n desconocido (marcar) · calidad 1
- `Bht` → Brecha Hidrotermal · unidad · UCS sin asignar · **calidad 0**
- `Kpcli` → Lavas Inferiores · unidad · UCS sin asignar · **calidad 0**
- `DL` → sin identificar · **calidad 0**
- Brecha mixta y Brecha sedimentaria como **subunidades** de Brecha basal
- Lutitas normales y Lutitas metamorfoseadas como **subunidades** de Miembro Trinidad (Kpcs)

> **Trampa de nomenclatura a documentar:** el código `Kpcsb` se usa en la literatura tanto para la Brecha basal (la unidad padre, según Marschik) como para la Brecha sedimentaria (una de sus subunidades, según Ortiz et al.). El registro debe distinguirlas con identificadores distintos y dejar constancia de la ambigüedad.

### Tarea 1.3 — Registro de alias

```
texto_crudo        "Kfa" | "KFA" | "Albitófiro" | "ALB"
atributo_id
origen             dxf_layer | sondaje_unidad | excel | manual
```

Reglas:
- El emparejamiento para *sugerencia automática* es insensible a mayúsculas, espacios y acentos. El alias **almacenado** conserva el texto crudo original.
- Un alias apunta a **exactamente un** atributo. Intentar mapearlo a dos es un error, no una advertencia.
- Al cargar capas DXF o sondajes, todo texto no reconocido aparece en una bandeja de **pendientes de asignar**, visible y contabilizada.

### Tarea 1.4 — Resolución de traslape por nivel

Este es el reemplazo de la lógica `lito_hit[i] = name`, que hacía ganar a la última capa cargada y produjo un modelo degenerado con R² = 1,0.

Cuando un punto cae dentro de más de una malla:

| caso | resolución |
|---|---|
| unidad + su propia subunidad | gana la **subunidad** (es más específica). No es conflicto. |
| dos unidades distintas | **ambiguo** → excluir el punto y contabilizarlo |
| dos subunidades de padres distintos | **ambiguo** → excluir y contabilizar |
| dos subunidades del mismo padre | **ambiguo** → excluir y contabilizar |
| litología + estructura | **la estructura predomina totalmente** |
| litología + alteración | **se componen** (riolita+argílica ≠ riolita+potásica) |
| alteración sola | no define dominio |

Sin la declaración de nivel malla por malla, el código no puede distinguir un anidamiento legítimo de un error de modelamiento. Leapfrog modela con métodos probabilísticos y las mallas pueden interponerse; el MWD es la tercera fuente que evalúa dónde acertó la interpolación.

Todo punto excluido por ambigüedad debe quedar **contabilizado y reportado**, nunca descartado en silencio.

### Tarea 1.5 — Estado sin-asignar que bloquea

Un atributo con `calidad = 0` o sin banda de UCS **no puede entrar al entrenamiento**. El intento debe fallar de forma ruidosa, nombrando qué atributos faltan y cuántos metros o puntos representan.

Ejemplo del mensaje esperado: *"No se puede entrenar: 3 atributos sin banda de UCS asignada (Bht 576,9 m · Kpcli 20,8 m · DL 3,1 m). Asignar en el registro de vocabulario o excluir explícitamente."*

Debe existir la acción **excluir explícitamente**, que registra la exclusión con su justificación y permite continuar. Es la vía prevista para DL y Kpcli, que juntos son el 1,4% del metraje.

### Tarea 1.6 — Límites de UCS sin truncamiento silencioso

Corregir el bug por el cual el campo de rango quedaba acotado a un máximo físico y, al ingresar un valor superior, el componente devolvía `None` y la expresión `float(v or default)` caía al valor por defecto, excluyendo silenciosamente una litología completa.

Nuevo comportamiento: límites físicos 0 a 450 MPa; un valor fuera de rango produce **error visible**, nunca sustitución.

### Tarea 1.7 — Persistencia

Exportar e importar el registro completo (atributos + alias + exclusiones justificadas) como archivo JSON o CSV. Debe ser legible por humanos, versionable, y **publicable como anexo de la memoria**.

### Tarea 1.8 — Interfaz

Panel dedicado con: tabla de atributos editable, tabla de alias, bandeja de pendientes con contador, y botones de exportar/importar. El contador de pendientes debe ser visible desde la vista principal, no escondido en el panel.

---

---


# PARTE IV — P1b · Roles y composición

## ADENDA A P1 — Roles de atributo y composición litología + alteración

**Pegar en la sesión de P1 en curso.** Modifica T1.3, T1.4 y T1.5 ya implementadas, y agrega tres tareas de robustez.

---

### Motivo

Se confirmó que **`Fk` significa feldespato potásica**, que es una *alteración*, mientras que **`Kfa` es Albitófiro**, que es una *litología*. Son strings casi invertidos con roles opuestos: esta colisión fue el origen de una confusión de nomenclatura que estuvo a punto de invalidar el 66% del metraje de sondaje. **Registrarla en las notas del registro de vocabulario.**

El archivo `Bht_Fk.dxf` demuestra que las capas de Leapfrog pueden venir con **litología y alteración compuestas en un solo nombre**. Aunque ese archivo pertenece a otro sitio (Mina Granate, MGN 3025) y las capas de Punta del Cobre todavía no se cargan, el convenio de nombres puede repetirse. La estructura del registro debe admitirlo desde ahora.

La regla vigente —"un alias apunta a exactamente un atributo"— no puede representar `Bht_Fk`, que debe resolver a dos atributos de roles distintos.

---

### A.1 — Campo `rol` en el atributo canónico

Agregar campo obligatorio `rol`, enumeración extensible con valores iniciales:

```
litologia | alteracion | estructura
```

**Migración:** todos los atributos ya prepoblados (Albitófiro, Brecha Hidrotermal, Lavas Inferiores, Brecha mixta, Brecha sedimentaria, Lutitas normales, Lutitas metamorfoseadas, DL) reciben `rol = litologia`. Agregar `Fk → Feldespato potásica` con `rol = alteracion`.

Los campos de banda de UCS (`ucs_min`, `ucs_max`, `ucs_media`, `ucs_sd`, `ucs_n`, `fuente`, `calidad`) **solo aplican a `rol = litologia`**. En los demás roles quedan nulos y la interfaz no debe ofrecerlos.

---

### A.2 — Alias que resuelven a un conjunto por rol

Reemplazar la regla actual por:

> **Un alias apunta a exactamente un atributo por rol.**

Un alias resuelve a un diccionario `{rol: atributo_id}`:

```
Kfa      → {litologia: Albitófiro}
Fk       → {alteracion: Feldespato potásica}
Bht_Fk   → {litologia: Brecha Hidrotermal, alteracion: Feldespato potásica}
```

La garantía de unicidad se conserva: **dos atributos del mismo rol en un mismo alias es un error, no una advertencia.**

*Por qué no la alternativa:* crear un atributo canónico por cada par litología×alteración produce n×m entradas, casi todas sin ensayo de laboratorio asociado, y multiplica el registro sin aportar información.

---

### A.3 — Descomposición sugerida de nombres compuestos

Al encontrar un nombre de capa no reconocido, intentar descomponerlo:

1. Partir por separadores comunes: `_`, `-`, `+`, espacio.
2. Emparejar cada token contra el registro de alias (insensible a mayúsculas, espacios y acentos).
3. Si los tokens resuelven a roles **distintos**, proponer la composición.
4. Si dos tokens resuelven al **mismo rol**, no proponer nada: es ambiguo y va a la bandeja de pendientes.
5. Tokens sin correspondencia → bandeja de pendientes.

**La composición se propone, nunca se acepta sola.** Requiere confirmación explícita.

Una vez confirmada, **almacenar el string crudo completo como alias propio** (`Bht_Fk → {litologia: …, alteracion: …}`), para que la próxima vez resuelva directo sin volver a descomponer.

---

### A.4 — Corrección de T1.5: el bloqueo alcanza solo a litologías

**Este es un defecto activo.** Tal como está implementada, la regla "atributo con `calidad = 0` bloquea el entrenamiento" haría que `Fk` bloqueara de forma permanente e insalvable: las alteraciones no tienen banda de UCS y **nunca la van a tener**, porque Karzulovic reporta por litología, no por litología×alteración.

Nueva regla:

- El chequeo de banda de UCS aplica **solo a atributos con `rol = litologia`**.
- Alteraciones y estructuras se registran, componen dominio, y **no participan** del chequeo.

Dejar escrito en el código y en la documentación:

> La banda de UCS es propiedad de la litología. `Bht+Fk` y `Bht+otra alteración` son dominios distintos que heredan la misma banda como valor previo. Si el MWD muestra que difieren, eso es un hallazgo, no un error.

---

### A.5 — Reescritura de T1.4 como regla por rol

La tabla de casos se reemplaza por cuatro reglas:

| regla | comportamiento |
|---|---|
| **Conflicto** | Dos atributos del **mismo rol** en un punto → ambiguo, excluir, contabilizar |
| **Composición** | Atributos de **roles distintos** → se componen en un dominio |
| **Anidamiento** | Dentro de `rol = litologia`, unidad + su subunidad → gana la **subunidad**. No es conflicto |
| **Predominio** | `rol = estructura` predomina sobre todo lo demás |

La clave de dominio pasa a ser el par `(litologia, alteracion|None)`. La banda de UCS se hereda de la litología.

Estas reglas deben funcionar de forma idéntica sea que el rol provenga de una malla compuesta (`Bht_Fk.dxf`) o de dos mallas separadas que se traslapan. **El resultado no puede depender de cómo vino empaquetada la información.**

Todo punto excluido por ambigüedad sigue contabilizándose y reportándose.

---

### A.6 — Tests sintéticos de traslape

**No requieren datos reales.** Construir mallas de cajas en memoria o como DXF mínimos.

La guarda geométrica actual con `Bht_Fk.dxf` verifica `classify_all_wells` **con una sola malla**, y con una sola malla no existe traslape: la lógica de T1.4 nunca se ejecuta. Hoy está protegida la geometría, no las reglas de resolución. El canario original tampoco cubría esto — H5 contra `Metandesitas.dxf` es también un caso de malla única.

Casos mínimos a cubrir:

1. **Anidamiento.** Caja A (`unidad`) contiene caja B (`subunidad` de A). Punto interior a ambas → resuelve a **B**. Contador de ambiguos = 0.
2. **Conflicto de unidades.** Cajas A y C, ambas `unidad` de `rol litologia`, que se cruzan. Punto en la intersección → **ambiguo**, excluido, contador = 1.
3. **Conflicto de subunidades.** Dos `subunidad` del mismo padre que se cruzan → **ambiguo**.
4. **Composición.** Caja de `rol litologia` traslapada con caja de `rol alteracion` → dominio compuesto, contador de ambiguos = 0, banda de UCS heredada de la litología.
5. **Predominio.** Caja de `rol estructura` sobre cualquiera de las anteriores → gana la estructura.
6. **Equivalencia de empaquetado.** El caso 4 resuelto mediante dos mallas separadas y mediante una malla compuesta `A_B.dxf` debe producir **resultado idéntico**.
7. **Punto fuera de todo** → sin clasificar, contabilizado como tal.

El contador de ambiguos debe ser accesible desde el reporte de composición del entrenamiento.

---

### A.7 — Exención explícita del guardián de sitio para fixtures

`Bht_Fk.dxf` pertenece a Mina Granate. Con el sitio activo en MPC, cargarlo por el flujo normal **debe disparar la advertencia de T1.1** reportando ~3.050 m de distancia. Verificar que efectivamente lo hace: es una buena prueba del guardián.

Pero los tests que usan ese archivo como fixture geométrico necesitan cargarlo sin fricción. Agregar una exención **explícita y declarada**:

```
exento_guardian_sitio = True
motivo = "fixture geométrico; el sitio es irrelevante para el test de ray casting"
```

**Nunca implícita, nunca por omisión.** Si un fixture de otro sitio pudiera cargarse sin declararlo, el guardián estaría silenciosamente roto.

---

### A.8 — Suites que fallan por archivos ausentes

Las cinco suites que fallan con "Faltan archivos reales" deben marcarse como **omitidas** (`skip`), con la razón visible, no como fallidas.

Con cinco rojos permanentes, una regresión real se esconde entre ellos y nadie la nota. La suite debe quedar verde para que un rojo signifique algo.

---

### Criterios de aceptación de la adenda

- [ ] Todo atributo tiene `rol`; los prepoblados migrados a `litologia`; `Fk` agregado como `alteracion`
- [ ] `Bht_Fk` resuelve a dos atributos de roles distintos
- [ ] Dos atributos del mismo rol en un alias → error
- [ ] Un alias compuesto confirmado queda almacenado como alias propio
- [ ] `Fk` (calidad 0, rol alteración) **no** bloquea el entrenamiento
- [ ] Una litología sin banda **sí** lo bloquea, nombrándola
- [ ] Los siete casos sintéticos de A.6 pasan
- [ ] Los casos 4 y 6 producen resultado idéntico entre malla compuesta y mallas separadas
- [ ] Cargar `Bht_Fk.dxf` por flujo normal con sitio MPC dispara la advertencia de distancia
- [ ] La exención de fixture es explícita y su ausencia hace fallar el test
- [ ] `pytest` termina verde: las cinco suites aparecen omitidas, no fallidas
- [ ] `test_p1_fundaciones.py` sigue pasando completo

---


# PARTE V — P1c · Adenda B · Registro de Brecha Hidrotermal

## ADENDA B (revisada) — Registro de Brecha Hidrotermal

### B.1 — La trampa documentada

**Comentario permanente en el registro.**

La hoja `UCS-TX` de `BRECHA_2.XLS` muestra una columna `σ1 [MPa]` con ocho probetas BHT y un promedio de **198,19 MPa** en la fila 14.

> **Ese promedio NO es el UCS.** Seis de las ocho probetas son ensayos triaxiales. El σ3 de cada una está en la hoja `Envolvente`, no en `UCS-TX`.

| probeta | σ3 | σ1 | | probeta | σ3 | σ1 |
|---|---|---|---|---|---|---|
| 2 BHT | **0** | 182,4 | | 7 BHT | **0** | 296,9 |
| 3 BHT | 6 | 192,5 | | 8 BHT | 9 | 222,1 |
| 4 BHT | 3 | 132,6 | | 10 BHT | 12 | 219,2 |
| 5 BHT | 6 | 152,0 | | 6 BHT | 3 | 187,9 |

Con los parámetros ajustados abajo, **6 MPa de confinamiento agregan cerca de 35%**: la envolvente predice σ1 ≈ 173 MPa para un material cuyo UCS es 128. Ahí está toda la diferencia entre 198 y 128.

Toda lectura futura de este libro **debe filtrar por σ3 = 0** antes de calcular estadísticas de UCS.

Nota adicional: la hoja `RocData` es la **entrada** de ese software, no su salida — un listado ensayo por ensayo (`TRX`, `UCS`, `UCS DEF`, `TID`) con identificador de probeta. RocData ajusta una envolvente a los pares (σ3, σ1) que recibe; no convierte usando módulo de Young ni velocidad de onda. `UCS DEF` es uniaxial con medición de deformabilidad.

### B.2 — Ajuste Hoek-Brown

Ajuste de roca intacta (s=1, a=0,5) sobre los **25 ensayos de compresión** del libro (15 triaxiales + 10 uniaxiales):

```
σci = 128,1 MPa      mi = 14,77      RMSE = 51,8 MPa
```

**Validado contra 18 ensayos brasileños que no entraron en el ajuste:** la envolvente predice σt = −8,63 MPa; lo medido da media −7,78, dentro del rango observado (−5,39 a −10,25). La forma de la envolvente es correcta.

### B.3 — Corroboración independiente por carga puntual

Campaña `PLT_MPC-NIVEL_175-CZ_06_Sector_CAS1004S_CAP_5`: 30 bloques irregulares de Brecha Hidrotermal con alteración silícea, MPC nivel 175, ensayados 30-03-2026 y 09-04-2026.

Separando por modo de rotura, que es lo que corresponde porque solo las roturas por matriz representan roca intacta:

```
por matriz         n=16   media 112,1   mediana 111,5   CV 0,563
por discontinuidad n=13   media 120,1   mediana 113,9   CV 0,353
promedio informe                        119,7
```

**Convergencia de cuatro métodos independientes** — dos laboratorios, tres tipos de ensayo, dos sectores:

| método | UCS |
|---|---|
| σci del ajuste Hoek-Brown (25 ensayos) | 128,1 |
| promedio de los 10 uniaxiales | 123,9 |
| carga puntual del informe (n=29) | 119,7 |
| carga puntual por matriz (n=16) | 112,1 |

### B.4 — Registro del atributo

```
Bht — Brecha Hidrotermal
  rol                 litologia
  nivel               unidad
  ucs_central         128,1
  ucs_banda_min       100        <- banda de confianza sobre el valor central
  ucs_banda_max       145
  dispersion_min      64,5       <- dispersión observada del material
  dispersion_max      296,9
  ucs_cv              0,57
  mi                  14,77
  sigma_t             -7,8
  fuente              "Hoek-Brown ajustado sobre 25 ensayos, BRECHA_2.XLS,
                       Laboratorio Punta del Cobre 19-06-2022.
                       Corroborado por carga puntual n=16 rotura por matriz,
                       CAS1004S nivel 175, marzo-abril 2026"
  calidad             1  (ensayo del sitio)
```

**Ampliar el esquema del atributo** con `ucs_central`, `dispersion_min`, `dispersion_max` y `ucs_cv`.

#### Distinción que debe quedar explícita en el código y en la memoria

> `ucs_banda_min/max` (100–145) es la **banda de confianza sobre el valor central**, no el rango de resistencia del material. Declarar 100–145 como rango del material afirmaría un CV de 0,09 —tan homogéneo como las lutitas— cuando cuatro métodos independientes miden 0,56.
>
> El modelo **entrena con el valor central**. La dispersión observada **gobierna el ancho del intervalo de predicción**.

**Prohibido** recortar valores por percentil: este proyecto rechazó explícitamente el filtrado por percentiles a favor de límites físicos. Los únicos filtros admitidos sobre probetas son físicos y trazables: modo de rotura por discontinuidad (estándar ISRM) y ensayos marcados `Inválido`.

Verificación registrada: excluir las probetas de densidad anómala (muestras 2 y 3, con 3,18 y 4,15 g/cm³) **no** produce el rango 100–145 — retira los valores altos 182,4 y 169,1 y baja la media a 110,9.

### B.5 — Alerta de variabilidad y techo del modelo

Si `ucs_cv > 0,35`, la interfaz muestra advertencia junto al atributo y el intervalo de predicción se ensancha.

Documentar:

> La granularidad de la etiqueta acota el techo del modelo. Con todos los puntos de Bht etiquetados en 128, el modelo no puede predecir nada distinto de 128 dentro de Bht: la resolución punto a punto no se cumple **para el UCS**. Sí se cumple para la asignación de dominio y para el DI. La variabilidad interna de Bht excede la resolución del modelo, y eso se declara como limitación.

### B.6 — Otros parámetros del mismo libro

- **Tracción indirecta** (`TI`): σt 4,57 a 21,99 MPa; media 14,9; CV 0,388. Una probeta marcada `Inválido` (ruptura tipo I) — **excluir**.
- **Ángulo de fricción básico** (`TT` / `Tres Núcleos`, tres núcleos ISRM): φb 26,57° a 30,29°.
- **Dureza Leeb** (`DS`): rebotes corregidos, FC = 0,9276.
- **Alteraciones observadas:** Silícea (mayoría de la carga puntual), Mineralizada (2 bloques), magnetita (CAP 5).
- **Densidad bimodal:** muestras 1–5 entre 3,15 y 4,15; muestras 6–10 entre 2,63 y 2,77. **No explica la variabilidad de UCS** — muestra 7 (ρ=2,63) da 296,9 y muestra 6 (ρ=2,64) da 69,0.

### B.7 — Recalcular traslape

Con Bht incorporada, recalcular la matriz de traslape entre todas las unidades y **reemplazar el resultado previo**. Usando la dispersión observada (64,5–296,9), Bht se traslapa con todas las demás unidades incluido el Albitófiro (274,3–304,9). Usando la banda de confianza (100–145), el panorama es distinto. **Reportar ambas** y explicar la diferencia — es material directo para la memoria.

---

---


# PARTE VI — P2 · Sondajes

## P2 — SONDAJES
#### Parser, desurvey y selección de pozos
**Modelo sugerido:** Sonnet con pensamiento extendido.

### Objetivo

Incorporar los sondajes con testigo como fuente de verdad independiente, y resolver la selección de qué pozos son relevantes para un conjunto dado de caserones.

### Tarea 2.1 — Lector de los seis CSV

Mapeo tolerante de nombres de columna: distintas minas usan `azimuth_utm` o `azimuth`, y algunas agregan `subunidad`. El lector debe aceptar variantes sin fallar.

Convertir el centinela `-999` a nulo en todos los campos numéricos. Normalizar códigos de estructura (mayúsculas y sinónimos: `V` y `vet` son lo mismo) contra el registro de alias de P1.

### Tarea 2.2 — Desurvey por curvatura mínima

Los pozos no son rectos. Implementación validada contra los 11 pozos MPC:

```python
def desurvey(collar_ENZ, surveys):
    """surveys: lista ordenada de (depth, azimuth, dip). dip negativo hacia abajo.
       Devuelve lista de (depth, Este, Norte, Cota)."""
    E, N, Z = collar_ENZ
    pts = [(0.0, E, N, Z)]
    for i in range(len(surveys) - 1):
        d1, a1, i1 = surveys[i]
        d2, a2, i2 = surveys[i + 1]
        md = d2 - d1
        if md <= 0:
            continue
        I1, A1 = math.radians(90 + i1), math.radians(a1)
        I2, A2 = math.radians(90 + i2), math.radians(a2)
        cb = math.cos(I2 - I1) - math.sin(I1) * math.sin(I2) * (1 - math.cos(A2 - A1))
        cb = max(-1.0, min(1.0, cb))
        b = math.acos(cb)
        rf = 1.0 if b < 1e-9 else 2 / b * math.tan(b / 2)   # factor de razón
        dN = md / 2 * (math.sin(I1)*math.cos(A1) + math.sin(I2)*math.cos(A2)) * rf
        dE = md / 2 * (math.sin(I1)*math.sin(A1) + math.sin(I2)*math.sin(A2)) * rf
        dZ = md / 2 * (math.cos(I1) + math.cos(I2)) * rf
        E += dE; N += dN; Z -= dZ
        pts.append((d2, E, N, Z))
    return pts
```

Más una función de interpolación lineal que devuelva la posición a una profundidad arbitraria, necesaria para ubicar tramos de litología, estructura y geomecánica.

*Criterio de aceptación:* los 11 pozos MPC deben desurveyarse sin excepción, y la banda sur debe reproducir 6 pozos, 1.102,4 m de litología y 148 estructuras en el rango de cota 263–359.

### Tarea 2.3 — Contactos derivados

La tabla de estructuras casi no registra contactos. Derivarlos de los **límites entre tramos consecutivos de la tabla de litología**, marcándolos con un tipo distinto (`contacto_derivado`) para no confundirlos con estructuras logueadas.

Estos contactos serán las etiquetas del discriminador fractura-contacto en una sesión posterior. Aquí solo hay que generarlos y almacenarlos.

### Tarea 2.4 — Intersección traza-malla en tres estados

Los sondajes se cargan **después** de las capas DXF. Usar la maquinaria existente de `points_in_mesh` con rayo vertical.

| estado | criterio | por defecto |
|---|---|---|
| **Intersecta** | algún punto de la traza cae dentro de alguna malla | seleccionado |
| **Cercano** | no intersecta, pero pasa a menos de una distancia configurable | no seleccionado, mostrando la distancia |
| **Lejano** | fuera de rango | no seleccionado |

Los pozos cercanos importan: aunque no toquen el caserón, siguen siendo útiles para la interpolación al modelo de bloques.

### Tarea 2.5 — Métricas por pozo

Junto a cada pozo de la lista, mostrar lo necesario para decidir sin abrirlo:

- metros de traza dentro de mallas
- qué unidades atraviesa y cuántos metros de cada una
- número de estructuras registradas
- RQD y RMR medianos del tramo intersectado
- distancia mínima a la malla más cercana (si no intersecta)

Un pozo que intersecta 2 m probablemente no sirve, y sin este dato se seleccionaría igual.

### Tarea 2.6 — Interfaz

Lista de pozos con casillas, ordenable por cualquier métrica, con el estado indicado visualmente y posibilidad de anulación manual en ambos sentidos. La selección debe persistir en el estado de la aplicación.

---

---


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


# PARTE IX — Sesión C · Concordancia

## SESIÓN C — Concordancia
**Modelo sugerido:** Opus, pensamiento extendido alto.
**Requiere:** P2 (sondajes) y Sesión E completadas, más al menos dos caserones cargados.

### C.0 — Encuadre

Esto es **análisis de concordancia, no validación**. La malla de Leapfrog **no es verdad terreno**: es una interpolación construida a partir de los sondajes, casi exacta junto al sondaje porque está restringida ahí, e hipótesis progresivamente más débil al alejarse.

Un desacuerdo entre MWD y malla **no es un error del MWD** hasta que se demuestre cuál de los dos falla.

Terminología obligatoria en interfaz, exportaciones y memoria: **"modelo geológico informado por MWD"**. Nunca "corregido", nunca "exacto".

### C.1 — Guardia de circularidad

**Bloqueante.** Si el modelo se entrena con etiquetas derivadas de la malla, comparar sus predicciones contra esa misma malla solo demuestra memorización.

El sistema debe **rechazar** todo reporte de concordancia que compare predicciones contra la misma malla que produjo las etiquetas de entrenamiento, e indicar por qué.

Comparaciones admitidas:

1. **Contra registros de sondaje** — fuente independiente del entrenamiento.
2. **Contra la malla del caserón excluido** — el modelo nunca vio la malla de 1541.

### C.2 — Dos niveles de contraste

**Nivel 1 — donde sondaje y MWD están colocalizados.** Único lugar con algo próximo a verdad terreno. Comparar la predicción MWD contra el logueo de testigo directamente. Extensión limitada, valor probatorio alto.

**Nivel 2 — donde solo existe la malla.** Se reporta concordancia y se analiza la estructura espacial del desacuerdo. **Nunca se llama "error" al desacuerdo.**

### C.3 — El diagnóstico principal

**Concordancia en función de la distancia al sondaje más cercano.** Graficar y reportar la pendiente.

| resultado | interpretación |
|---|---|
| Alta cerca, **decae** al alejarse | La malla se degrada lejos del dato y el MWD aporta información donde la interpolación ya no la tiene. **Mejor resultado posible**: valida el MWD y cuantifica el alcance útil de la malla. |
| Plana con la distancia | La malla es tan buena lejos como cerca; el MWD no agrega nada. |
| **Baja cerca** de los sondajes | El problema es del modelo: ahí la malla está anclada al dato duro y no puede estar equivocada. |

### C.4 — Estructura espacial del desacuerdo

Clasificar cada punto discordante por su **distancia al borde de malla más cercano**:

- A uno o dos metros de un borde → precisión de interpolación, esperable.
- En el interior macizo de un cuerpo → problema real, hay que investigarlo.

Reportar el histograma. La distinción separa "la malla está corrida" de "el modelo está mal".

### C.5 — Desfase de contactos

Para cada contacto que predice la malla, medir el desfase δ hasta la firma detectada por el MWD.

- δ con **sesgo sistemático** → la malla está desplazada, y δ cuantifica cuánto.
- δ **simétrico con dispersión** → ruido de interpolación.

Ese δ es el margen operacional de la función de anticipación: recomendar bajar PP N metros antes del contacto previsto. Reportar media, mediana, desviación y sesgo.

### C.6 — Matriz de confusión

Entre litología predicha por MWD y litología de la fuente de contraste, por unidad. Reportar concordancia global, por unidad, y los pares que más se confunden entre sí.

Cruzar con B.7: las unidades cuyas bandas de UCS se traslapan deberían ser las que más se confunden. Si se confunden unidades de bandas bien separadas, hay algo más ocurriendo.

### C.7 — Salidas

- Reporte exportable con todos los gráficos y tablas anteriores
- Tabla de concordancia por caserón y por unidad
- Listado de zonas de desacuerdo interior, con coordenadas, para revisión de geología

---

---


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


# ANEXO — Bloque común de convenciones (versión larga)

## BLOQUE COMÚN
#### (pegar al inicio de cada sesión)

Estás colaborando en el desarrollo de **MWD GeoMech Wizard**, plataforma Python/Dash de archivo único (~3.300 líneas, pensada para ejecutarse en Colab) que constituye la herramienta de una memoria de título de Ingeniería Civil en Minas (USACH), desarrollada en convenio con Pucobre.

La plataforma lee datos MWD en formato IREDES XML provenientes de equipos **Epiroc Simba E70S con sistema COPROD**, los cruza contra modelos litológicos y estructurales 3D en DXF, y aplica Machine Learning para caracterizar geomecánicamente el macizo rocoso. Método de explotación: Sub Level Stoping, mina subterránea de cobre.

### Convenciones inmutables — NO modificar bajo ninguna circunstancia

**Orden canónico de campos en etiquetas Val (IREDES):**
```
LT | PR (ROP) | PP | FP (Feed = Avance) | DP | RP | FLP (Flush)
```

**TMatrix del archivo DQ:** fila 0 → Norte, fila 1 → Este, fila 2 → Cota.

**Ejes DXF:** X = Este, Y = Norte, Z = Cota.

**Ray casting:** el rayo en `points_in_mesh` es **VERTICAL (0,0,1)**. El grid XY de aceleración solo es válido con rayo vertical. Cambiar la dirección del rayo sin rehacer el grid produjo en su momento una caída de exactitud de 82,4% a 7,1%.

**Test canario innegociable:** pozo H5 contra `Metandesitas.dxf` debe dar **exactamente 1437 de 1743 puntos dentro (82,4%)**. Este test es de *geometría*, no de geología: se conserva como test de regresión aunque sus datos sean de otra mina. Si falla, algo se rompió.

**Índice de Discontinuidades (DI):** ventana de 14 muestras (≈26 cm), pesos PP=0,35 · DP=0,25 · FP=0,20 · RP=0,20, umbral 1,5. Metodología de Fernández et al. 2023 (doi:10.1016/j.ijmst.2023.02.004). El autor de esa publicación es el profesor guía de la memoria.

**Proxy de energía específica:**
```
SE_reacción = (P_percusión + P_rotación + P_avance) / ROP
```
Está **explícitamente distinguido** de la formulación de Teale (1965). Los parámetros MWD son *presiones de reacción hidráulica*, no valores impuestos. Esta distinción debe preservarse en todo comentario y documentación.

**Límites físicos de UCS:** mínimo 0, máximo **450 MPa**. Sin truncamiento silencioso jamás.

**Rango de presión de percusión (PP):** 90 a 230 bar. **PP es la única variable manipulada por el operador.** El sistema se separa en modelo de *caracterización* (roca ← MWD, con PP como covariable de contexto) y modelo de *prescripción* (desempeño ← dominio y PP, con PP como variable de decisión).

**Validación cruzada:** GroupKFold agrupado por pozo para evitar fuga de datos. Cuando existan varios caserones, validación dejando-un-caserón-fuera (LOCO-CV).

### Prohibiciones de diseño

- **Nunca usar coordenadas (X, Y, Z, cota) como variables predictoras** del modelo de caracterización. El yacimiento es estratiforme y la cota es casi un proxy directo de la litología; el modelo tomaría ese atajo y dejaría de leer el MWD. Si se quiere evaluar, hágase como *ablación explícita* comparando desempeño dentro del caserón contra desempeño LOCO.
- **Nunca un default silencioso.** Todo dato faltante se declara faltante y bloquea o advierte. Los dos bugs más graves del proyecto fueron defaults silenciosos.
- **Nunca mezclar sitios.** Un archivo de trabajo = una mina.
- **Nunca RMR como parámetro del modelo.** Fue removido deliberadamente por no ser físicamente objetivo.

### Alcance actual: solo Punta del Cobre (MPC)

Se descartó todo dato de Mina Granate. La memoria se enfoca exclusivamente en Punta del Cobre.

**Envolvente UTM de los sondajes MPC:**
```
Este   376.521 – 377.005
Norte  6.958.752 – 6.959.323
```
Mina Granate está a ~3,05 km del centroide de MPC. Cualquier objeto cargado a esa distancia es de otra mina.

**Composición de los 11 sondajes MPC** (campo `unidad` = Unidad Litológica):

| código | metros | % | significado |
|---|---|---|---|
| Kfa | 1.176,3 | 66% | Albitófiro |
| Bht | 576,9 | 33% | Brecha Hidrotermal |
| Kpcli | 20,8 | 1,2% | Lavas Inferiores |
| DL | 3,1 | 0,2% | sin identificar |

**Reparto espacial** (tercios geométricos norte-sur sobre la nube de sondajes):

| banda | pozos | m litología | estructuras | cota |
|---|---|---|---|---|
| Norte | 5 | 674,5 | 35 | 264 – 418 |
| Centro | 0 | 0 | 0 | — |
| **Sur** | **6** | **1.102,4** | **148** | **263 – 359** |

El sector objetivo de la memoria es el **Sur**, por su densidad de estructuras (que son las etiquetas del discriminador fractura-contacto).

**Caracterización de macizo por unidad** (derivada de los sondajes):

| unidad | RQD mediana | RMR mediana | densidad media |
|---|---|---|---|
| Kfa | 77,7 | 71,0 | 2,79 |
| Bht | 92,0 | 71,0 | 2,97 (máx 4,09) |

Bht **no es una brecha débil**: tiene mejor RQD que el Albitófiro y es más densa, coherente con una brecha mineralizada bien cementada (magnetita/sulfuros).

**Ensayos de laboratorio disponibles** — Karzulovic & Asoc. Ltda., "Evaluación Geotécnica Caserones Mina Punta del Cobre", Tabla 3.2 (roca intacta):

| unidad | UCS mín | UCS máx | media | SD | CV | mi | E medio (GPa) | Poisson | γ (t/m³) |
|---|---|---|---|---|---|---|---|---|---|
| Albitófiro | 274,3 | 304,9 | 289,6 | — | — | 11,3 | 71,6 | 0,15 | 2,85 |
| Brecha mixta | 82,6 | 141,7 | 111,5 | 23,6 | 0,212 | 7,6 | 17,3 | 0,20 | 2,80 |
| Brecha sedimentaria | 77,4 | 98,7 | 83,6 | 8,6 | 0,103 | 19,1 | 12,8 | 0,22 | 2,76 |
| Lutitas normales | 117,1 | 134,9 | 126,0 | 12,6 | 0,100 | 15,8 | 16,4 | 0,28 | 2,45 |
| Lutitas metamorfoseadas | 186,8 | 221,8 | 204,3 | 24,8 | 0,121 | 20,8 | 89,0 | 0,115 | 2,50 |

El Albitófiro carece de desviación estándar, lo que sugiere una única probeta. Se acepta el valor, pero **el registro debe conservar esa limitación y el intervalo de predicción debe ensancharse en consecuencia**.

**Etiqueta de entrenamiento del modelo de UCS:** valores de **ensayo de laboratorio (roca intacta)**, no las bandas operacionales del Excel geomecánico. La justificación es de coherencia interna: el modelo ya excluye del entrenamiento los puntos con DI sobre el umbral, es decir, entrena solo con tramos sin discontinuidad — la misma condición que mide el ensayo uniaxial. El Excel se conserva únicamente para verificación de consistencia de bandas.

**Hueco conocido:** Bht (33% del metraje) no tiene UCS de laboratorio. Está en gestión con geología. El sistema debe manejarlo como *estado declarado*, no como bloqueo del desarrollo.

### Esquema de los archivos de sondaje

Seis CSV, separador `;`, terminación CRLF, codificación latin-1, clave `holeid`, valor centinela `-999`.

```
MPC_header.csv      holeid ; x_utm ; y_utm ; z_utm ; length
MPC_survey.csv      holeid ; depth ; azimuth_utm ; dip ; equipo_desviacion
MPC_lithology.csv   holeid ; from ; to ; unidad
MPC_structure.csv   holeid ; from ; to ; structure
MPC_geomec.csv      holeid ; from ; to ; RQD ; RMR
MPC_density.csv     holeid ; from ; to ; <densidad>
```

Los dips son negativos (hacia abajo). Los pozos **no son rectos**: requieren desurvey.

Códigos de estructura observados: `ZFR` zona fracturada · `FRI` fractura interna · `FM` falla menor · `V`/`vet` veta · `ZF` zona de falla · `FI` falla interna · `SD` zona de cizalle · `Cto` contacto. **Todas cuentan como discontinuidad mecánica.** Requieren normalización de mayúsculas y sinónimos. Los contactos casi no están registrados como estructura: hay que derivarlos de los límites de la tabla de litología.

---

---
