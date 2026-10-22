"""Convierte final.json al formato que leen rf_figura.py y rf_esquema.py."""
import json, sys, math
sys.path.insert(0, "/home/user/Proyecto2")
import geomech_wizard as gw
R = json.load(open(sys.argv[1], encoding="utf-8"))
nombre_de = {v["ancla"]: k for k, v in R["ucs_por_litologia"].items()}
et = sorted(((float(k), n) for k, n in R["entrenamiento"]["etiquetas"].items()), key=lambda t: -t[1])
N = sum(n for _, n in et); mu = sum(v * n for v, n in et) / N
D = {"config": {"di_threshold": R["di_vigente"]["umbral"], "di_window": R["di_vigente"]["window"],
                "di_ventana_cm": gw.DI_VENTANA_CM, "di_weights": R["di_vigente"]["pesos"],
                "di_variante": R["di_vigente"]["variante"],
                "ml_features": gw.ML_FEATURES, "ml_labels": gw.ML_LABELS,
                "rf": {k: str(v) for k, v in gw.RF_PRODUCCION.items()}, "modo_ucs": "auto",
                "perm_semilla": gw.PERM_IMP_SEMILLA, "perm_n": gw.PERM_IMP_N_MUESTRAS,
                "limpieza": R["limpieza"]},
     "embudo": R["embudo"],
     "etiquetas": [{"litologia": nombre_de.get(v, str(v)), "ucs_MPa": v, "n_puntos": n,
                    "pct": round(100 * n / N, 2)} for v, n in et],
     "por_caseron": [{"caseron": c, **d} for c, d in sorted(R["entrenamiento"]["por_caseron"].items())],
     "n_pozos_grupo": R["entrenamiento"]["n_pozos"],
     "importancia": R["train_rf"]["feat_imp"], "importancia_nota": R["train_rf"]["feat_imp_motivo"],
     "arbol_ejemplo": R["arbol_ejemplo"],
     "groupkfold": {"n_pliegues": len(R["groupkfold"]["pliegues"]), "unidad": "pozo",
                    "pliegues": R["groupkfold"]["pliegues"], "r2_medio": R["groupkfold"]["r2_medio"],
                    "rmse_medio": R["groupkfold"]["rmse_medio"], "spearman_medio": R["groupkfold"]["spearman_medio"]},
     "loocv": {"unidad": "caserón", "nombre": "LOOCV-Caserón",
               "pliegues": [{**f, "r2_reportado": f["r2"]} for f in R["loocv_caseron"]["pliegues"]],
               "r2_medio_cross_val_score": R["loocv_caseron"]["r2_medio_definidos"],
               "n_definidos": R["loocv_caseron"]["n_definidos"], "rmse_medio": R["loocv_caseron"]["rmse_medio"]},
     "linea_base": {"media_global": {"prediccion_MPa": round(mu, 1),
                                     "rmse": round(math.sqrt(sum(n * (v - mu) ** 2 for v, n in et) / N), 1)}},
     "spearman_ajuste": R["groupkfold"]["spearman_medio"],
     "intervalo_p10_p90": {"roca_intacta": {"n": R["p10_p90"]["intacta"]["n"], "ancho_medio_MPa": R["p10_p90"]["intacta"]["media"]},
                           "roca_fracturada": {"n": R["p10_p90"]["fract"]["n"], "ancho_medio_MPa": R["p10_p90"]["fract"]["media"]},
                           "nota": "ucs_ml = MEDIANA de los 200 árboles; P10/P90 ensanchados por pi_factor y acotados a 0-450 MPa."},
     "banda_check": {}}
for out in sys.argv[2:]:
    json.dump(D, open(out, "w"), ensure_ascii=False, indent=2, default=float)
print("OK", D["linea_base"], D["loocv"]["r2_medio_cross_val_score"])
