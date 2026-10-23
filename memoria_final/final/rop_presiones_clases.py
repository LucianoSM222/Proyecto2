"""ρ de Spearman simple entre la ROP y PP, AP, RP y DP en roca continua
(DI ≤ 1) y fracturada (DI > 1). Mismo filtro que rop_presiones.py, salvo el DI.
Uso: python3 rop_presiones_clases.py final.json rop_presiones_clases.json
"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
PRES = [("pp", "PP"), ("pa", "AP"), ("pr", "RP"), ("pd", "DP")]
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
gw.aplicar_limpieza_estandar()
gw.create_di_variant("calibrada_RQD_5m", FIN["pesos"], window=FIN["window"], threshold=FIN["umbral"])
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
anclas = gw._anclas_por_litologia()
filas = {"continua": [], "fracturada": []}; pozos = {"continua": set(), "fracturada": set()}
for wn, w in gw.wells.items():
    for p in w.points:
        if not p.entrenable or p.lito not in anclas or p.di is None: continue
        if p.vel is None or p.vel < gw.ROP_MIN_FISICA: continue
        v = [getattr(p, k) for k, _ in PRES]
        if any(x is None or not np.isfinite(x) for x in v): continue
        k = "fracturada" if p.di > FIN["umbral"] else "continua"
        filas[k].append((p.vel, *v)); pozos[k].add(wn)
R = {}
for k, F in filas.items():
    A = np.array(F, float)
    R[k] = {"n": len(F), "n_pozos": len(pozos[k]),
            "rho": {et: round(float(spearmanr(A[:, 0], A[:, j + 1]).statistic), 3) for j, (_, et) in enumerate(PRES)}}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
print(R, flush=True)
