"""Sensibilidad del DI al tamaño de ventana (10, 14 y 20 muestras), el mismo
análisis de di_sensitivity_analysis() del Paso 3, con la configuración final:
limpieza estándar, serie depurada y pesos calibrados a 5 m de final.json.
Picos = eventos DI > umbral agrupados a < 0,5 m (DI_PICOS_MIN_GAP_M).
Uso: python3 di_ventanas.py final.json di_ventanas.json
"""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
POZO = "PCC_0042_PR01_TH_P20_H12"


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
log("carga y DI listos")

UMB, PAR, PES = gw.di_threshold, gw.di_config["params"], gw.di_config["weights"]
R = {"ventanas": list(gw.DI_SENSITIVITY_WINDOWS), "umbral": UMB, "pesos": PES,
     "gap_m": gw.DI_PICOS_MIN_GAP_M, "paso_m": gw.MWD_PASO_NOMINAL_M, "pozo": {}, "global": {}, "por_caseron": {}}
acc = {w: defaultdict(lambda: {"picos": 0, "sobre": 0, "con_di": 0, "pozos": 0, "pozos_sin_di": 0, "metros": 0.0})
       for w in gw.DI_SENSITIVITY_WINDOWS}
for wn, w in gw.wells.items():
    pts = sorted(w.points, key=lambda p: p.largo)
    if not pts: continue
    L = [p.largo for p in pts]; cas = gw.caseron_de_pozo(w)
    for v in gw.DI_SENSITIVITY_WINDOWS:
        di = gw.di_profile_serie(pts, v, PAR, PES)
        for k in (cas, "TOTAL"):
            a = acc[v][k]; a["pozos"] += 1; a["metros"] += L[-1] - L[0]
            if di is None:
                a["pozos_sin_di"] += 1; continue
            fin = np.isfinite(di)
            a["con_di"] += int(fin.sum()); a["sobre"] += int((di[fin] > UMB).sum())
            a["picos"] += gw._count_fused_peaks(L, np.nan_to_num(di, nan=-1.0), UMB)
        if wn == POZO:
            R["pozo"][str(v)] = {"di": [None if not np.isfinite(x) else round(float(x), 4) for x in di]}
    if wn == POZO:
        R["pozo"]["largo"] = [round(x, 3) for x in L]
for v in gw.DI_SENSITIVITY_WINDOWS:
    for k, a in acc[v].items():
        fila = {"ventana": v, "ventana_cm": round(v * gw.MWD_PASO_NOMINAL_M * 100, 1), "pozos": a["pozos"],
                "pozos_sin_di": a["pozos_sin_di"], "registros_con_di": a["con_di"], "picos": a["picos"],
                "picos_por_100m": round(100 * a["picos"] / a["metros"], 2) if a["metros"] else None,
                "pct_sobre_umbral": round(100 * a["sobre"] / a["con_di"], 2) if a["con_di"] else None}
        (R["global"].__setitem__(str(v), fila) if k == "TOTAL" else R["por_caseron"].setdefault(k, {}).__setitem__(str(v), fila))
# el pozo de referencia, con el mismo conteo de la pantalla del Paso 3
Lp = R["pozo"]["largo"]
R["pozo"]["filas"] = []
for v in gw.DI_SENSITIVITY_WINDOWS:
    d = np.array([np.nan if x is None else x for x in R["pozo"][str(v)]["di"]])
    fin = np.isfinite(d)
    R["pozo"]["filas"].append({"ventana": v, "picos": gw._count_fused_peaks(Lp, np.nan_to_num(d, nan=-1.0), UMB),
                               "pct_sobre_umbral": round(100 * float((d[fin] > UMB).sum()) / fin.sum(), 2),
                               "registros_con_di": int(fin.sum())})
json.dump(R, open(OUT, "w"), ensure_ascii=False, default=float)
log(f"global: {R['global']}")
log(f"pozo: {R['pozo']['filas']}")
