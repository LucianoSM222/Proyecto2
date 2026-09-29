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


