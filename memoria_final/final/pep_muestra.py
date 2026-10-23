"""Muestra por registro de PEP, UCS referencial, ROP y PP para la figura de tres
paneles (PEP vs UCS referencial · vs ROP · vs PP). Misma configuración que
final_calc.py: limpieza estándar, DI calibrado a 5 m con los pesos de final.json.
Uso: python3 pep_muestra.py final.json pep_muestra.json
"""
import sys, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
PEP_MAX, N_MUESTRA = 1000.0, 30000


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

# Registros entrenables de roca intacta con UCS referencial; PEP ≤ 1.000 porque
# con ROP ≈ 0 la PEP no tiene sentido físico (lavado del bit, no roca).
filas, fuera_pep = [], 0
for p in gw.all_points():
    if not p.entrenable or p.lito not in anclas or p.di is None or p.di > FIN["umbral"]: continue
    if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se) or p.pp is None: continue
    if p.se > PEP_MAX:
        fuera_pep += 1; continue
    filas.append((p.se, anclas[p.lito], p.vel, p.pp, p.lito))
A = np.array([f[:4] for f in filas], float)
from scipy.stats import spearmanr
rho = {k: round(float(spearmanr(A[:, 0], A[:, j]).statistic), 3) for k, j in (("ucs_ref", 1), ("rop", 2), ("pp", 3))}
ii = np.random.default_rng(42).choice(len(filas), min(N_MUESTRA, len(filas)), replace=False)
R = {"n": len(filas), "fuera_pep_max": fuera_pep, "pep_max": PEP_MAX, "rop_min": gw.ROP_MIN_FISICA,
     "spearman_pep": rho, "anclas": anclas,
     "pep": [round(filas[i][0], 1) for i in ii], "ucs_ref": [filas[i][1] for i in ii],
     "rop": [round(filas[i][2], 3) for i in ii], "pp": [round(filas[i][3], 1) for i in ii],
     "lito": [filas[i][4] for i in ii]}
json.dump(R, open(OUT, "w"), ensure_ascii=False, default=float)
log(f"n {len(filas)} · fuera por PEP > {PEP_MAX:.0f}: {fuera_pep} · rho {rho}")
