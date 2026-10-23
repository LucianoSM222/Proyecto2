"""PEP, ROP y UCS modelada (Random Forest, mediana de los árboles) por
litología e intervalo de PP de 10 bar, separando roca continua (DI ≤ 1) y
fracturada (DI > 1). Configuración final: limpieza estándar, serie depurada,
pesos calibrados a 5 m de final.json, modelo de producción reentrenado igual
que en final_calc.py. Registros entrenables (limpieza) con litología con UCS
referencial, ROP ≥ mínimo físico y PEP finita; intervalos con ≥ pp.min_puntos_bin.
Uso: python3 pep_estratos_clases.py final.json pep_estratos_clases.json
"""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]


def log(m):
    print(f"[{time.time()-T0:5.0f}s] {m}", flush=True)


cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
gw.aplicar_limpieza_estandar()
gw.create_di_variant("calibrada_RQD_5m", FIN["pesos"], window=FIN["window"], threshold=FIN["umbral"])
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
res = gw.train_rf(); gw.predict_all_wells()
log(f"modelo: cv {res.get('cv_r2_mean')} n {res.get('n_train')}")
anclas = gw._anclas_por_litologia(); MIN_BIN = int(gw.get_param("pp.min_puntos_bin"))

cel = defaultdict(lambda: {"pep": [], "rop": [], "ucs": []})
for p in gw.all_points():
    if not p.entrenable or p.lito not in anclas or p.di is None or p.pp is None: continue
    if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se) or p.ucs_ml is None: continue
    clase = "fracturada" if p.di > FIN["umbral"] else "continua"
    k = (clase, p.lito, int(p.pp // 10 * 10))
    cel[k]["pep"].append(p.se); cel[k]["rop"].append(p.vel); cel[k]["ucs"].append(p.ucs_ml)
R = {"umbral_di": FIN["umbral"], "min_bin": MIN_BIN, "anclas": anclas, "filas": [], "rho_pp_ucs": {}}
for (clase, lito, b), v in sorted(cel.items()):
    if len(v["pep"]) < MIN_BIN: continue
    R["filas"].append({"clase": clase, "lito": lito, "ucs_lab": anclas[lito], "pp_bin": b, "n": len(v["pep"]),
                       "pep_mediana": float(np.median(v["pep"])), "rop_mediana": float(np.median(v["rop"])),
                       "ucs_ml_mediana": float(np.median(v["ucs"]))})
for clase in ("continua", "fracturada"):
    for lito in anclas:
        ff = [f for f in R["filas"] if f["clase"] == clase and f["lito"] == lito]
        if len(ff) >= 3:
            R["rho_pp_ucs"].setdefault(clase, {})[lito] = {
                "rho": round(float(spearmanr([f["pp_bin"] for f in ff], [f["ucs_ml_mediana"] for f in ff]).statistic), 3),
                "n_intervalos": len(ff)}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
log(f"filas {len(R['filas'])} · ρ PP–UCS modelada {R['rho_pp_ucs']}")
