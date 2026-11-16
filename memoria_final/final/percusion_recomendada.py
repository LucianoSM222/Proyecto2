"""Percusión recomendada por litología y ranking de tramos de perforación.
Datos: los cuatro caserones, registros entrenables con DI ≤ 1 (roca continua).
Por litología, la PP se agrupa en tramos de 5 bar; entre los tramos cuya PR
mediana queda entre 1,0 y 1,2 m/min se elige el de MENOR varianza de PEP.
Ranking: tramos de 5 m de un solo dominio, PR media en 1,0-1,2 m/min,
ordenados por el CV de la PEP (perforación más pareja primero).
Uso: python3 percusion_recomendada.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import defaultdict
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
PR_LO, PR_HI, BIN, NMIN, NMIN_FALLA, TRAMO = 1.0, 1.2, 5.0, 200, 50, 5.0
# Dominio: la litología, o «litología::estructura» si el registro está en una falla de la malla.
dom = lambda p: (f"{p.lito}::{p.estructura}" if p.estructura else p.lito) if p.lito else None
es_falla = lambda d: "::" in d
acc = defaultdict(lambda: defaultdict(lambda: {"pr": [], "pep": []}))
tramos = defaultdict(list)
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    # roca continua (DI ≤ 1) en la litología; en falla se usa todo registro con DI
    ok = [p.entrenable and p.di is not None and dom(p) is not None and np.isfinite(p.se)
          and (p.di <= 1.0 or es_falla(dom(p))) for p in ps]
    for p, k in zip(ps, ok):
        if k:
            d = acc[dom(p)][float(np.floor(p.pp / BIN) * BIN + BIN / 2)]
            d["pr"].append(p.vel); d["pep"].append(p.se)
    if not ps: continue
    L = np.array([p.largo for p in ps])
    for a in np.arange(0, L[-1], TRAMO):
        idx = [i for i in np.flatnonzero((L >= a) & (L < a + TRAMO))]
        if len(idx) < 150: continue
        lit = {dom(ps[i]) for i in idx}
        if len(lit) != 1 or None in lit: continue
        sel = [i for i in idx if ok[i]]
        if len(sel) < 0.8 * len(idx): continue
        pr = np.array([ps[i].vel for i in sel]); pep = np.array([ps[i].se for i in sel]); pp = np.array([ps[i].pp for i in sel])
        if not (PR_LO <= pr.mean() <= PR_HI): continue
        tramos[lit.pop()].append({"barreno": wn, "caseron": gw.caseron_de_pozo(w), "desde_m": round(float(a), 1),
                                  "pp": round(float(pp.mean()), 1), "pr": round(float(pr.mean()), 3),
                                  "pep": round(float(pep.mean()), 1), "cv_pep": round(float(pep.std() / pep.mean()), 4)})
R = {"criterio": {"pr_objetivo": [PR_LO, PR_HI], "bin_pp_bar": BIN, "n_min_bin": NMIN, "n_min_bin_falla": NMIN_FALLA,
                  "datos": "4 caserones, registros entrenables; litología con DI ≤ 1, falla (litología::estructura) con todo DI"}, "litologias": {}}
for lit, bins in acc.items():
    curva = []
    for pp in sorted(bins):
        pr = np.array(bins[pp]["pr"]); pep = np.array(bins[pp]["pep"])
        if pr.size < (NMIN_FALLA if es_falla(lit) else NMIN): continue
        curva.append({"pp": pp, "n": int(pr.size), "pr_mediana": round(float(np.median(pr)), 3),
                      "pep_mediana": round(float(np.median(pep)), 1), "pep_sd": round(float(pep.std()), 1),
                      "pep_var": round(float(pep.var()), 0)})
    if not curva: continue
    cand = [c for c in curva if PR_LO <= c["pr_mediana"] <= PR_HI]
    if cand:
        rec = min(cand, key=lambda c: c["pep_var"]); motivo = "PR mediana en 1,0–1,2 m/min con la menor varianza de PEP"
    else:
        rec = min(curva, key=lambda c: min(abs(c["pr_mediana"] - PR_LO), abs(c["pr_mediana"] - PR_HI)))
        motivo = "ningún tramo de PP alcanza PR 1,0–1,2 m/min: se toma el más cercano"
    rk = sorted(tramos.get(lit, []), key=lambda t: t["cv_pep"])
    R["litologias"][lit] = {"curva": curva, "recomendada": rec, "motivo": motivo, "candidatos": len(cand),
                            "n_total": int(sum(c["n"] for c in curva)), "ranking": rk[:5], "n_tramos_ranking": len(rk)}
    print(lit, "PP", rec["pp"], "PR", rec["pr_mediana"], "PEP sd", rec["pep_sd"], "| cand", len(cand), "| tramos", len(rk), "|", motivo)
json.dump(R, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
