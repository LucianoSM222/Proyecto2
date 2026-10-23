"""¿Qué presión se relaciona directamente con la ROP? PP (percusión), AP
(avance), RP (rotación) y DP (dámper); FP (flujo de barrido) queda fuera por
criterio físico: es el aire/agua de barrido, no actúa sobre la roca.

Tres pruebas, de menos a más exigente, en roca continua entrenable (DI ≤ 1,
limpieza estándar, ROP ≥ mínimo físico, litología con UCS referencial):
  1. ρ de Spearman simple ROP–presión;
  2. ρ parcial: rangos de cada presión y de la ROP descontando linealmente las
     otras tres presiones (las presiones están correlacionadas entre sí);
  3. ρ intra-pozo: ρ de Spearman sobre las desviaciones respecto de la mediana
     de cada pozo, que quita la roca y el operador de cada tiro.
Además, R² de la regresión en rangos con las cuatro presiones, y con cada una
sola. Todo para el conjunto y por litología. Configuración final.
Uso: python3 rop_presiones.py final.json rop_presiones.json
"""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr, rankdata
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
PRES = [("pp", "PP"), ("pa", "AP"), ("pr", "RP"), ("pd", "DP")]


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

filas = []
for wn, w in gw.wells.items():
    for p in w.points:
        if not p.entrenable or p.lito not in anclas or p.di is None or p.di > FIN["umbral"]: continue
        if p.vel is None or p.vel < gw.ROP_MIN_FISICA: continue
        v = [getattr(p, k) for k, _ in PRES]
        if any(x is None or not np.isfinite(x) for x in v): continue
        filas.append((wn, p.lito, p.vel, *v))
log(f"{len(filas)} registros")


def r2_rangos(X, y):
    Xc = np.column_stack([X, np.ones(len(y))]); b, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    return float(1 - np.sum((y - Xc @ b) ** 2) / np.sum((y - y.mean()) ** 2))


def analizar(sel):
    pozo = np.array([f[0] for f in sel]); rop = np.array([f[2] for f in sel], float)
    P = np.array([f[3:] for f in sel], float)
    rr = rankdata(rop); RP_ = np.column_stack([rankdata(P[:, j]) for j in range(P.shape[1])])
    # desviaciones respecto de la mediana de cada pozo
    cod, inv = np.unique(pozo, return_inverse=True)
    def desv(v):
        med = np.zeros(cod.size)
        for k in range(cod.size): med[k] = np.median(v[inv == k])
        return v - med[inv]
    rop_d = desv(rop); P_d = np.column_stack([desv(P[:, j]) for j in range(P.shape[1])])
    out = {"n": len(sel), "n_pozos": int(cod.size), "presiones": {},
           "r2_rangos_las_4": round(r2_rangos(RP_, rr), 4)}
    for j, (_, et) in enumerate(PRES):
        otras = [k for k in range(len(PRES)) if k != j]
        Xo = np.column_stack([RP_[:, otras], np.ones(len(rr))])
        res_y = rr - Xo @ np.linalg.lstsq(Xo, rr, rcond=None)[0]
        res_x = RP_[:, j] - Xo @ np.linalg.lstsq(Xo, RP_[:, j], rcond=None)[0]
        out["presiones"][et] = {
            "rho_simple": round(float(spearmanr(P[:, j], rop).statistic), 3),
            "rho_parcial": round(float(np.corrcoef(res_x, res_y)[0, 1]), 3),
            "rho_intra_pozo": round(float(spearmanr(P_d[:, j], rop_d).statistic), 3),
            "r2_sola": round(r2_rangos(RP_[:, [j]], rr), 4),
            "mediana": round(float(np.median(P[:, j])), 1)}
    out["correlacion_entre_presiones"] = {f"{PRES[a][1]}-{PRES[b][1]}": round(float(spearmanr(P[:, a], P[:, b]).statistic), 3)
                                          for a in range(len(PRES)) for b in range(a + 1, len(PRES))}
    return out


R = {"umbral_di": FIN["umbral"], "rop_min": gw.ROP_MIN_FISICA, "grupos": {"Todas las litologías": analizar(filas)}}
for lito in sorted(anclas, key=lambda l: anclas[l]):
    sel = [f for f in filas if f[1] == lito]
    if len(sel) > 1000: R["grupos"][lito] = analizar(sel)
for g, d in R["grupos"].items():
    log(f"{g}: n={d['n']} R²(4)={d['r2_rangos_las_4']} " + " · ".join(
        f"{k}: ρ {v['rho_simple']} / parcial {v['rho_parcial']} / intra {v['rho_intra_pozo']}" for k, v in d["presiones"].items()))
log(f"entre presiones: {R['grupos']['Todas las litologías']['correlacion_entre_presiones']}")

# ranking de máxima ROP: AP de los 5 mejores segmentos frente al dominio
RK = json.load(open(SRC, encoding="utf-8"))["ranking"]["criterios"]
R["ranking"] = {k: [{"vel": c["vel"], "pp": c["pp"], "pa": c["pa"], "pr": c["pr"], "pd": c["pd"]} for c in v[:5]] for k, v in RK.items()}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
