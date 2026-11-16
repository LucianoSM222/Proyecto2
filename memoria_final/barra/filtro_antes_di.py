"""Escenarios A y B de percusión de empate, con las muestras marcadas SACADAS de
la serie antes de calcular el DI (no entran a la ventana ni a la estandarización
por pozo). Uso: python3 filtro_antes_di.py salida.json A|B

A: toda caída ≥ 0,25 respecto de sus dos vecinas parecidas (filtro vigente).
B: además, caída aislada (sin otra a < 0,5 m) con pareja a 1, 2 o 3 largos de
   barra (±6 cm): empate forzado por el largo de barra.
Emboquillado, rango físico de PP y continuidad se marcan antes, sobre la serie
completa: sacar una muestra deja un salto de ~4 cm que la continuidad leería
como vacío de registro.
"""
import sys, os, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

T0 = time.time()
OUT, ESC = sys.argv[1], sys.argv[2]
L, TOL, R_AISL, KS, UMBRAL = gw.LARGO_BARRA_M, 0.06, 0.5, (1, 2, 3), 0.25


def log(m):
    print(f"[{time.time()-T0:5.0f}s] {m}", flush=True)


cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
D = "/home/user/Proyecto2/test_data/reales/MPC Sondajes"
FILES = {"header": "MPC_header.csv", "survey": "MPC_survey.csv", "lithology": "MPC_lithology.csv",
         "structure": "MPC_structure.csv", "geomec": "MPC_geomec.csv", "density": "MPC_density.csv"}
gw.load_drillhole_csvs({k: open(os.path.join(D, v), "rb").read() for k, v in FILES.items()})
gw.refresh_drillhole_selection()
R = {"escenario": ESC, "umbral_empate": UMBRAL, "L": L, "tol_m": TOL, "aislamiento_m": R_AISL, "k": KS}

# 1) emboquillado + PP 90-230 + continuidad, sobre la serie completa
gw.clean_filters.clear(); gw.recompute_filters(2.0)
n0 = sum(len(w.points) for w in gw.wells.values())

# 2) percusión de empate (A o B): las marcas SALEN de la serie
n_marca = 0
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    idx = gw.detectar_percusion_de_empate(ps, UMBRAL)
    if ESC == "B":
        if len(idx) >= 2:
            x = np.array([ps[i].largo for i in idx])
            d = np.abs(x[None, :] - x[:, None]); np.fill_diagonal(d, 99)
            ais = d.min(axis=1) > R_AISL
            ok = np.zeros(x.size, bool)
            for k in KS:
                ok |= ((np.abs(d - k * L) <= TOL) & ais[None, :]).any(axis=1)
            idx = [i for i, o in zip(idx, ok & ais) if o]
        else:
            idx = []
    fuera = set(idx); n_marca += len(fuera)
    w.points = [p for i, p in enumerate(ps) if i not in fuera]
R["limpieza"] = {"marcas_sacadas_de_la_serie": n_marca, "registros_originales": n0,
                 "registros_en_serie": sum(len(w.points) for w in gw.wells.values()),
                 "no_entrenables_otros_filtros": sum(1 for w in gw.wells.values() for p in w.points if not p.entrenable)}
log(f"escenario {ESC}: {R['limpieza']}")

# 3) DI calibrado a 5 m sobre la serie depurada
gw.compute_di()
gw.confirmar_radio_rqd(5.0)
cal = gw.calibrate_di_weights(radio_m=5.0, umbral=1.0, window=14, params=("pp", "pr", "pd", "pf"),
                              nombre_variante="calibrada_RQD_5m_" + ESC, registrar=True)
gw.activar_di("calibrada_RQD_5m_" + ESC); gw.compute_di()
R["di"] = {"pesos": {k: round(float(v), 4) for k, v in cal["pesos"].items()},
           "rho_ajuste": cal["rho_ajuste"], "rho_validacion": cal["rho_validacion"],
           "n_pares": cal["n_pares"], "n_sondajes": cal["n_sondajes"],
           "pliegues": [(p["sondaje"], p.get("rho")) for p in cal["validacion"]["pliegues"]]}
di = np.array([p.di for w in gw.wells.values() for p in w.points if p.di is not None])
R["di"]["n_le_1"] = int((di <= 1.0).sum()); R["di"]["n_gt_1"] = int((di > 1.0).sum())
X, y, g, _, fun = gw._training_funnel(gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"])
R["entrenamiento"] = int(len(y))
log(f"DI: {R['di']}  entrenamiento {len(y)}")

# 4) concordancia con los cruces de malla en PCC_1541 (mismo método que la memoria)
RADIO = 3.0
cruces, rango, perf = {}, {}, {}
for wn, ww in gw.wells.items():
    if gw.caseron_de_pozo(ww) != "PCC_1541": continue
    p2 = sorted(ww.points, key=lambda p: p.largo)
    if len(p2) < 2: continue
    l2 = np.array([p.largo for p in p2])
    perf[wn] = (l2, np.array([p.di if p.di is not None else np.nan for p in p2])); rango[wn] = (l2[0], l2[-1])
    cr, prev = [], None
    for p in p2:
        if prev is not None and p.dominio != prev[1] and p.dominio and prev[1]: cr.append((prev[0] + p.largo) / 2)
        prev = (p.largo, p.dominio)
    cruces[wn] = np.array(cr)
pcz = [wn for wn in cruces if len(cruces[wn])]


def picos(wn, u=1.0):
    l2, d2 = perf[wn]; ix = np.flatnonzero(np.nan_to_num(d2, nan=-1) > u)
    if not ix.size: return np.array([])
    out, ult = [l2[ix[0]]], l2[ix[0]]
    for i in ix[1:]:
        if l2[i] - ult >= gw.DI_PICOS_MIN_GAP_M: out.append(l2[i])
        ult = l2[i]
    return np.array(out)


P = {wn: picos(wn) for wn in pcz}
op = tp = oc = tc = 0
for wn in pcz:
    a, b = P[wn], cruces[wn]; tc += b.size; tp += a.size
    if a.size:
        dd = np.abs(a[:, None] - b[None, :])
        op += int((dd.min(axis=1) <= RADIO).sum()); oc += int((dd.min(axis=0) <= RADIO).sum())
rng, nul = np.random.default_rng(42), []
for _ in range(30):
    o = t = 0
    for wn in pcz:
        k = P[wn].size
        if not k: continue
        dd = np.abs(rng.uniform(*rango[wn], k)[:, None] - cruces[wn][None, :])
        o += int((dd.min(axis=1) <= RADIO).sum()); t += k
    nul.append(o / t)
R["concordancia_1541"] = {"picos": tp, "picos_a_3m": op, "precision": op / tp, "azar": float(np.mean(nul)),
                          "cruces": tc, "cruces_con_pico": oc, "recall": oc / tc,
                          "picos_total_1541": int(sum(picos(wn).size for wn in perf))}
log(f"concordancia: {R['concordancia_1541']}")
json.dump(R, open(OUT, "w"), indent=1, default=float)
