# Resultados finales para la memoria (2026-10-22)

Todas las cifras salen de una sola corrida (`memoria_final/final/final_calc.py`
→ `final.json`). Las figuras y tablas, sin pies de figura y en estilo Excel,
están en `figuras/finales/`; los valores de todas las tablas, en
`figuras/finales/tablas_capitulo6.xlsx` (`tablas_excel.py`). Se regeneran con `final_figs.py`, `pep_muestra.py`, `rf_figura.py`,
`rf_esquema.py`, `di_estructura.py` y `barra/fig_periodo.py`.

## Configuración

| Elemento | Valor |
|---|---|
| Serie del DI | **depurada**: emboquillado (2 m) y percusión de empate salen de la serie **antes** de la varianza móvil y de la estandarización por pozo; su DI queda vacío (95.761 registros) |
| Filtros solo del entrenamiento | rango físico de PP 90–230 bar (12.103) · continuidad del registro (5.162) |
| Percusión de empate | caída ≥ 0,25 respecto de las dos vecinas, vecinas a ≤ 12,5% entre sí (12.786 sobre el total; 8.911 fuera del emboquillado) |
| Total no entrenable por limpieza | 112.961 (11,5%) |
| DI | ventana 14 (≈ 28 cm), umbral 1,0, PP · RP · DP · FP (sin avance) |
| Pesos del DI (calibrados a 5 m) | **PP 0,01 · RP 0,39 · DP 0,07 · FP 0,54** |
| Random Forest | 200 árboles · profundidad 8 · min_samples_split 6 · min_samples_leaf 3 · max_features √p · semilla 42 |
| Agregación | **mediana** de los 200 árboles (predicción y todas las métricas) |
| Siglas | FP = flujo, AP = avance (Pucobre) · PEP = presión específica de penetración |
| UCS de laboratorio | «referencial» de cada litología (antes «ancla») |

## Cifras

| Dónde | Valor final |
|---|---|
| Registros / pozos | 982.420 / 928 |
| DI ≤ 1 / DI > 1 / sin DI | 735.674 / 150.985 / 95.761 |
| Conjunto de entrenamiento | **723.601** registros en 902 pozos |
| Etiquetas | Kpcli 180 (426.935) · Bht 128,1 (226.219) · Kpcls 60 (53.596) · Brecha mixta 111,5 (16.851) |
| Tabla 6.1 | 0,25 → 12.786 (1,30%); empates esperados por largo de barra (1,756 m): 11.189 |
| Pearson PP–DP | señales 0,47 · varianza móvil (entrada del DI) 0,53 |
| Tabla 6.2, radio 5 m | 32 pares, 4 sondajes; ρ ajuste **+0,236**, validación dejando un sondaje fuera **+0,051** |
| GroupKFold por pozo (k = 5) | **R² +0,290 ± 0,02**, RMSE 30,4 MPa, ρ de Spearman +0,564 |
| LOOCV-Caserón | **R² −2,766** (PCC_0042 −3,55 · PCC_1541 −4,14 · PCS_1043 −0,61; PCS_1059 tiene una sola etiqueta: indefinido); RMSE medio 50,5 MPa; ρ +0,111 |
| Línea base «media global» (153,3 MPa) | RMSE 36,1 MPa |
| Importancia por permutación | FP 0,223 · RP 0,131 · PEP 0,049 · PP 0,043 · AP 0,041 · ROP 0,016 · DP 0,009 (271 pozos no vistos) |
| UCS predicha, p50 vs. referencial | Kpcli 167,3 (180) · Bht 137,6 (128,1) · Brecha mixta 154,6 (111,5) · Kpcls 133,0 (60) |
| Comparación de algoritmos (R² prueba / entrenamiento) | **RF +0,166 / 0,485** · HGB +0,147 / 0,594 · Lineal +0,136 / 0,184 · MLP +0,088 / 0,492 · KNN −0,059 / 0,703 (59.326 registros, 76 pozos) |
| Concordancia DI ↔ mallas, PCC_1541 | 1.596 picos; en pozos con cruces 1.320; **precisión 58,0%** (azar 52,6%) · **recall 92,8%** (radio 3 m) |
| Desfase pico–cruce | media −0,08 m · mediana +0,15 m · σ 5,46 m |
| Modelo de bloques | 14.913 bloques de 2,5 m; 8,5% con DI > 1; UCS mediana 154,4 MPa (p10 130,9 · p90 170,2) |
| Dominios | 50 grupos (±20 MPa, ±0,5 DI, tramos de 2 m); G2 Kpcli 408.718 · G1 Bht 202.651 · G39 Kpcls 65.848 |
| Banda P10–P90 media | intacta 32,3 MPa · fracturada 38,3 MPa |

> **LOOCV-Litología retirada del proyecto** (decisión del autor, 2026-10-22,
> por complejidad). La memoria valida el modelo con GroupKFold por pozo y
> LOOCV-Caserón; las antiguas Fig. 6.4 y 6.5 (RMSE y ρ dejando una litología
> fuera) ya no forman parte de los entregables.

## Lo que cambió al depurar la serie del DI

- **La concordancia supera al azar por primera vez:** 58,0% contra 52,6%.
  Con el DI sobre la serie completa era 51,0% contra 53,2%. Las caídas de
  empate y el arranque del pozo generaban picos que no eran roca.
- **La validación de la calibración pasa a positiva** (ρ +0,051, antes
  −0,157), aunque sigue siendo baja: con 4 sondajes la calibración no se
  asienta.
- **Los pesos vuelven a moverse:** FP 0,54 y RP 0,39 dominan; PP y DP quedan
  casi en cero.

## Figuras y tablas (`figuras/finales/`)

| Archivo | Uso en la memoria |
|---|---|
| `F6_01_correlacion_pearson.png` | Fig. 6.1 |
| `F6_02_percusion_empate.png` | Fig. 6.2 |
| `F6_02b_periodicidad_empate.png` | periodicidad de la percusión de empate con el largo de barra |
| `F6_02c_localizacion_registros_filtrados.png` | antes/después en P20_H12 con la posición de cada registro excluido (emboquillado, empate, rango de PP, continuidad) |
| `T6_01_sensibilidad_percusion_empate.png/.csv` | Tabla 6.1 |
| `T6_02_sensibilidad_radio_RQD.png/.csv` | Tabla 6.2 |
| `F6_03_perfil_DI_calibrado.png` | Fig. 6.3 |
| `F6_04_LOOCV_caseron.png` | ρ de Spearman y R² por caserón dejado fuera |
| `F6_05_spearman_por_esquema.png` | ρ del bosque por pozo (GroupKFold) y por caserón (LOOCV-Caserón) |
| `F6_06_PEP_vs_UCS.png` | Fig. 6.6 |
| `F6_07_UCS_lab_vs_ML.png` | Fig. 6.7 |
| `F6_08_comparacion_algoritmos.png` | Fig. 6.8 |
| `F6_09_desfase_DI_mallas_PCC1541.png` | Fig. 6.9 |
| `F6_10_perfil_PCS1043_P07_H4.png` | Fig. 6.10 |
| `F6_11_seccion_tronadura_PCC0042.png` | Fig. 6.11 |
| `F6_12_clasificacion_DI_UCS.png` | Fig. 6.12 |
| `T6_03_dominios.png/.csv` | Tabla 6.3 |
| `T6_04_ranking_recomendaciones.png/.csv` | Tabla 6.4 |
| `F6_13_PEP_UCS_ROP_PP.png` | Fig. 6.13 |
| `F6_13b_PEP_UCS_ROP_PP_registros.png` | PEP por registro contra UCS referencial, ROP y PP (color = PP) |
| `tablas_capitulo6.xlsx` | valores de todas las tablas y figuras, una hoja por tema |
| `F_RF_esquema.png`, `F_RF_detalle.png` | esquema y detalle del bosque |
| `F_DI_vs_estructura.png` | DI de P20_H12 contra el modelo geológico |
