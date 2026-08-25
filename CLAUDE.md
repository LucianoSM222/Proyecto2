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
| 5 | Entrenamiento y LOCO-CV | (prompt en la hoja de ruta) | ⬜ requiere caserones cargados |
| 6 | C Concordancia | `docs/C_concordancia.md` | ⬜ |
| 7 | Curvas PP y prescripción | (prompt en la hoja de ruta) | ⬜ |
| 8 | Discriminador fractura/contacto | (prompt en la hoja de ruta) | ⬜ |
| 9 | Modelo de bloques IDW | (prompt en la hoja de ruta) | ⬜ |
| 10 | Kit del Capítulo 5 | (prompt en la hoja de ruta) | ⬜ |

Hoja de ruta, prompts por sesión y criterio de modelo: `docs/roadmap_ejecucion.md`.
Documento maestro completo (respaldo): `docs/MWD_GeoMech_Documento_Maestro.md`.

## Suite de tests

`python3 -m pytest -q` en la raíz. Las suites que dependen de fixtures no
versionados se OMITEN, no fallan (`test_support.py`). Verde = 0 fallidas.
