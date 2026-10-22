# Verificación memoria ↔ código

Cotejo de la memoria (versión `Memoria_de_título_Luciano_San_martin_2210.pdf`, 89 pp.)
contra el código de la rama `claude/geomech-platform-pucobre-co64dv` y contra los
datos cargados de los cuatro caserones. Cada cifra marcada como «medido» se
obtuvo cargando los cuatro caserones el 2026-10-22; no viene de memoria ni de
reportes anteriores.

Se responde por número: «1: convención», «2: aplicar», etc.

---

## A. Decisiones que cambian las cifras de las figuras

Hay que resolverlas antes de regenerar las imágenes finales: cada una cambia los
números de los resultados.

| # | La tesis dice | El código hace (medido) | Qué decidir |
|---|---|---|---|
| **A1** | 6.2: «se decide continuar el proyecto con 5 metros de radio» → pesos calibrados de la Tabla 6.2 (PP 0,01 · RP 0,04 · DP 0,55 · FP 0,31) | La variante activa es la **convención** (PP 0,35 · DP 0,25 · FLP 0,20 · RP 0,20). Las cifras 845.550 / 136.870 de la sección 6.1 se reproducen **exactamente** con la convención, no con los pesos calibrados. El texto y los números dicen cosas distintas | ¿Qué DI entra a la evaluación: la **convención** o la **calibrada a 5 m**? La calibrada tiene ρ de validación −0,127 en la propia Tabla 6.2 |
| **A2** | 5.2.2: «se excluyeron sistemáticamente los primeros 2 metros de cada barreno» | En las corridas por script de esta ronda **no se aplicó**: el corte de emboquillado solo se ejecuta desde el Paso 2 de la interfaz. Quedaron dentro **86.785 puntos** con largo < 2 m. Afecta a todo lo calculado en la ronda: R² +0,306 / −3,02, `F_RF_detalle` y `F_RF_esquema`. El embudo, además, rotula la etapa como «emboquillado <2 m» aunque no se haya aplicado | Aplicarlo (recomendado; es lo que declara la tesis) y corregir el rótulo del embudo para que diga si el corte corrió o no |
| **A3** | Resumen, 6.1 y Conclusiones: el RF se entrenó sobre **845.550** puntos (86,1%) | 845.550 es solo DI ≤ 1 sobre los 982.420 puntos, sin ningún filtro. El conjunto real de entrenamiento es **772.184** con emboquillado 2 m + percusión de empate 0,20 + continuidad (convención), y **832.800** sin emboquillado | Reemplazar por la cifra del embudo que resulte de A1 y A2. La tesis debería mostrar el embudo completo, etapa por etapa |
| **A4** | 6.2: «umbral vigente de 0,25, se eliminó 12.786 muestras (1,3%)». 5.2.2 describe el filtro como «PP o avance nulas o inconsistentes» | Umbral **0,20** → **14.738** muestras (1,5%), según tu decisión. El filtro marca una muestra que cae ≥ 20% bajo el promedio de sus dos vecinas, **con las vecinas parecidas entre sí** (la menor ≥ 90% del promedio, es decir, la mitad del umbral). No mira el avance ni valores nulos | Actualizar 6.2 a 0,20 / 14.738 / 1,5%. Reescribir 5.2.2. La Tabla 6.1 dice «entre 0,20 y 0,75» pero llega a 0,80 |
| **A5** | No aparece en ningún capítulo | El **filtro de continuidad** está activo: excluye **5.989** puntos cuya ventana del DI cruza un salto de registro > 2,95 cm | Agregarlo a 4.2.2 y 5.2.2 como tercer filtro |
| **A6** | 3.6.1 y 4.4.1: el RF «predice promediando las salidas de sus árboles» | Producción usa la **mediana** (p50) de los 200 árboles. La validación la midió de las dos formas: promedio R² +0,308 (pozo) / −2,182 (caserón); mediana +0,306 / −3,02 (sin emboquillado, ver A2). La tesis reporta −2,492 / −2,5, que **no coincide con ninguna** | ¿Se reporta con mediana (lo que usa la herramienta) o con promedio? Corregir 3.6.1 y 4.4.1 en cualquiera de los dos casos |
| **A7** | «LOOCV» significa **dos** esquemas distintos: dejar un **caserón** fuera (3.6.2, 4.4.2, 6.7: R² −2,492) y dejar una **litología** fuera (Resumen «estimando una litología oculta», Fig. 6.4 RMSE 57,1 / 61,5, Fig. 6.5 Spearman +0,586 / +0,581 / +0,228) | Son dos funciones distintas: `LeaveOneGroupOut` por caserón y `leave_one_lithology_out` (la «vara común», que mide el error en MPa) | Darle a cada uno su nombre. Propuesta: «LOOCV por caserón» y «validación dejando una litología fuera». Las cifras de las Fig. 6.4/6.5 se calcularon antes de los filtros actuales y hay que regenerarlas |
| **A8** | Fig. 6.8: cinco algoritmos con partición **70/15/15** por tiro, MLP incluido. 4.4.2 dice lo contrario: cuatro modelos, todos con GroupKFold, y redes neuronales excluidas | En el código **no existe ninguna partición 70/15/15**. `model_comparison_report` compara Lineal, KNN (k=7), RF, HistGB (profundidad 6) y MLP (32,16) «de control», todos con GroupKFold de 5 pliegues por pozo y submuestreo de 60.000 puntos | La Fig. 6.8 no se puede reproducir con el código actual. Regenerarla con GroupKFold y alinear 4.4.2 y 6.3 |
| **A9** | 4.2.1, Ec. 4.1: cada muestra se interpola con t = largo / largo_máximo | Cada punto se ubica a su **profundidad real medida** sobre la dirección collar→fondo. La interpolación normalizada se eliminó (sesión S1) porque **estiraba** 20 pozos hasta 1,65 m | Reescribir 4.2.1 con el método vigente |
| **A10** | Lavas por caserón (Tabla 4.1.3, Anexo B): Kpcls solo en PCC_1541. 6.4: «en PCC_1541 la litología predominante son las lavas inferiores» | El vocabulario asigna `Lavas_1541` → **Kpcls (60 MPa)** y `LAVA_1059` → **Kpcli (180 MPa)**. Cota medida: las lavas de **PCC_1541** tienen mediana 307 m (**94,1% bajo 320**) y las de **PCS_1059**, mediana 402 m (59% sobre 400). Con la regla estratigráfica que se usaba antes (inferiores bajo ~320, superiores sobre ~400), las dos asignaciones quedan **invertidas**. PCC_1541 está en el mismo nivel que PCC_0042, cuyas lavas (mediana 288 m) son Kpcli | Confirmar la asignación de lavas por malla. Afecta la etiqueta de 96.865 puntos (PCC_1541) y de 143.082 (PCS_1059). El propio texto de 6.4 apoya Kpcli para PCC_1541. Detalle llamativo: la Tabla 6.3 muestra el grupo Kpcls con UCS ML de 129 MPa sobre una etiqueta de 60 |
| **A11** | Agrupación de dominios: 4.5 usa tolerancia de DI ±0,5; 6.6 dice «intervalos de 1 punto» | `compute_domain_groups(tol_ucs=20, tol_di=0,15, tramo=2 m)`; la interfaz también parte en 0,15. No forma intervalos fijos: asigna cada tramo al primer grupo que cumple las dos tolerancias | ¿Qué tolerancia de DI generó la Tabla 6.3? Fijar una y que 4.5, 5.2.5 y 6.6 digan lo mismo |

---

## B. Vocabulario y siglas

| # | En la tesis | En el código / la norma | Propuesta |
|---|---|---|---|
| **B1** | PEP aparece con **tres** nombres: «Presión Específica de **Percusión**» (Resumen, Ec. 3.3, 4.4.1, 4.7, 6.3, 6.6), «de **Penetración**» (Lim. 2, 3.4, 5.2.5) y «de **perforación**» (4.7, 6.3). El índice de figuras rotula las Fig. 6.7 y 6.15 como «Energía específica» | **Presión específica de penetración**, según tu corrección | Unificar en las tres variantes y en los rótulos de figura |
| **B2** | Unidad de PEP en Ec. 3.3: [bar·m/min] | PEP = bar ÷ (m/min) = **bar·min/m** | Corregir la unidad |
| **B3** | Barrido = **FP** (3.3, 4.1.2, Tablas 6.2 y 6.4) | IREDES: **FP = Feed Pressure (avance)**, **FLP = Flushing (barrido)**. El código y las figuras dicen FLP | Cambiar FP → **FLP** en la tesis. Con «FP» un evaluador que conozca IREDES leerá «avance» |
| **B4** | El barrido se llama «presión de flujo», «flujo de barrido», «barrido o flushing» y «P° Flujo» | — | Un solo nombre: «presión de barrido (FLP)» |
| **B5** | 5.2.3: el DI usa **RP, AP, DP y PP** (avance dentro, barrido fuera) | El DI usa PP, DP, **FLP** y RP; el avance queda fuera. Coincide con 3.5 y 6.7 | Corregir 5.2.3 |
| **B6** | Variables del RF: 6.3 dice **6** (5 presiones + ROP); 4.4.1 dice ROP + PEP + 5 presiones = **7** | **7**: ROP, PP, AP, DP, RP, FLP, PEP | Corregir 6.3. Revisar además la frase de 4.4.1 «PEP que el algoritmo logra clasificarla para evitar ruido por correlaciones»: no describe nada que el código haga |
| **B7** | Frontera del DI: Resumen «DI < 1,0», 6.1 «inferior al umbral», 6.3 «DI ≥ 1» fracturado, 4.4.1 «DI ≤ umbral» | Intacta = **DI ≤ 1**; fracturada = DI > 1 | Usar ≤ y > en todo el texto |
| **B8** | Anexo B: ids `Kpcsb_sed`, `Lutitas_n`, `Lutitas metamorf`; 9 entradas | Ids reales `Kpcsb_sedimentaria`, `Lutitas_normales`, `Lutitas_metamorfoseadas`. El vocabulario tiene **25** atributos: faltan `Kpcsb_basal` y `Kpcs` (unidades padre), `Ka` / `Ka_caliza` / `Ka_arenisca`, `DL`, `Fk` (alteración) y las 9 estructuras | Usar los ids exactos. Si el anexo se presenta como «registro de vocabulario», debería estar completo o declarar que es un extracto. `Fk` merece aparecer por la colisión Fk ↔ Kfa |
| **B9** | Fuente de las anclas: Kpcli, Kpcls y Bht_feldk = «Dato de terreno / campaña Pucobre»; Bht = «ensayo de campaña» | Vocabulario: Kpcli, Kpcls y Bht_feldk = **«autor de la memoria»** (Kpcls sin ensayo). Bht = Hoek-Brown ajustado sobre 25 ensayos (BRECHA_2.XLS, 2022) + carga puntual n=16 (CAS1004S), dispersión 64,5–296,9 MPa, CV 0,57 | Alinear la fuente. Es lo primero que se pregunta en una defensa sobre una etiqueta de entrenamiento |
| **B10** | Presencia por caserón (Tabla 4.1.3 / Anexo B): Kpcli en PCC_0042, PCC_1541, PCS_1059; Brecha mixta en PCS_1043 y PCS_1059 | Medido: **Kpcli en PCC_0042, PCS_1043, PCS_1059** (no en PCC_1541); **Brecha mixta solo en PCS_1043**. Bht y Kpcls coinciden | Corregir (depende de A10) |
| **B11** | «Albitófiros» | `Albitófiro` | Menor |
| **B12** | Terminología del proyecto («modelo geológico informado por MWD», nunca «corregido» ni «exacto»): 5.2.1 «calce exacto»; 6.4 «validación de exactitud» | — | Revisar esas dos frases |

---

## C. Afirmaciones de método que el código no hace así

| # | La tesis dice | El código hace |
|---|---|---|
| **C1** | 3.5: los pesos se eligen con el índice de similitud S_T (Ec. 3.5, de Fernández). 6.2: un «Simplex» que mantiene «al menos el 20% del tramo sobre el umbral». 4.3: el de mayor Spearman | Lo de 4.3 es lo correcto: 400 vectores de Dirichlet + la convención (401), semilla 42; maximiza ρ de Spearman entre el RQD_MWD (regla de Deere de 0,10 m sobre DI ≤ umbral) y el RQD del sondaje; valida dejando un sondaje fuera. **S_T y el criterio del 20% no están implementados.** Los pesos suman 1; no van «entre 0 y 100» |
| **C2** | 4.8: se valida el DI con el «DI medio por caserón» contra el RQD, en un Spearman entre caserones | El apareamiento es **uno a uno**: cada intervalo de RQD con el punto MWD más cercano dentro del radio, y el RQD_MWD medido sobre el tramo de ese pozo |
| **C3** | 3.4, 3.4.2 y 4.8: el RQD es una «fuente independiente» para contrastar el DI | El RQD **calibra** los pesos, así que no es independiente para validarlos. Solo el pliegue dejando un sondaje fuera lo es |
| **C4** | 6.4: 49,4% «cuando el RQD tiene un radio de ±5 m». 6.7: 49,4% «en un radio de 3 m» | 6.7 es lo correcto: es la tolerancia de 3 m al cruce de malla. Recordatorio: ese 49,4% es **precisión** y queda al nivel del azar (~52% del largo de los pozos está a menos de 3 m de algún cruce de malla). Picos con DI > 1 en PCC_1541: la tesis dice 1.115; el cálculo con umbral 1,0 y fusión de 0,5 m da **1.811** |
| **C5** | 6.2: r(PP, DP) = 0,55 < 0,6, «no será necesario aplicar el filtro» | Sobre los **perfiles de varianza**, que son las entradas reales del DI, r(PP, DP) = **0,673 > 0,6**, y RP–PP = 0,54. El argumento se cae si se mide donde corresponde |
| **C6** | 4.7: el dominio debe reunir «al menos cinco tramos». 6.6: el CV de PEP se evalúa «por estratos de PP» | Un segmento = ≥ 5 **muestras** consecutivas (~10 cm) del mismo grupo, entrenables, con DI ≤ umbral y PEP < 800. Se exige pozo ≥ 20 m ✓. `top_drilling` **no estratifica por PP**; `pep.control_pp` = `directo` |
| **C7** | 3.3: el espaciamiento «fluctúa entre 0,5 y 3,2 cm» | Medido: mínimo 0,5 · p1 1,4 · mediana 2,0 · media 2,06 · p99 2,3 · **máximo 1.053 cm** (vacíos de registro). Además existe un modo de registro cada 10 cm (1.737 intervalos) |
| **C8** | 6.2 y Conclusiones: «11 sondajes con RQD» | 11 sondajes en el header, **10 con RQD** |
| **C9** | 6.3: «las muestras efectivas fueron solamente 5» | Entrenan **4** etiquetas: Kpcli 180 · Bht 128,1 · Kpcls 60 · Brecha mixta 111,5. Kfa y Brecha sedimentaria no tienen puntos MWD |

---

## D. Parámetros que el código usa y la tesis no declara

Conviene agregarlos a 4.4.1 / 5.2 para que la herramienta sea reproducible desde
el texto:

- **Random Forest**: 200 árboles · profundidad máxima 8 · min_samples_split 6 ·
  min_samples_leaf 3 · max_features √p · random_state 42. Predicción = mediana
  de los árboles; banda P10–P90 ensanchada por `pi_factor` según la calidad del
  ancla y acotada a 0–450 MPa.
- **Importancia por permutación**: semilla 42, 20.000 puntos, medida sobre el
  30% de los pozos apartados del ajuste.
- **ROP mínima física** 0,2 m/min (perfil de faena): rige el análisis PEP↔UCS,
  las curvas de PP y la relación directa. No rige el RF.
- **Techo de PEP**: < 800 en el ranking Top-5; ≤ 1.000 en los reportes por pozo.
- **PP**: 90–230 bar; **UCS**: 0–450 MPa.
- **Estadística de la etiqueta**: `ucs.estadistica_ml = auto` (central si existe,
  si no la media).
- **Calibración del DI**: mínimo 30 puntos por intervalo de RQD y mínimo
  2 sondajes para validar.

## E. Lo que sí coincide (verificado)

Ventana del DI de 14 muestras ≈ 28 cm · sensibilidad con ventanas de 10, 14 y 20 ·
umbral del DI 1,0 · DI estandarizado por pozo (valor cuadrático medio 1) ·
rayo vertical (0,0,1) · 400 vectores de Dirichlet + convención, semilla 42 ·
GroupKFold de 5 pliegues por pozo · LOOCV por caserón con 4 iteraciones ·
largo de barra 1,756 m · picos fusionados a < 0,5 m · ajuste de plano con ≥ 3
pozos · Top-5 con pozo ≥ 20 m y tres criterios (máx. ROP, mín. PEP, mín. CV de
PEP) · bloques de 2,5 m · tramo de dominio de 2 m y tolerancia de UCS ±20 MPa ·
bandas de UCS de las 9 litologías de la Tabla 4.1.3 idénticas al vocabulario ·
928 pozos y 982.420 registros.

## F. Fuera del código, para tu revisión

- `CLAUDE.md` todavía dice umbral 1,5, ventana «~26 cm», «SE_reacción» y
  «LOCO-CV». Contradice la tesis y el código actuales.
- Numeración de figuras y ecuaciones desalineada entre el índice y el texto
  (Ec. 3.5 y Ec. 4.1 repetidas; el índice llama 6.4 a la figura que el texto
  llama 6.3). Hay marcadores «¡Error! Marcador no definido» en el índice.
