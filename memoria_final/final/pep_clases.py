"""PEP contra UCS referencial y ROP en roca intacta (DI ≤ 1) y fracturada
(DI > 1), sobre la POBLACIÓN completa (sin muestreo): ρ de Spearman y R² de
los ajustes lineal y parabólico. Configuración final (limpieza estándar, serie
depurada, pesos calibrados a 5 m de final.json). Mismo filtro que la figura
PEP vs UCS: ROP ≥ mínimo físico, PEP finita y ≤ 1.000, litología con UCS
referencial.
Uso: python3 pep_clases.py final.json pep_clases.json
"""
import sys, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
PEP_MAX = 1000.0


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
anclas = gw._anclas_por_litologia()
log("carga y DI listos")


def r2(x, y, grado):
    c = np.polyfit(x, y, grado); p = np.polyval(c, x)
    return round(float(1 - np.sum((y - p) ** 2) / np.sum((y - y.mean()) ** 2)), 4), [float(v) for v in c]


filas = {"intacta": [], "fracturada": []}
for p in gw.all_points():
    if p.di is None or p.lito not in anclas: continue
    if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se) or p.se > PEP_MAX: continue
    filas["fracturada" if p.di > FIN["umbral"] else "intacta"].append((p.se, p.vel, anclas[p.lito], p.entrenable))

R = {"pep_max": PEP_MAX, "rop_min": gw.ROP_MIN_FISICA, "umbral_di": FIN["umbral"], "clases": {}}
for k, v in filas.items():
    for alcance in ("todos", "entrenables"):
        A = np.array([f[:3] for f in v if alcance == "todos" or f[3]], float)
        pep, rop, ur = A[:, 0], A[:, 1], A[:, 2]
        R["clases"].setdefault(k, {})[alcance] = {
            "n": int(A.shape[0]),
            "rho_pep_rop": round(float(spearmanr(pep, rop).statistic), 3),
            "rho_pep_ucs_ref": round(float(spearmanr(pep, ur).statistic), 3),
            "r2_rop_lineal": r2(pep, rop, 1)[0], "r2_rop_parabolico": r2(pep, rop, 2)[0],
            "r2_ucs_ref_lineal": r2(pep, ur, 1)[0], "r2_ucs_ref_parabolico": r2(pep, ur, 2)[0],
            "coef_rop_parabolico": r2(pep, rop, 2)[1], "coef_ucs_ref_parabolico": r2(pep, ur, 2)[1]}
        log(f"{k} {alcance}: {R['clases'][k][alcance]}")
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
