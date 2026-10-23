# Kit de resultados — Capítulo 5

*modelo geológico informado por MWD.*

Generado 2026-08-26 06:31. 19 de 22 ítem(s) producidos; 3 no se pudieron generar y se listan igual, con su motivo.

## Procedencia

- **capas**: {'PCC_1541:Lavas', 'PCC_1541:Bht', 'PCS_1043:Lavas', 'PCS_1043:Bht', 'PCS_1043:Kpcmix', 'PCC_0042:Bht'}
- **caserones**: {'PCC_1541', 'PCS_1043', 'PCC_0042'}


## 5.1 Vocabulario y bandas de UCS

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.1 | Registro de vocabulario y bandas de UCS | tabla | `T5_1_registro_de_vocabulario_y_bandas_de_ucs.csv` | ✅ |
| T5.2 | Matriz de traslape de bandas de UCS (ambos criterios) | tabla | `T5_2_matriz_de_traslape_de_bandas_de_ucs_ambos_criterios.csv` | ✅ |

## 5.2 Datos y escala

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.3 | Composición del conjunto de entrenamiento | tabla | `T5_3_composicion_del_conjunto_de_entrenamiento.csv` | ✅ |
| F5.1 | Vista 3D de pozos y mallas | figura | `F5_1_vista_3d_de_pozos_y_mallas.html` | ✅ |

## 5.3 Índice de discontinuidad

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| F5.2 | Perfil de DI de un pozo representativo | figura | `F5_2_perfil_de_di_de_un_pozo_representativo.html` | ✅ |
| F5.3 | Sensibilidad de la ventana del DI | figura | `F5_3_sensibilidad_de_la_ventana_del_di.html` | ✅ |
| T5.4 | Validación independiente DI contra RQD de laboratorio | tabla | — | ⚠ sin_datos |
| F5.4 | DI medio contra RQD por caserón | figura | — | ⚠ sin_datos |

## 5.4 Modelo de caracterización

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.5 | Matriz de correlación entre variables MWD | tabla | `T5_5_matriz_de_correlacion_entre_variables_mwd.csv` | ✅ |
| T5.6 | Comparación de los cinco modelos | tabla | `T5_6_comparacion_de_los_cinco_modelos.csv` | ✅ |
| T5.7 | Reporte de justificación de variables | tabla | `T5_7_reporte_de_justificacion_de_variables.csv` | ✅ |
| T5.8 | Ablación de cota dentro y entre caserones | tabla | `T5_8_ablacion_de_cota_dentro_y_entre_caserones.csv` | ✅ |
| T5.9 | Validación por pozo (GroupKFold) | tabla | — | ⚠ sin_datos |

## 5.5 Concordancia con el modelo geológico

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.10 | Diagnósticos de concordancia (C.3 a C.7) | tabla | `T5_10_diagnosticos_de_concordancia_c3_a_c7.csv` | ✅ |

## 5.6 Coherencia energía específica contra UCS

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.11 | Coherencia SE contra UCS por dominio | tabla | `T5_11_coherencia_se_contra_ucs_por_dominio.csv` | ✅ |

## 5.7 Respuesta a la presión de percusión

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.12 | Curvas de respuesta a PP por dominio | tabla | `T5_12_curvas_de_respuesta_a_pp_por_dominio.csv` | ✅ |

## 5.8 Discriminación de discontinuidades

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.13 | Discriminador fractura contra contacto | tabla | `T5_13_discriminador_fractura_contra_contacto.csv` | ✅ |
| T5.14 | RQD_MWD por pozo y por caserón | tabla | `T5_14_rqd_mwd_por_pozo_y_por_caseron.csv` | ✅ |

## 5.9 Modelo de bloques

| Id | Título | Tipo | Archivo | Estado |
|---|---|---|---|---|
| T5.15 | Modelo de bloques: X, Y, Z, tamaño, UCS, DI, confianza | tabla | `T5_15_modelo_de_bloques_x_y_z_tamano_ucs_di_confianza.csv` | ✅ |
| T5.16 | Resumen del modelo de bloques por banda ISRM | tabla | `T5_16_resumen_del_modelo_de_bloques_por_banda_isrm.csv` | ✅ |
| T5.17 | Predicciones punto a punto | tabla | `T5_17_predicciones_punto_a_punto.csv` | ✅ |
| D5.1 | Modelo de bloques en DXF con capas por banda | dxf | `D5_1_modelo_de_bloques_en_dxf_con_capas_por_banda.dxf` | ✅ |

## Ítems no generados

- **T5.4** Validación independiente DI contra RQD de laboratorio — Ningún caserón reúne RQD de laboratorio del Excel geomecánico y puntos MWD suficientes: sin las dos fuentes no hay contraste independiente que hacer.
- **F5.4** DI medio contra RQD por caserón — Ningún caserón reúne RQD de laboratorio y puntos MWD suficientes para el contraste independiente.
- **T5.9** Validación por pozo (GroupKFold) — No se corrió la validación multipozo de posición de mallas: sin resultados no hay detalle por pozo.

## Notas de formato

- **F5.1** — PNG no disponible (ValueError); se exportó HTML interactivo. Instalar kaleido para obtener PNG. 73 MB: pesado para adjuntar. Un HTML interactivo embebe toda la geometría de las mallas. Instalar kaleido produce el PNG, mucho más liviano, sin cambiar la figura.
- **F5.2** — PNG no disponible (ValueError); se exportó HTML interactivo. Instalar kaleido para obtener PNG.
- **F5.3** — PNG no disponible (ValueError); se exportó HTML interactivo. Instalar kaleido para obtener PNG.
- **T5.17** — 156 MB: pesado para adjuntar. Un HTML interactivo embebe toda la geometría de las mallas. Instalar kaleido produce el PNG, mucho más liviano, sin cambiar la figura.
