"""LOOCV-Litología con el bosque (método «ml»): se deja una litología fuera,
se entrena con las demás y se estima la UCS mediana de la excluida. ρ de
Spearman entre la UCS estimada y la de ensayo, sobre las litologías.
Uso: python3 loocv_litologia.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from scipy.stats import spearmanr
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
R = gw.leave_one_lithology_out(metodo="ml")
pl = [p for p in R.get("pliegues", []) if p["ucs_predicho"] is not None]
R["spearman"] = round(float(spearmanr([p["ucs_real"] for p in pl], [p["ucs_predicho"] for p in pl]).statistic), 3) if len(pl) >= 3 else None
json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1, default=float)
print(R.get("status"), R.get("spearman"), R.get("mae_mpa"), [(p["litologia"], p["ucs_real"], p["ucs_predicho"]) for p in R.get("pliegues", [])])
