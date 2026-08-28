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

Fuente ÚNICA desde el 2026-08-28: `test_data/vocabulario_MPC_20260828_1302.json`
(exportado por el autor desde la app, schema `mwd-geomech-vocabulario`).
`cargar_caserones.py` lo importa con `import_vocabulary()` al arrancar —
YA NO siembra la tabla de Karzulovic hardcodeada en `seed_attribute_registry()`—
así que estos números pueden diferir de versiones anteriores de este documento:
son los que el autor refinó trabajando con datos reales, no una primera pasada.

| Atributo | UCS central | Banda | CV | Fuente / nota |
|---|---|---|---|---|
| `Kfa` (Albitófiro) | 289,6 (media) | 274,3-304,9 | — | Karzulovic 2005 T3.2. 66% del metraje de sondaje (1.176,3 m). Sin sd → probeta única, intervalo ensanchado |
| `Bht` | 128,1 | disp. 64,5-296,9 | 0,57 | Hoek-Brown s/25 ensayos + carga puntual n=16 (CAS1004S). 33% del metraje (576,9 m). RQD mediana 92,0. CV excede lo que la etiqueta puede resolver — se declara, no se oculta ensanchando la banda |
| `Bht_feldk` | 155 | 130-180 | — | litología PROPIA, no Bht con alteración — decisión del autor |
| `Kpcli` (Lavas Inferiores) | 180 | 150-230 | — | cota <~320. Confirmado: Lavas de PCC_1541 93,4% bajo 320 (=Kpcli); Lavas de PCS_1043 99,6% entre 320-400 (=Kpcls) |
| `Kpcls` (Lavas Superiores) | 60 | 40-95 | — | SIN ensayo — ancla aportada por el autor, no de laboratorio. Cota >~400 |
| `Ka` (Calizas Fm. Abundancia) | 80 | 60-140 | — | dos niveles con resistencia distinta, ver subunidades |
| `Ka_caliza` | 60 | — | — | subunidad de `Ka` |
| `Ka_arenisca` | 120 | — | — | subunidad de `Ka`, ~20 m de espesor. Descripción del autor llegó parcialmente ilegible: pendiente de confirmar |
| `Kpcsb_basal` (Brecha basal) | — | — | — | unidad PADRE, sin ancla propia — `Kpcsb` es ambiguo en la literatura (Marschik=basal, Ortiz et al.=sedimentaria); se distinguen con ids explícitos |
| `Brecha_mixta` | 111,5 | 82,6-141,7 | 0,212 | subunidad de `Kpcsb_basal`. Karzulovic 2005 T3.2 |
| `Kpcsb_sedimentaria` | 83,6 | 77,4-98,7 | 0,103 | subunidad de `Kpcsb_basal`. Karzulovic 2005 T3.2 |
| `Kpcs` (Miembro Trinidad) | — | — | — | unidad padre de las lutitas, sin ancla propia |
| `Lutitas_normales` | 126,0 | 117,1-134,9 | 0,100 | subunidad de `Kpcs`. Karzulovic 2005 T3.2 |
| `Lutitas_metamorfoseadas` | 204,3 | 186,8-221,8 | 0,121 | subunidad de `Kpcs`. Karzulovic 2005 T3.2 |
| `DL` | — | — | — | código sin identificar en sondajes, 0,2% del metraje (3,1 m) |

Estructuras (rol `estructura`, sin banda de UCS): `FM` Falla menor · `FI` Falla
interna · `ZF` Zona de falla · `ZFR` Zona fracturada · `FRI` Fractura interna ·
`SD` Zona de cizalle · `V` Veta · `Dique` · `Cto` Contacto.

COLISIÓN DE NOMENCLATURA `Fk` ↔ `Kfa`: `Fk` es feldespato potásica
(ALTERACIÓN); `Kfa` es Albitófiro (LITOLOGÍA). Strings casi invertidos con
roles OPUESTOS — estuvo a punto de invalidar el 66% del metraje de sondaje
MPC. El campo `rol` de `Attribute` existe en buena medida por este caso: un
traslape entre los dos es COMPOSICIÓN (roles distintos), no conflicto.

LAS DOS LAVAS SE SEPARAN A MANO, por capa, en el vocabulario — no por una
regla automática. Pucobre entrega ambas como «Lavas»/«LAVA», con el mismo
nombre de malla, así que la resolución por nombre no las distingue; hubo una
regla por cota (inferiores bajo 320, superiores sobre 400) y el autor pidió
sacarla: diferenciar cuál malla es cuál es conocimiento de quien configura la
faena, no un umbral que el programa adivine. `set_layer_attributes` asigna la
litología POR CAPA (por objeto `Layer`, no por texto del nombre), así que dos
mallas de nombre idéntico pueden llevar litologías distintas igual, elegidas
a mano en el árbol de vocabulario. El vocabulario final trae el alias
`dxf_layer` exacto por malla (`Lavas_1043`→`Kpcli`, `Lavas_1541`→`Kpcls`,
`LAVA_1059`→`Kpcli`), así que en la carga por lote ya no hace falta elegir
nada a mano: la elección ya está en el JSON, hecha por el autor.

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

Medido sobre la carga final (2026-08-28), no estimado:

| Caserón | Pozos | Puntos MWD |
|---|---|---|
| PCC_0042 | 436 | 479.316 |
| PCC_1541 | 237 | 202.827 |
| PCS_1043 | 125 | 157.195 |
| PCS_1059 | 130 | 143.082 |
| **Total** | **928** | **982.420** |

38 mallas DXF (litología + estructura) en los cuatro caserones. Cero puntos
sin litología, cero ambiguos, en el cruce geométrico completo.

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
| C1 | Tres constantes de vuelta desde el perfil (Deere, visor, parseo) | — | ✅ |
| C2 | Guardar/Cargar proyecto responden de verdad | — | ✅ |
| C3 | SE≥1000 fuera del reporte por pozo (ROP≈0, lavado del bit) | — | ✅ |
| C4 | Calibración antes del cálculo · transfiere a las casillas · avance en P3-3.7 | — | ✅ |
| C5 | `min_puntos` de RQD, control que no controlaba | — | ✅ |
| C6 | Visor 3D: mallas recortadas a la vista, 52→13 MB por caserón | — | ✅ |
| C7 | KeyError en r2_train con el modelo Banda | — | ✅ |
| C8 | Aviso de tronadura dinámico · fuente de UCS · exportar DXF con atributos | — | ✅ |
| D1 | Pestaña Geometría del perfil: slug ASCII · secciones ya no se esfuman | — | ✅ |
| D2 | Lavas: cota automática fuera, asignación manual por capa en vocabulario | — | ✅ |
| D3 | Golpe de barra: filtro local (cae y se recupera) para el Paso 2 | — | ✅ |
| D4 | Tronadura por UCS de matriz: deja de mezclarse con la UCS cruda | — | ✅ |
| D5 | Visor: ocultar en el árbol aliviana la traza, no solo la esconde | — | ✅ |
| D6 | Persistencia: caserón y error de asignación viajan en el .gwz | — | ✅ |
| D7 | Calibración del DI: la propuesta ya no se borra sola al redibujar | — | ✅ |
| D8 | Siglas cruzadas otra vez: `di_config_summary` decía FP por FLP y omitía el avance | — | ✅ |
| D9 | Reportes dibujados (no JSON crudo) y descarga en PNG | — | ✅ |

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
- EL VISOR "SE ATRAPA" — causa raíz encontrada, no arreglada. `app.run()`
  corre el servidor de desarrollo de Flask SIN `threaded=True`: atiende UNA
  sola petición HTTP a la vez. Cada acción de la interfaz dispara una cadena
  de ~10 callbacks encadenados (badges, árbol de capas, figura 3D, etc.), así
  que si uno tarda —cargar un proyecto, reclasificar, armar la vista 3D—
  TODOS los demás, incluido un simple clic en "Siguiente →", quedan en cola
  detrás. Medido en vivo (navegador real vía Playwright) sobre un proyecto
  chico de prueba (125 pozos, 157.195 puntos): un clic tardó **5 s** en
  responder. Con los datasets reales del proyecto (cuatro caserones, más de
  un millón de puntos) esto es sustancialmente peor — es la "trampa" que se
  reportó.

  NO es un arreglo de una línea. Se probó `threaded=True` para permitir
  peticiones concurrentes, y **crashea de verdad**, dos veces reproducido:
  `RuntimeError: dictionary changed size during iteration` en
  `_step2()` → `all_points()` → `for w in wells.values()`, porque un
  callback todavía está ESCRIBIENDO en `wells` (la carga del proyecto,
  agregando pozos uno a uno) mientras OTRO callback, en un hilo distinto, ya
  está LEYENDO el mismo diccionario para dibujar el paso siguiente. `wells`,
  `layers`, `domains` y el resto del estado global no tienen ningún candado.

  El arreglo correcto no es un candado global —eso solo devolvería el
  problema del principio, porque casi todo callback toca ese estado, así que
  serializar todo con un lock es indistinguible de no tener hilos—, sino
  mover las operaciones PESADAS Y SÍNCRONAS (cargar un .gwz, cargar DXF/XML)
  al MISMO patrón de hilo de fondo + `dcc.Interval` de sondeo que ya usa el
  entrenamiento ML (`task_lock`, `task_state`, `run_ml_task`): así el
  callback que atiende el clic del usuario vuelve de inmediato, sin bloquear
  el único hilo del servidor, y las demás peticiones no hacen cola detrás de
  una carga larga. Es una decisión de arquitectura, no una corrección
  puntual — se dejó documentada en vez de aplicada a medias.
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

### Datos de trabajo de la tesis (2026-08-28, final)

`test_data/` quedó reducido a exactamente lo que se usa: `reales/` (los cuatro
caserones) más los dos JSON de configuración exportados por el autor. Todo lo
anterior —datos de Mina Granate/SAN_7064 (OTRA mina), Excel geomecánico viejo,
fixtures sintéticas de sesiones tempranas, zips duplicados— se BORRÓ, a
pedido explícito del autor: "los datos con los que trabajaremos en la tesis
serán solo los que te subí, los demás bórralos todos".

- `test_data/reales/Capas {caseron}/*.dxf` — mallas, PLANAS (sin subcarpeta
  "Litología"/"Estructuras": el rol de cada malla ya no se adivina por
  carpeta, lo resuelve el vocabulario).
- `test_data/reales/MWD {SITIO} {número}/{DQ|MW}*.xml` — DQ y MW mezclados en
  la misma carpeta por caserón (antes: `{sitio}/CP*/DQ/` separado).
- `test_data/reales/MPC Sondajes/MPC_*.csv` — los 6 CSV de sondaje (header,
  survey, lithology, structure, geomec, density), reubicados desde la raíz de
  `test_data/`.
- `test_data/vocabulario_MPC_20260828_1302.json` — 25 atributos + 96 alias,
  incluido uno `dxf_layer` EXACTO por cada malla de los cuatro caserones (ver
  tabla de anclas arriba). `cargar_caserones.py` lo importa con
  `import_vocabulary()` al arrancar; YA NO siembra la tabla de Karzulovic
  hardcodeada de `seed_attribute_registry()`.
- `test_data/perfil_faena_MPC_20260828_1236.json` — 58 parámetros de
  operación, importado con `import_site_profile()`.

`cargar_caserones.py` quedó ajustado a esta estructura (`_carpeta_mwd()`,
`VOCABULARIO`, `PERFIL`). Probado extremo a extremo sobre los cuatro
caserones: 928 pozos, 982.420 puntos, **cero** puntos sin litología, cero
ambiguos en el cruce geométrico.

Efecto en la suite: `test_p2_sondajes.py` apuntaba a la ruta vieja de los CSV
de sondaje — corregido a la nueva. El resto de los tests que dependían de las
fixtures borradas (Mina Granate, sintéticas) pasan a SKIP, no a fallo, por el
mecanismo ya existente en `test_support.py` (`require_real_data`).

## Pantallas de salida

Dos botones en la barra, y ninguno calcula nada hasta que se lo pide:

- 💥 **tronadura** (`_tronadura_panel_body`, `build_bloques_figure`,
  `tronadura_resumen`): el sólido coloreado por DI —dónde está quebrada— y por
  UCS —qué tan competente—. Un bloque SIN soporte de datos no se pinta de un
  color intermedio: queda fuera del sólido. Lleva su advertencia de qué NO es:
  aproximación de apoyo, no modelo geológico validado.

  La advertencia sobre el DI es DINÁMICA (`_tronadura_advertencia_di`), no un
  texto fijo: antes decía siempre "el DI no está calibrado en puntos de RQD",
  pero el sólido se pinta con `p.di`, que sale de la variante REALMENTE
  activa. Con una variante calibrada activa esa frase quedaba falsa —el aviso
  decía una cosa, los pesos que coloreaban el sólido decían otra—. Ahora
  nombra la variante activa y, si es calibrada, trae su veredicto de
  validación real.

  `tronadura_ucs_fuente()` / `set_tronadura_ucs_fuente()` eligen entre la UCS
  de matriz y la cruda (`ucs_matriz` / `ucs_ml`) para colorear el sólido. Qué
  MODELO corrió —banda, relación, ml— se sigue decidiendo en el Paso 4; esto
  elige cuál de sus dos salidas se usa acá.

  `exportar_bloques_dxf()` saca el sólido como .dxf: un punto por bloque en
  Este/Norte/Cota, con XDATA (appid `MWD_GEOMECH`) llevando UCS_MPA, DI,
  LITOLOGIA, CONFIANZA, BANDA y CASERON. Un bloque sin soporte no se exporta,
  igual que no se dibuja.

  LO QUE QUEDA ABIERTO: que el sólido interpolado por IDW no capte una falla
  que el DI puntual sí capta es un problema de RESOLUCIÓN del modelo de
  bloques —el radio de búsqueda promedia sobre una estructura delgada—, no de
  qué variante de DI corre. No se tocó en esta pasada; requiere investigar
  con los datos reales cuánto hay que apretar `bloques.radio_h_m`/`radio_v_m`
  antes de que valga la pena, o si hace falta una vista de puntos crudos
  aparte de la interpolada.
- 📄 **reportes** (`REPORTES`, `reportes_disponibles`, `generar_reporte`): los
  diez reportes en un listado. Armar la lista NO corre ninguno —solo mira si
  hay con qué— y el que hoy no puede correr dice qué falta. `reportes_nuevos()`
  avisa cuáles se habilitaron desde la última vez que se abrió el panel; se
  calcula al abrirlo, nunca en un badge de la barra: un recorrido de todos los
  puntos en cada refresco es exactamente la lentitud que este panel viene a
  sacar (el badge de vocabulario costaba 561 ms por refresco antes de cachearlo).

  El reporte se DIBUJA: tarjetas para las cifras, tablas para los registros,
  párrafos para las notas. Antes era `json.dumps()` dentro de un `html.Pre` —se
  veía como código fuente, que no sirve ni para leer un resultado ni para pegar
  en la memoria—. `_reporte_secciones()` parte el reporte en secciones
  dibujables y alimenta LAS DOS salidas, la pantalla y la imagen, para que no
  puedan discrepar. Un recorte de filas (`REPORTE_MAX_FILAS`) se declara con su
  total real, y en la imagen un valor que no cabe se corta con «…» visible:
  `go.Table` recorta en silencio y desde el PNG no habría forma de saberlo.

  `reporte_imagen()` baja el reporte como **PNG**, y la elección se midió sobre
  el reporte de perfil en vez de suponerse: png 138.778 B contra jpeg 127.286 B
  a la misma escala. El JPEG es un 9% más liviano —una tabla no tiene gradientes
  que aproveche— y ese 9% se paga emborronando los dígitos, que es lo único que
  el reporte contiene. `scale=1` sí importa: a este cuerpo de letra el texto ya
  sale nítido y `scale=2` pesaba 2,6 veces más sin verse mejor. Si no hay con
  qué producir la imagen (kaleido necesita un navegador) se baja el JSON y el
  aviso dice por qué, en vez de dejar al usuario sin nada.

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

Auditoría final, cronometrada sobre PCS_1043+PCC_0042 reales (601.324 puntos,
463 pozos, 17 mallas). Los tres cambios preservan el resultado EXACTO —
comprobado por huella del JSON/de los bloques y comparación valor a valor:

| | antes | ahora | qué era |
|---|---|---|---|
| Paso 1 | 1.870 ms · 2.326 ms (2ª) | 467 ms · **2 ms (2ª)** | `_diagnostico_calce()` materializaba un arreglo de un millón de filas EN CADA VISITA para mostrar seis números en un banner. `_bbox_mwd()` lo cachea contra la firma de puntos MÁS la de collares —reasignar el DQ de un pozo lo mueve sin cambiar cuántos hay— y el camino frío usa `np.fromiter` por eje |
| Vista 3D | 1.152 ms | 569 ms | Plotly VALIDA elemento por elemento toda lista de Python que recibe: `ii/jj/kk` de cada malla eran 36.000 índices por malla pasando uno a uno por el validador (896.328 llamadas a `to_scalar_or_list`). Como ndarray toma el camino rápido |
| Modelo de bloques | 41,3 s | 23,5 s | contar pozos distintos por bloque recorría un arreglo de strings en Python (10,2 s), y cada bloque en planta rearmaba `np.array(vecinos)` desde listas (6,8 s). Códigos enteros + `np.unique`, y celdas del índice convertidas a numpy UNA vez |

Lo que NO se tocó: los 22 s que quedan del modelo de bloques son el algoritmo
en sí —25 celdas de vecindario por bloque con el perfil real, no un
vecindario patológico—. Bajarlo más exige vectorizar el bucle de cota, que
cambia el orden de las sumas y con él los últimos bits de la UCS
interpolada: no vale el riesgo por un reporte que se corre una vez.

`_training_funnel(..., solo_conteos=True)` da los mismos conteos sin la matriz;
NO borra la procedencia (`_prov_capas`/`_prov_caserones`/`_prov_ucs`), porque un
pase de conteos que la limpiara dejaría muda a la guardia de circularidad.
`test_embudo_conteos.py` compara etapa por etapa contra el pase completo.

Lo que NO se cacheó: `training_composition_report()` sigue costando ~1,1 s por
visita al Paso 4. Depende de `p.entrenable` y `p.di`, que se mutan en sitio sin
que ninguna firma barata los capte; un embudo desactualizado explicaría mal el
N del modelo, y eso es peor que esperar un segundo.

## Perfil de faena

Los parámetros de operación viven en `param_registry` (59 en diecinueve
secciones), no en el código: `get_param` / `set_param` / `reset_param`, con
validación y procedencia declarada. Se editan desde la PANTALLA del perfil
(botón ⚙ de la barra, `_perfil_panel_body`), no solo desde código;
`aplicar_perfil_desde_panel` escribe por lote y un valor rechazado no bloquea
los demás. `export_site_profile()` e `import_site_profile()` en JSON es lo que
recibe una faena nueva. Hoy NINGUNO está protegido; el mecanismo
(`ParametroProtegido`) sigue disponible para la faena que quiera congelar algo.

No todo lo que llegó a ser parámetro merecía quedarse. Tres salieron de vuelta
a constante: `rqd.tramo_min_m` (RQD_TRAMO_MIN_M, 0,10 m) es la DEFINICIÓN de
Deere, no una elección — su propia procedencia ya decía "cambiarla deja de ser
RQD" y seguía siendo un campo editable. `visor.puntos_maximos`
(MAX_VIZ_POINTS) y `carga.presupuesto_parseo` (PARSE_BUDGET_S) decían en su
propia procedencia "depende de la máquina, no del yacimiento" y también
seguían ahí. La regla, en palabras del autor: si algo normalmente funciona
así en cualquier faena, se fija el valor y se oculta — un campo editable para
un número que nunca cambia es la misma clase de "simplificar para volver a
complicar" que ya se vio con los seis parámetros del DI.

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

Y VOLVIERON A CRUZARSE, porque la sigla se escribía en dos lugares:
`di_config_summary()` rotulaba `pf` como "FP" y **omitía `pa` por completo**,
así que de las cinco presiones declaraba cuatro, una con la sigla de otra. Esa
línea encabeza el panel del Paso 3 Y se antepone a cada CSV exportado como
procedencia, de modo que el error viajaba en los datos, no solo en la pantalla.
La sigla ahora se escribe UNA vez, en `CAL_SIGLAS`, y `CAL_ETIQUETAS` se arma
desde ella. El cálculo nunca estuvo mal: `di_profile` siempre integró `pf` con
su peso 0,20 — lo que faltaba era decirlo bien.

La calibración tampoco "guardaba" sus pesos, y la causa era de Dash: escribía
los pesos en las casillas Y subía `refresh` en el mismo retorno; `render_wizard`
escucha `refresh`, así que `_step3()` se redibujaba y recreaba los `dbc.Input`
con `value=di_config[...]` —los de la variante ACTIVA, que calibrar no toca a
propósito—, borrando el resultado en el mismo ciclo en que aparecía. La
propuesta vive ahora en `_di_panel_pendiente` y el panel la lee con
`_di_panel_valor()`; sigue sin activar nada, y aplicar o restaurar la descartan.

## Suite de tests

`python3 -m pytest -q` en la raíz. Las suites que dependen de fixtures no
versionados se OMITEN, no fallan (`test_support.py`). Verde = 0 fallidas.

`test_nombres_definidos.py` pasa pyflakes sobre TODOS los .py y falla si
alguno usa un nombre que no existe. Python resuelve nombres al ejecutar, no al
importar: una llamada a una función borrada importa sin quejarse y solo
revienta cuando alguien pasa por esa línea. Así murieron `on_xml` (carga de
MWD entera) y `apply_layer_band` (asignar caserón a una capa), las dos en el
commit que sacó el Excel geomecánico, y así quedaron tres tests fantasma en el
runner de `test_geomech.py` —bajo pytest ese bloque no corre, de modo que la
suite seguía verde mintiendo—. Requiere `pip install pyflakes`; sin él la
suite se OMITE en vez de pasar.
