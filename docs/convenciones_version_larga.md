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
