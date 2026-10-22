# Resultados finales para la memoria (2026-10-22)

Todas las cifras salen de una sola corrida (`memoria_final/final/final_calc.py`
→ `final.json`), con una configuración única. Las figuras están en
`figuras/finales/` y se regeneran con `final_figs.py`, `rf_figura.py`,
`rf_esquema.py` y `di_estructura.py`.

## Configuración

| Elemento | Valor |
|---|---|
| Emboquillado | primeros 2 m fuera (86.785 registros) |
| Rango físico de PP | 90–230 bar (12.103 registros más) — **nuevo, ver nota 1** |
| Percusión de empate | caída ≥ 0,25 respecto de las dos vecinas, vecinas a ≤ 12,5% entre sí (8.911 más) |
| Continuidad del registro | salto > 2,95 cm dentro de la ventana (5.162 más) |
| Total no entrenable por limpieza | 112.961 (11,5%) |
| DI | ventana 14 (≈ 28 cm), umbral 1,0, PP · RP · DP · FP (sin avance) |
| Pesos del DI (calibrados a 5 m) | **PP 0,02 · RP 0,48 · DP 0,04 · FP 0,46** |
| Random Forest | 200 árboles · profundidad 8 · min_samples_split 6 · min_samples_leaf 3 · max_features √p · semilla 42 |
| Agregación | **mediana** de los 200 árboles (predicción y todas las métricas) |
| Siglas | FP = flujo, AP = avance (Pucobre) · PEP = presión específica de penetración |

## Notas que cambian la lectura

1. **Rango físico de PP (nuevo).** Apareció al revisar el ranking: el criterio
   de mínima PEP elegía tramos con PP de 2 a 7 bar y ROP de 7 a 10 m/min, es
   decir, la sarta avanzando sin percutir. Había 13.086 registros entrenables
   con PP < 90 bar, que explicaban 7.035 de los 7.168 registros con
   ROP > 3 m/min. El rango 90–230 bar ya estaba declarado en el perfil de
   faena, pero ningún filtro lo aplicaba. Se aplicó con tu criterio de no
   entrenar con datos sin sentido físico. Se puede retirar si no lo quieres.
2. **Los pesos a 5 m cambiaron otra vez.** Con la limpieza final quedan en
   RP 0,48 y FP 0,46, con el dámper en 0,04. La tesis (6.2) justifica el
   radio de 5 m porque «le daba mayor peso» al dámper. Con los datos limpios
   eso ya no ocurre, y la validación dejando un sondaje fuera da
   ρ = −0,157: **no generaliza**. Sin el filtro de PP los pesos eran
   PP 0,12 · RP 0,17 · DP 0,27 · FP 0,43. Que cambien tanto con un filtro del
   1,2% de los datos es la inestabilidad que la tabla 6.2 ya describe.
3. **El Spearman +0,586 «estimando una litología oculta» no se reproduce.**
   En LOOCV-Litología el bosque ordena **al revés**: ρ = −0,518 por registro.
   Predice 125 MPa para Kpcli (ancla 180) y 152 MPa para Kpcls (ancla 60). Lo
   que sí sale positivo es el ρ por pozo (GroupKFold): **+0,563**, que es
   probablemente de donde vino el 0,586. La figura `F6_05b` muestra los tres
   esquemas lado a lado.
4. **La concordancia del DI con las mallas sigue en el azar.** La precisión es
   51,0% contra un azar de 53,2%.

## Cifras de la tesis y su valor final

| Dónde | Tesis dice | Valor final |
|---|---|---|
| Resumen, 6.1, Concl. | entrenado sobre 845.550 puntos (86,1%) | **776.471** registros (79,0% del total) en 902 pozos |
| 6.1 | DI ≤ 1: 845.550 · DI > 1: 136.870 | DI ≤ 1: **862.287** (87,8%) · DI > 1: **120.133** (12,2%), sobre los 982.420 |
| 6.2 | empate 0,25 → 12.786 (1,3%) | 12.786 (1,30%) sobre el total ✓; teórico por largo de barra: 11.189 |
| 6.2 | r(PP, DP) = 0,55 < 0,6 | señales: 0,555; **perfiles de varianza (entrada del DI): 0,569**; AP–DP 0,604 en señales |
| Tabla 6.2 | 34 pares a 5 m; pesos DP 0,55 · FP 0,31 | **32 pares, 4 sondajes; PP 0,02 · RP 0,48 · DP 0,04 · FP 0,46; ρ ajuste +0,126, validación −0,157** (tabla completa en `T6_02`) |
| 6.2 | 11 sondajes | 11 sondajes, **10 con RQD**; 4 alcanzan el MWD a 5 m |
| 6.3, Fig. 6.4 | RMSE línea base 57,1 / RF 61,5 | LOOCV-Litología: línea base **57,1** · RF **61,6** · relación directa **134,5** · banda **134,5** (relación y banda extrapolan en 2 de 4 pliegues) |
| 6.3, Fig. 6.5 | Spearman RF +0,586 · banda +0,581 · relación +0,228 | LOOCV-Litología por registro: RF **−0,518** · relación **−0,619**. GroupKFold por pozo: RF **+0,563** (nota 3) |
| 6.3 | muestras efectivas 5 | **4** etiquetas: Kpcli 180 (448.004) · Bht 128,1 (242.405) · Kpcls 60 (68.666) · Brecha mixta 111,5 (17.396) |
| 6.3, Fig. 6.8 | 70/15/15; solo RF positivo (+0,008 / +0,075) | GroupKFold, 5 pliegues, 58.785 registros de 71 pozos. R² prueba: **RF +0,161** · HGB +0,126 · Lineal +0,097 · MLP +0,054 · KNN −0,055. RF sigue siendo el mejor, pero **ya no es el único positivo** |
| Resumen, 6.7 | LOOCV R² −2,5 / −2,492 | **LOOCV-Caserón R² −2,903** (media de 3 pliegues definidos: PCC_0042 −3,74 · PCC_1541 −4,38 · PCS_1043 −0,59; PCS_1059 tiene una sola etiqueta y queda indefinido); RMSE medio 52,0 MPa |
| — (nuevo) | — | **GroupKFold por pozo: R² +0,297 ± 0,010**, RMSE 31,5 MPa, ρ +0,563 (mediana de árboles) |
| — | — | Línea base «media global» (151,7 MPa): RMSE 37,6 MPa |
| Importancia | (no reportada) | FP 0,233 · RP 0,128 · PEP 0,061 · PP 0,038 · AP 0,032 · ROP 0,021 · DP 0,012 (permutación sobre 271 pozos no vistos) |
| Fig. 6.7 | — | p50 de la UCS predicha: Kpcli 166,4 (ancla 180) · Bht 136,6 (128,1) · Brecha mixta 154,8 (111,5) · **Kpcls 129,5 (ancla 60)** |
| 6.4, 6.7 | 49,4% de los picos a ≤ 3 m; 1.115 puntos DI ≥ 1 | PCC_1541: **1.616 picos** (fusión 0,5 m), 1.320 en pozos con cruces; precisión **51,0%** · azar 53,2% · recall 86,5% |
| 6.4 | desfase media −1,68 · mediana −0,71 · σ 7,11 m | media **−1,04** · mediana **−0,44** · σ **6,56 m** |
| 6.5, Fig. 6.12 | 15.388 bloques; 88,4% competente; 74,8% sano-competente | **14.913 bloques** de 2,5 m; los 14.913 en la banda ISRM R5 (100–250 MPa); DI: 97,0% sana · 2,6% transición · 0,4% fracturada; UCS mediana 153,9 (p10 129,2 · p90 170,3) |
| Tabla 6.3 | G3 Kpcli 467.615 (48,8%)… | **45 grupos**; G2 Kpcli 409.246 · G1 Bht 205.136 · G34 Kpcls 69.307 (tabla `T6_03`) |
| Tabla 6.4 | dominio G3 | dominio **G2** (Kpcli, el mayor); ranking completo en `T6_04` |
| D (salidas) | — | ancho P10–P90 medio: intacta 33,7 MPa · fracturada 40,4 MPa |

## Figuras y tablas (`figuras/finales/`)

| Archivo | Uso en la memoria |
|---|---|
| `F6_01_correlacion_pearson.png` | Fig. 6.1 (señales y perfiles de varianza) |
| `F6_02_percusion_empate.png` | Fig. 6.2 |
| `T6_01_sensibilidad_percusion_empate.png/.csv` | Tabla 6.1 |
| `T6_02_sensibilidad_radio_RQD.png/.csv` | Tabla 6.2 |
| `F6_03_perfil_DI_calibrado.png` | Fig. 6.3 (DI de P20_H12 + RQD de DDH13-LP-50 y DDH25-ZC-42) |
| `F6_04_RMSE_LOOCV_litologia.png` | Fig. 6.4 |
| `F6_05_spearman_LOOCV_litologia.png` | Fig. 6.5 |
| `F6_05b_spearman_por_esquema.png` | nueva: ρ del bosque por esquema de validación |
| `F6_06_PEP_vs_UCS.png` | Fig. 6.6 |
| `F6_07_UCS_lab_vs_ML.png` | Fig. 6.7 |
| `F6_08_comparacion_algoritmos.png` | Fig. 6.8 (GroupKFold) |
| `F6_09_desfase_DI_mallas_PCC1541.png` | Fig. 6.9 (+ precisión, recall y azar) |
| `F6_10_perfil_PCS1043_P07_H4.png` | Fig. 6.10 |
| `F6_11_seccion_tronadura_PCC0042.png` | Fig. 6.11 |
| `F6_12_clasificacion_DI_UCS.png` | Fig. 6.12 |
| `T6_03_dominios.png/.csv` | Tabla 6.3 |
| `T6_04_ranking_recomendaciones.png/.csv` | Tabla 6.4 |
| `F6_13_PEP_UCS_ROP_PP.png` | Fig. 6.13 |
| `F_RF_esquema.png`, `F_RF_detalle.png` | esquema simple y detalle del bosque |
| `F_DI_vs_estructura.png` | DI de P20_H12 contra el modelo geológico |
