"""Concordancia de los picos de DI con los cruces de malla (litología y
estructura): desfase pico–cruce y sensibilidad al umbral de DI, con el MISMO
método que la figura de PCC_1541 en final_calc.py, para tres conjuntos:
los 4 caserones, PCC_0042 (donde se calibró el DI) y PCC_1541 (prueba).
Configuración final (limpieza estándar, serie depurada, pesos a 5 m).
Uso: python3 concordancia_caserones.py final.json concordancia_caserones.json
"""
import sys, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
RADIO, UMBRALES, N_AZAR = 3.0, [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0], 30
CONJUNTOS = {"4 caserones": None, "PCC_0042": "PCC_0042", "PCC_1541": "PCC_1541"}


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

cruces, rango, perf, cas = {}, {}, {}, {}
for wn, ww in gw.wells.items():
    p2 = sorted(ww.points, key=lambda p: p.largo)
    if len(p2) < 2: continue
    l2 = np.array([p.largo for p in p2])
    perf[wn] = (l2, np.array([p.di if p.di is not None else np.nan for p in p2]))
    rango[wn] = (float(l2[0]), float(l2[-1])); cas[wn] = gw.caseron_de_pozo(ww)
    cr, prev = [], None
    for p in p2:
        if prev is not None and p.dominio != prev[1] and p.dominio and prev[1]:
            cr.append((prev[0] + p.largo) / 2.0)
        prev = (p.largo, p.dominio)
    cruces[wn] = np.array(cr)


def picos_de(wn, u):
    l2, d2 = perf[wn]
    ix = np.flatnonzero(np.nan_to_num(d2, nan=-1) > u)
    if ix.size == 0: return np.array([])
    out, ult = [l2[ix[0]]], l2[ix[0]]
    for i in ix[1:]:
        if l2[i] - ult >= gw.DI_PICOS_MIN_GAP_M: out.append(l2[i])
        ult = l2[i]
    return np.array(out)


R = {"radio_m": RADIO, "umbral_di": FIN["umbral"], "conjuntos": {}}
for nombre, c in CONJUNTOS.items():
    pozos = [wn for wn in perf if c is None or cas[wn] == c]
    pcz = [wn for wn in pozos if len(cruces[wn])]
    rng = np.random.default_rng(42)
    PR = []
    for u in UMBRALES:
        P = {wn: picos_de(wn, u) for wn in pcz}
        op = tp = oc = tc = 0
        for wn in pcz:
            a, b = P[wn], cruces[wn]
            if a.size and b.size:
                dd = np.abs(a[:, None] - b[None, :])
                op += int((dd.min(axis=1) <= RADIO).sum()); tp += a.size
                oc += int((dd.min(axis=0) <= RADIO).sum()); tc += b.size
            elif b.size: tc += b.size
            elif a.size: tp += a.size
        nul = []
        for _ in range(N_AZAR):
            o = t = 0
            for wn in pcz:
                k = P[wn].size
                if not k: continue
                lo_, hi_ = rango[wn]
                dd = np.abs(rng.uniform(lo_, hi_, k)[:, None] - cruces[wn][None, :])
                o += int((dd.min(axis=1) <= RADIO).sum()); t += k
            if t: nul.append(o / t)
        PR.append({"u": u, "P": op / tp if tp else None, "R": oc / tc if tc else None,
                   "azar": float(np.mean(nul)) if nul else None, "n_picos": int(tp), "n_cruces": int(tc)})
    dl = []
    for wn in pcz:
        a, b = picos_de(wn, FIN["umbral"]), cruces[wn]
        if a.size and b.size:
            j = np.argmin(np.abs(a[:, None] - b[None, :]), axis=1); dl.extend((a - b[j]).tolist())
    dl = np.array(dl)
    R["conjuntos"][nombre] = {"n_pozos": len(pozos), "n_pozos_con_cruces": len(pcz), "pr": PR,
                              "desfases": [round(float(x), 3) for x in dl],
                              "desfase": {"n": int(dl.size), "media": round(float(dl.mean()), 3),
                                          "mediana": round(float(np.median(dl)), 3), "sd": round(float(dl.std()), 3)}}
    f1 = next(f for f in PR if abs(f["u"] - FIN["umbral"]) < 1e-9)
    log(f"{nombre}: pozos {len(pozos)} con cruces {len(pcz)} · umbral 1: P {f1['P']:.3f} azar {f1['azar']:.3f} "
        f"R {f1['R']:.3f} · desfase {R['conjuntos'][nombre]['desfase']}")
json.dump(R, open(OUT, "w"), ensure_ascii=False)
