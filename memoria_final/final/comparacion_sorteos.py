"""Estabilidad de la comparación de algoritmos frente al sorteo de pozos: la
misma comparación (tope de 60.000 registros, GroupKFold k = 5) con varias
semillas del sorteo de pozos completos. Uso:
python3 comparacion_sorteos.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
R = {"semillas": [], "corridas": []}
for s in (42, 1, 2, 3, 4, 5):
    gw.COMPARISON_SEED = s
    c = gw.model_comparison_report(with_se=True)
    R["semillas"].append(s)
    R["corridas"].append({"semilla": s, "n": c["n_samples"], "pozos": c["n_grupos"],
                          "filas": [{k: r[k] for k in ("modelo", "r2_mean", "r2_train_mean", "r2_std", "rmse_mean")} for r in c["rows"]]})
    print(s, [(r["modelo"], r["r2_train_mean"], r["r2_mean"]) for r in c["rows"]], flush=True)
    json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
mods = [r["modelo"] for r in R["corridas"][0]["filas"]]
R["resumen"] = {m: {"r2_prueba_media": round(float(np.mean([c["filas"][i]["r2_mean"] for c in R["corridas"]])), 3),
                    "r2_prueba_sd": round(float(np.std([c["filas"][i]["r2_mean"] for c in R["corridas"]])), 3),
                    "r2_entrenamiento_media": round(float(np.mean([c["filas"][i]["r2_train_mean"] for c in R["corridas"]])), 3),
                    "veces_mejor": int(sum(max(c["filas"], key=lambda r: r["r2_mean"])["modelo"] == m for c in R["corridas"]))}
                for i, m in enumerate(mods)}
json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1); print(json.dumps(R["resumen"], ensure_ascii=False))
