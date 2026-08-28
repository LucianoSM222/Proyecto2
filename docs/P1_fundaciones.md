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


