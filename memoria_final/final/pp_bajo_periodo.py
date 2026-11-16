"""¿Las caídas de PP < 120 bar se repiten cada largo de barra (1,756 m)?
Rachas de PP < 120 en roca continua entrenable; distancias entre rachas del
mismo pozo comparadas con múltiplos del largo de barra (±6 cm), contra la
misma prueba con las rachas recolocadas al azar en el pozo (30 repeticiones).
Uso: python3 pp_bajo_periodo.py final.json pp_bajo_periodo.json
"""
import sys, json
from collections import Counter
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
gw.aplicar_limpieza_estandar()
gw.create_di_variant("calibrada_RQD_5m", FIN["pesos"], window=FIN["window"], threshold=FIN["umbral"])
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
anclas = gw._anclas_por_litologia(); LB, TOL = gw.LARGO_BARRA_M, 0.06

centros, rangos, largos_racha, caida = {}, {}, [], []
for wn, w in gw.wells.items():
    pts = sorted(w.points, key=lambda p: p.largo)
    if len(pts) < 3: continue
    c_, r = [], []
    for i, p in enumerate(pts):
        ok = (p.entrenable and p.lito in anclas and p.di is not None and p.di <= FIN["umbral"] and p.vel is not None
              and p.vel >= gw.ROP_MIN_FISICA and p.se is not None and np.isfinite(p.se) and p.pp is not None and 90 <= p.pp < 120)
        if ok: r.append(i)
        elif r:
            c_.append(np.mean([pts[j].largo for j in r])); largos_racha.append(len(r))
            vec = [q.pp for q in pts[max(0, r[0] - 3): r[0]] + pts[r[-1] + 1: r[-1] + 4] if q.pp]
            if vec: caida.append(1 - np.mean([pts[j].pp for j in r]) / np.median(vec))
            r = []
    if len(c_) >= 2: centros[wn] = np.array(c_); rangos[wn] = (pts[0].largo, pts[-1].largo)


def frac_periodica(cs):
    hit = tot = 0
    for c_ in cs.values():
        d = np.abs(c_[:, None] - c_[None, :])[np.triu_indices(c_.size, 1)]
        d = d[(d > LB - TOL) & (d < 3 * LB + TOL)]
        hit += int(np.sum(np.min(np.abs(d[:, None] - LB * np.array([1, 2, 3])[None, :]), axis=1) <= TOL))
    return hit / tot if tot else None, tot


obs, n_pares = frac_periodica(centros)
rng = np.random.default_rng(42); nul = []
for _ in range(30):
    nul.append(frac_periodica({wn: rng.uniform(*rangos[wn], c_.size) for wn, c_ in centros.items()})[0])
lr = Counter(largos_racha)
R = {"largo_barra_m": LB, "tol_m": TOL, "n_rachas": len(largos_racha), "n_pozos": len(centros),
     "rachas_por_largo": {str(k): lr[k] for k in sorted(lr)[:6]}, "caida_relativa_mediana": round(float(np.median(caida)), 3),
     "pares_1_a_3_barras": n_pares, "frac_periodica_obs": round(obs, 4), "frac_periodica_azar": round(float(np.mean(nul)), 4),
     "frac_periodica_azar_sd": round(float(np.std(nul)), 4)}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
print(R, flush=True)
