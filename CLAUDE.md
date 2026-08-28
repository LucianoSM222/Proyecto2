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

## Litologías y anclas de UCS

Aportadas por el autor y confirmadas contra el registro:

| Atributo | UCS central | Banda | Nota |
|---|---|---|---|
| `Bht` | 128,1 | disp. 64,5-296,9 | CV 0,57 |
| `Bht_feldk` | 155 | 130-180 | litología PROPIA, no Bht con alteración |
| `Kpcli` (Lavas Inferiores) | 180 | 150-230 | |
| `Kpcls` (Lavas Superiores) | — | — | SIN ancla: no hay ensayo |
| `Brecha_mixta` (Kpcmix) | 111,5 | 82,6-141,7 | sd 23,6 |
| `Kpcsb_sedimentaria` | 83,6 | 77,4-98,7 | |
| `Ka_caliza` / `Ka_arenisca` | 60 / 120 | — | sin puntos MWD hoy |
| `Dique` (DQ1) | — | — | rol estructura |

LAS DOS LAVAS SE SEPARAN POR COTA, no por nombre: Pucobre entrega ambas como
«Lavas»/«LAVA». Inferiores bajo `lito.cota_lavas_inferiores` (320), superiores
sobre `lito.cota_lavas_superiores` (400). Una malla en la franja intermedia
queda SIN atributo y sin ancla — es el caso de PCS_1043, 35 m sobre el techo de
las inferiores. Es la regla del geólogo, criterio trazable, no un percentil.

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

## Estado de ejecución

Mantener al día. Evita releer la hoja de ruta completa para saber dónde vamos.

| # | Sesión | Spec | Estado |
|---|---|---|---|
| 0 | Preparación del repositorio | — | ✅ |
| 1 | P1 Fundaciones | `docs/P1_fundaciones.md` | ✅ `ff8f6d5` |
| 1b | Adenda A · roles y composición | `docs/P1b_roles_composicion.md` | ✅ `01253e0` |
| 1c | Adenda B · registro de Bht | `docs/P1c_adendaB_bht.md` | ✅ |
| 2 | P2 Sondajes | `docs/P2_sondajes.md` | ✅ `5307a61` |
| 3 | P3 Correcciones de uso | `docs/P3_correcciones.md` | ✅ `19cee91` |
| 4 | E Escala | `docs/E_escala.md` | ✅ |
| 5 | Entrenamiento y LOCO-CV | (prompt en la hoja de ruta) | 🟡 entrenado sobre 3 caserones; LOCO-CV R²<0 → no generaliza entre caserones |
| 6 | C Concordancia | `docs/C_concordancia.md` | ✅ `b835888` |
| 6b | Coherencia SE↔UCS (alcance redefinido) | — | ✅ `0c8a7b1` |
| 7 | Curvas PP y prescripción | (prompt en la hoja de ruta) | ✅ `b6753c2` |
| 8 | Discriminador fractura/contacto | (prompt en la hoja de ruta) | 🟡 `6664435` implementado; contra sondajes 104/217 = azar |
| 9 | Modelo de bloques IDW | (prompt en la hoja de ruta) | ✅ `6664435` |
| 10 | Kit del Capítulo 5 | (prompt en la hoja de ruta) | ✅ 19/22 ítems |
| P5 | Filtro del plano del abanico | — | ✅ `929a132` |
| PF | Perfil de faena configurable | — | ✅ `47e273b` |
| P1-2 | Variantes del DI · RQD propagado | — | ✅ `ee8d3c5` |
| P3 | Calibración de pesos contra RQD | — | ✅ `4ced6b6` |
| S1 | Geometría de carga (estiramiento, traslape) | — | ✅ `5804ec9` |
| S2 | RQD uno a uno · todas las presiones candidatas | — | ✅ `f2a15c8` |
| S3 | UCS de fuente única · estadística elegible | — | ✅ `01c6689` |
| S4 | Fuera Excel calibrador y geomecánico | — | ✅ `16653fa` |
| S5 | Sondajes en 3D · menú de selección | — | ✅ `764a7be` |
| S6 | Árbol por caserón y abanico | — | ✅ `a53b8c6` |
| S7 | Carpeta-repositorio · guardado a disco | — | ✅ `fdbfeb3` |
| A1 | DI activo · el panel no pisa la convención | — | ✅ `a6a64ce` |
| A2 | Fuera defaults silenciosos y kit duplicado | — | ✅ `bd974c7` |
| A3 | Universalidad · 64 parámetros y pantalla de perfil | — | ✅ `05aee77` |
| A4 | Vara común UCS · relación directa · valor por punto | — | ✅ `0e12e18` |
| A5 | Radio del RQD elegible · anclas reales de MPC | — | ✅ `38622e7` |
| A6 | `on_xml` restaurado · la carga de MWD estaba muerta | — | ✅ `a48abc3` |
| A7 | Menús del perfil · badge cacheado · canario despierto | — | ✅ `3eccdb4` |
| A8 | UCS por banda · SE no física fuera | — | ✅ `2e5da9f` |
| A9 | Cuatro caserones completos · Lavas por cota | — | ✅ |
| B1 | Cierre · las ventanas no saltan solas · se elige modelo | — | ✅ `b178c7a` |
| B2 | Soporte a tronadura · sólido por DI y por UCS | — | ✅ |
| B3 | Centro de reportes · se abre el que se pida | — | ✅ |
| B4 | Pantalla de calibración · siglas cruzadas · un solo lugar | — | ✅ |
| B5 | Velocidad de la interfaz · medida, no estimada | — | ✅ |
| B6 | SE sin estratificar · reporte de semillas | — | ✅ |

Hallazgos que condicionan la interpretación, no defectos pendientes:

- LOCO-CV R² < 0: el modelo no transfiere entre caserones. La ablación de
  cota lo confirma (dentro +0,177 sin cota / +0,413 con cota; LOCO −2,117 /
  −4,108): agregar cota duplica el R² dentro y duplica la caída fuera.
- SE↔UCS: ρ(UCS, ROP) = +1,00 dentro de cada estrato de PP. El MWD tiene
  señal física consistente; lo que no calza son las bandas de UCS asignadas.
  Bht y Kpcli son indistinguibles en MWD pese a 62 MPa nominales de
  diferencia.
- Discriminador fractura/contacto: 47,9% de acierto contra etiquetas de
  sondaje a 10 m, que es el azar entre dos clases. 57,6% de los picos quedan
  indeterminados, con el motivo declarado uno por uno. Descontando los picos
  que son plano de abanico sube a 50,8%: sigue siendo el azar.
- UN ABANICO DE TIROS ES UN PLANO. De 33 grupos de picos, 18 se explican por
  la geometría de perforación (841 picos, 18,3%). Los tres grupos mayores
  —590, 533 y 478 picos— tienen 0,5°, 0,0° y 0,5° entre su normal y la del
  abanico. No hay ninguna estructura discreta identificable hoy.
- El RQD de sondaje solo alcanza a PCC_0042: los 10 sondajes con RQD están
  todos junto a ese caserón, y PCS_1043 y PCC_1541 quedan en 0% a cualquier
  radio. Cualquier calibración es "calibrada en PCC_0042".
- GEOMETRÍA DE CARGA, dos defectos que invalidaban posiciones: los puntos se
  colocaban por parámetro normalizado y un registro que no llegaba al fondo se
  ESTIRABA sobre todo el tiro (20 pozos, hasta 1,65 m sobre tiros de 35 m); y
  los pozos sin DQ coherente iban al centro global, dejando 16 apilados sobre
  la misma vertical. Corregidos: cada punto va a su profundidad real y un pozo
  sin posición se descarta declarando el motivo.
- El RQD se aparea UNO A UNO: cada centro medido con el punto MWD más cercano,
  y el RQD_MWD se mide sobre el tramo de ese pozo con el largo del intervalo.
- Las CINCO presiones son candidatas del DI, incluida la de avance: qué
  presión sobra lo decide la calibración, no un descarte previo.
- El testigo NO es un contraste independiente: es el patrón que ajusta los
  pesos. di_quality_indicator() mide el apartamiento en PUNTOS DE RQD, y su
  veredicto separa ORDENAR bien los sectores de MEDIR bien el RQD.
- Calibración DI↔RQD: los pesos NO se estabilizan. A 5 y 10 m domina el
  dámper (0,65 y 0,82 contra el 0,25 de la convención); a 25 m domina el
  barrido (0,49) con el dámper en 0,10. El rho de validación es -0,21 (5 m),
  +0,12 (10 m) y +0,17 (25 m), con pliegues que van de -0,21 a +0,83. Con
  cuatro o cinco sondajes la calibración no puede asentarse. La restricción
  que manda es la cantidad de sondajes con RQD, no la elección de pesos.

Hoja de ruta, prompts por sesión y criterio de modelo: `docs/roadmap_ejecucion.md`.
Documento maestro completo (respaldo): `docs/MWD_GeoMech_Documento_Maestro.md`.

## Fuentes de datos

UNA sola fuente de UCS: el registro de atributos. La capa ya no lleva `ucs_lab`
y el Excel geomecánico salió del programa, junto con el Excel calibrador y el
paso de "calibración de unidades" que colgaba de él. Qué estadística alimenta
el modelo se elige en `ucs.estadistica_ml`: `auto` (cadena histórica, defecto),
`central`, `media`, `mediana`, `rango_medio` o `rango_vs_se`.

`rango_vs_se` proyecta la banda min-max sobre el rango de SE observado y da una
etiqueta POR PUNTO, atacando el problema de fondo —tres etiquetas para 400.000
registros—. Induce circularidad con SE: ese modo lo declara y excluye SE de las
predictoras.

## Cómo se resume la SE de una litología

`se.control_pp` = `directo` (defecto) o `por_estrato`. Decisión del autor, con
su razón: SE_reacción = (PP + RP + AP) / ROP **ya lleva ROP en el
denominador**, así que la percusión entra CONTRASTADA contra la velocidad. Si
subir PP consigue subir ROP, la SE se normaliza y sigue hablando de la roca; si
la SE no se mueve pese a más PP, es porque la roca resiste esa percusión, que
también es hablar de la roca. En los dos casos el número describe el macizo y
no la decisión del operador, así que estratificar sobra.

`_se_representativa()` y `_se_escala_lito()` obedecen ese modo, y
`_nota_control_pp()` viaja pegado a la procedencia de todo modelo que dependa
de ello: el número cambia según el modo y leerlo sin saber cuál corrió sería
leer un dato sin procedencia.

LO QUE NO CAMBIA: `se_ucs_coherence_report()` sigue reportando `estratos_pp`
pase lo que pase. Ahí estratificar es la PRUEBA de que la relación no es
artefacto del operador, no el método de estimación. Sacar la evidencia junto
con el procedimiento habría sido perder el argumento que sostiene la decisión.

`explorar_repositorio(ruta)` recorre una carpeta y clasifica DXF, DQ, MW y CSV
de sondaje por caserón, con `repo.patron_caseron`. `guardar_proyecto_en(ruta)`
escribe el .gwz a disco: el guardado siempre funcionó, lo que falla es la
descarga del navegador con archivos de decenas de MB.

## Pantallas de salida

Dos botones en la barra, y ninguno calcula nada hasta que se lo pide:

- 💥 **tronadura** (`_tronadura_panel_body`, `build_bloques_figure`,
  `tronadura_resumen`): el sólido coloreado por DI —dónde está quebrada— y por
  UCS —qué tan competente—. Un bloque SIN soporte de datos no se pinta de un
  color intermedio: queda fuera del sólido. Lleva su advertencia de qué NO es:
  aproximación de apoyo, no modelo geológico validado.
- 📄 **reportes** (`REPORTES`, `reportes_disponibles`, `generar_reporte`): los
  diez reportes en un listado. Armar la lista NO corre ninguno —solo mira si
  hay con qué— y el que hoy no puede correr dice qué falta. `reportes_nuevos()`
  avisa cuáles se habilitaron desde la última vez que se abrió el panel; se
  calcula al abrirlo, nunca en un badge de la barra: un recorrido de todos los
  puntos en cada refresco es exactamente la lentitud que este panel viene a
  sacar (el badge de vocabulario costaba 561 ms por refresco antes de cachearlo).

`ml_seed_sensitivity()` corre la misma vara con varias semillas y compara la
dispersión contra la distancia entre competidores: si la semilla mueve el MAE
más que lo que separa al primero del segundo, el orden lo decidió qué filas
tocaron y no el método. Los deterministas —línea base, relación, banda— se
corren UNA vez y declaran que su cero es por construcción, no por estables.

## Velocidad

Se mide, no se estima. Cronometrado con 1.050.000 puntos en 600 pozos, que es
el orden de los cuatro caserones:

| | antes | ahora | qué era |
|---|---|---|---|
| Paso 4 | 9.367 ms | 1.157 ms | el embudo armaba la matriz de entrenamiento entera —X, y, groups— para mostrar nueve números, y `_step4` materializaba un millón de puntos en una lista que no leía |
| Paso 1 | 1.062 ms | 1 ms (2ª visita) | `conteo_puntos_con_ucs()` cachea el total y los con banda contra la firma de puntos MÁS la de dominios |
| Paso 3 | 663 ms | 318 ms | recorre el generador en vez de materializar |
| Vista 3D | 1.157 ms | 713 ms | cada pozo declaraba SU barra de color (600 barras idénticas apiladas) y cada collar era su propia traza |

`_training_funnel(..., solo_conteos=True)` da los mismos conteos sin la matriz;
NO borra la procedencia (`_prov_capas`/`_prov_caserones`/`_prov_ucs`), porque un
pase de conteos que la limpiara dejaría muda a la guardia de circularidad.
`test_embudo_conteos.py` compara etapa por etapa contra el pase completo.

Lo que NO se cacheó: `training_composition_report()` sigue costando ~1,1 s por
visita al Paso 4. Depende de `p.entrenable` y `p.di`, que se mutan en sitio sin
que ninguna firma barata los capte; un embudo desactualizado explicaría mal el
N del modelo, y eso es peor que esperar un segundo.

## Perfil de faena

Los parámetros de operación viven en `param_registry` (62 en diecinueve
secciones), no en el código: `get_param` / `set_param` / `reset_param`, con
validación y procedencia declarada. Se editan desde la PANTALLA del perfil
(botón ⚙ de la barra, `_perfil_panel_body`), no solo desde código;
`aplicar_perfil_desde_panel` escribe por lote y un valor rechazado no bloquea
los demás. `export_site_profile()` e `import_site_profile()` en JSON es lo que
recibe una faena nueva. Hoy NINGUNO está protegido; el mecanismo
(`ParametroProtegido`) sigue disponible para la faena que quiera congelar algo.

Un parámetro del perfil NUNCA se usa como valor por defecto de argumento
(`def f(r=RADIO)`): Python los congela al importar y el número dejaría de
seguir al perfil. Se resuelve en el cuerpo. `test_universalidad.py` recorre el
AST y falla si vuelve a aparecer.

El DI que corre es una VARIANTE ACTIVA: `di_activo()` la nombra y `activar_di`
es la única puerta que escribe `di_config`/`di_threshold`. Cambiar parámetros
en el panel crea o reusa una variante (`aplicar_di_config`); la convención de
Fernández nunca se toca. Fernández busca sus pesos con `movvar`: calibrar es
su método, no una desviación.

Los SEIS del DI —ventana, umbral y cuatro pesos— NO son parámetros del perfil.
Estuvieron en el registro y eran un control que no controlaba: la pantalla
aceptaba el número, lo daba por aplicado, y el DI seguía con los suyos.
Además se pedían dos veces, en el perfil y en el Paso 3. Se escriben en un
solo lugar —el Paso 3, o `calibrate_di_weights` contra el testigo— y el menú
de Fracturamiento los MUESTRA en vivo (`_di_vigente_body`), solo lectura.

Las siglas de las presiones estaban cruzadas en la pantalla: en IREDES `FP` es
Feed Pressure —el AVANCE, que el código guarda en `pa`— y `FLP` es el BARRIDO,
que guarda en `pf`. El panel del DI rotulaba la entrada de `pf` como "FP". El
número nunca cambió; el rótulo sí. `CAL_ETIQUETAS` es el nombre completo de
cada una y se usa en todas las pantallas.

## Suite de tests

`python3 -m pytest -q` en la raíz. Las suites que dependen de fixtures no
versionados se OMITEN, no fallan (`test_support.py`). Verde = 0 fallidas.
