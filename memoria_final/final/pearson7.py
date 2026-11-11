"""Correlación de Pearson entre las 7 variables MWD (PR, PP, FP, DP, RP, FLP y
PEP) sobre la serie depurada del DI. Uso: python3 pearson7.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
V = [("PR", "vel"), ("PP", "pp"), ("FP", "pa"), ("DP", "pd"), ("RP", "pr"), ("FLP", "pf"), ("PEP", "se")]
filas = []
for w in gw.wells.values():
    m = gw.mascara_serie_di(w.points)
    filas += [[getattr(p, a) for _, a in V] for p, k in zip(w.points, m) if k]
M = np.array(filas, float); M = M[np.isfinite(M).all(axis=1)]
R = {"variables": [s for s, _ in V], "n": int(M.shape[0]), "r": np.round(np.corrcoef(M.T), 3).tolist(),
     "nota": "serie depurada del DI; PEP = (PP + RP + FP) / PR"}
json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1); print(R["n"]); print(np.array(R["r"]))
