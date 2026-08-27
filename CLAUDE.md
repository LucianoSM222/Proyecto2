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

`explorar_repositorio(ruta)` recorre una carpeta y clasifica DXF, DQ, MW y CSV
de sondaje por caserón, con `repo.patron_caseron`. `guardar_proyecto_en(ruta)`
escribe el .gwz a disco: el guardado siempre funcionó, lo que falla es la
descarga del navegador con archivos de decenas de MB.

## Perfil de faena

Los parámetros de operación viven en `param_registry` (42 en diez secciones),
no en el código: `get_param` / `set_param` / `reset_param`, con validación y
procedencia declarada. `export_site_profile()` e `import_site_profile()` en
JSON es lo que recibe una faena nueva. Seis parámetros están PROTEGIDOS —la
ventana, el umbral y los cuatro pesos del DI— y rechazan la escritura.

Para calibrar el DI se crea una VARIANTE (`create_di_variant`), nunca se toca
la de convención. Fernández busca sus pesos con `movvar`: calibrar es su
método, no una desviación.

## Suite de tests

`python3 -m pytest -q` en la raíz. Las suites que dependen de fixtures no
versionados se OMITEN, no fallan (`test_support.py`). Verde = 0 fallidas.
