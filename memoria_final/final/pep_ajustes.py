"""¿Qué ajuste UCS referencial ~ PEP representa mejor los datos, y sobre qué
conjunto? Configuración final (limpieza estándar, serie depurada, pesos
calibrados a 5 m de final.json). Registros entrenables con litología con UCS
referencial, ROP ≥ mínimo físico y PEP finita ≤ 1.000.

Conjuntos: «intacta» (DI ≤ 1) y «todo» (intacta + fracturada).
Agregación:
- registro: cada registro es un punto (población completa, sin muestreo);
- litologia: mediana de PEP por litología (un punto por litología);
- litologia_caseron: mediana por litología y caserón;
- litologia_estrato_pp: mediana por litología y estrato de PP de 10 bar
  (≥ pp.min_puntos_bin registros), como la figura PEP–UCS–ROP–PP.
Formas: lineal, parabólica, potencial, exponencial y logarítmica; el R² se
mide SIEMPRE en MPa (espacio original) para que sean comparables.
Uso: python3 pep_ajustes.py final.json pep_ajustes.json
"""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr, pearsonr
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
MIN_BIN = int(gw.get_param("pp.min_puntos_bin"))
log("carga y DI listos")

reg = []
for w in gw.wells.values():
    cas = gw.caseron_de_pozo(w)
    for p in w.points:
        if not p.entrenable or p.di is None or p.lito not in anclas: continue
        if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se) or p.se > PEP_MAX: continue
        if p.pp is None: continue
        reg.append((p.se, anclas[p.lito], p.di > FIN["umbral"], p.lito, cas, int(p.pp // 10 * 10)))
log(f"{len(reg)} registros")


def ajustes(x, y):
    """Cinco formas; R² en MPa. Devuelve {forma: {r2, coef, ecuacion}}."""
    x = np.asarray(x, float); y = np.asarray(y, float); out = {}
    sst = float(np.sum((y - y.mean()) ** 2))

    def r2(pred): return round(1 - float(np.sum((y - pred) ** 2)) / sst, 4) if sst > 0 else None
    a, b = np.polyfit(x, y, 1); out["lineal"] = {"r2": r2(a * x + b), "coef": [a, b], "ecuacion": f"UCS = {a:.5g}·PEP + {b:.5g}"}
    if x.size >= 4:
        c = np.polyfit(x, y, 2)
        out["parabolico"] = {"r2": r2(np.polyval(c, x)), "coef": list(c),
                             "ecuacion": f"UCS = {c[0]:.5g}·PEP² + {c[1]:.5g}·PEP + {c[2]:.5g}"}
    if (x > 0).all() and (y > 0).all():
        n, lk = np.polyfit(np.log(x), np.log(y), 1); k = np.exp(lk)
        out["potencial"] = {"r2": r2(k * x ** n), "coef": [k, n], "ecuacion": f"UCS = {k:.5g}·PEP^{n:.5g}"}
        m, lk = np.polyfit(x, np.log(y), 1); k = np.exp(lk)
        out["exponencial"] = {"r2": r2(k * np.exp(m * x)), "coef": [k, m], "ecuacion": f"UCS = {k:.5g}·e^({m:.5g}·PEP)"}
        a, b = np.polyfit(np.log(x), y, 1)
        out["logaritmico"] = {"r2": r2(a * np.log(x) + b), "coef": [a, b], "ecuacion": f"UCS = {a:.5g}·ln(PEP) + {b:.5g}"}
    for v in out.values(): v["coef"] = [float(t) for t in v["coef"]]
    return out


def resumen(x, y, n_reg=None, etiquetas=None):
    x = np.asarray(x, float); y = np.asarray(y, float)
    d = {"n_puntos": int(x.size), "n_registros": n_reg if n_reg is not None else int(x.size),
         "spearman": round(float(spearmanr(x, y).statistic), 3) if x.size >= 3 else None,
         "pearson": round(float(pearsonr(x, y).statistic), 3) if x.size >= 3 else None,
         "ajustes": ajustes(x, y)}
    if etiquetas is not None:
        d["puntos"] = [{"grupo": e, "pep_mediana": round(float(a), 1), "ucs_ref": float(b)} for e, a, b in zip(etiquetas, x, y)]
    return d


R = {"pep_max": PEP_MAX, "rop_min": gw.ROP_MIN_FISICA, "umbral_di": FIN["umbral"], "min_bin": MIN_BIN,
     "anclas": anclas, "conjuntos": {}}
rng = np.random.default_rng(42)
for conj in ("intacta", "todo"):
    sel = [r for r in reg if conj == "todo" or not r[2]]
    pep = np.array([r[0] for r in sel]); ur = np.array([r[1] for r in sel])
    C = {"registro": resumen(pep, ur)}
    for nombre, clave in (("litologia", lambda r: (r[3],)), ("litologia_caseron", lambda r: (r[3], r[4])),
                          ("litologia_estrato_pp", lambda r: (r[3], r[5]))):
        g = defaultdict(list)
        for r in sel: g[clave(r)].append(r[0])
        g = {k: v for k, v in g.items() if nombre != "litologia_estrato_pp" or len(v) >= MIN_BIN}
        ks = sorted(g)
        C[nombre] = resumen([np.median(g[k]) for k in ks], [anclas[k[0]] for k in ks],
                            n_reg=int(sum(len(g[k]) for k in ks)), etiquetas=[" · ".join(map(str, k)) for k in ks])
    ii = rng.choice(len(sel), min(30000, len(sel)), replace=False)
    C["muestra"] = {"pep": [round(float(pep[i]), 1) for i in ii], "ucs_ref": [float(ur[i]) for i in ii],
                    "lito": [sel[i][3] for i in ii]}
    R["conjuntos"][conj] = C
    for k, v in C.items():
        if k == "muestra": continue
        mejor = max(v["ajustes"].items(), key=lambda t: t[1]["r2"] if t[1]["r2"] is not None else -9)
        log(f"{conj:9s} {k:22s} n={v['n_puntos']:>7} ρ={v['spearman']} r={v['pearson']} "
            + " ".join(f"{f}={a['r2']}" for f, a in v["ajustes"].items()) + f"  → {mejor[0]}")
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
