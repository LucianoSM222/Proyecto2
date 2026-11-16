"""Correlación de rangos de Spearman entre el DI medio y el RQD de sondaje, por
caserón y en conjunto. Configuración final (limpieza estándar, serie depurada,
pesos calibrados a 5 m de final.json).

Apareo UNO A UNO, como la calibración (_preparar_intervalos_calibracion): cada
tramo de RQD con el registro MWD entrenable más cercano a su centro, buscado
DENTRO de cada caserón; el DI medio es el promedio del DI sobre el tramo de ese
pozo con el largo del intervalo, con al menos rqd.min_puntos_intervalo registros.
Uso: python3 di_rqd_caserones.py final.json di_rqd_caserones.json
"""
import sys, os, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]
RADIOS = (5.0, 10.0, 25.0)


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
gw.aplicar_limpieza_estandar()
gw.create_di_variant("calibrada_RQD_5m", FIN["pesos"], window=FIN["window"], threshold=FIN["umbral"])
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
PISO = max(2, int(gw.get_param("rqd.min_puntos_intervalo")))
log(f"carga y DI listos · piso {PISO} registros por tramo")

IV = gw._intervalos_rqd_sondaje()
cas_pts = {}
for wn, w in gw.wells.items():
    c = gw.caseron_de_pozo(w)
    for i, p in enumerate(w.points):
        if p.entrenable:
            cas_pts.setdefault(c, ([], []))
            cas_pts[c][0].append((p.este, p.norte, p.cota)); cas_pts[c][1].append((wn, i))
cas_pts = {c: (np.array(a), b) for c, (a, b) in cas_pts.items()}

pares = []   # un tramo de RQD por caserón, con su distancia y su DI medio
for iv in IV:
    for c, (P, meta) in cas_pts.items():
        d = np.linalg.norm(P - iv["centro"], axis=1); k = int(np.argmin(d))
        wn, i = meta[k]; w = gw.wells[wn]; lc = w.points[i].largo
        media = max(iv["largo_m"], 0.2) / 2.0
        di = [p.di for p in w.points if p.entrenable and abs(p.largo - lc) <= media and p.di is not None]
        pares.append({"caseron": c, "sondaje": iv["sondaje"], "desde": iv["desde"], "hasta": iv["hasta"],
                      "rqd": iv["rqd"], "dist_m": round(float(d[k]), 2), "pozo": wn, "n_di": len(di),
                      "di_medio": round(float(np.mean(di)), 4) if len(di) >= PISO else None})

R = {"n_tramos_rqd": len(IV), "sondajes_rqd": sorted({iv["sondaje"] for iv in IV}), "piso": PISO,
     "radios": list(RADIOS), "cobertura": {}, "spearman": [], "pares": pares}
for c in sorted(cas_pts):
    dd = np.array([p["dist_m"] for p in pares if p["caseron"] == c])
    R["cobertura"][c] = {"dist_min_m": round(float(dd.min()), 1), "dist_mediana_m": round(float(np.median(dd)), 1),
                         **{f"tramos_a_{r:g}m": int((dd <= r).sum()) for r in RADIOS}}


def rho(sel):
    sel = [p for p in sel if p["di_medio"] is not None]
    fila = {"n_pares": len(sel), "n_sondajes": len({p["sondaje"] for p in sel})}
    if len(sel) < 5 or len({p["rqd"] for p in sel}) < 2:
        return {**fila, "rho": None, "p": None, "motivo": "menos de 5 pares o RQD sin variación"}
    r = spearmanr([p["di_medio"] for p in sel], [p["rqd"] for p in sel])
    return {**fila, "rho": round(float(r.statistic), 3), "p": round(float(r.pvalue), 4), "motivo": None}


for r in RADIOS:
    for c in sorted(cas_pts):
        R["spearman"].append({"radio_m": r, "caseron": c, **rho([p for p in pares if p["caseron"] == c and p["dist_m"] <= r])})
    # conjunto: cada tramo una sola vez, con el caserón más cercano dentro del radio
    mejor = {}
    for p in pares:
        if p["dist_m"] <= r:
            k = (p["sondaje"], p["desde"])
            if k not in mejor or p["dist_m"] < mejor[k]["dist_m"]: mejor[k] = p
    R["spearman"].append({"radio_m": r, "caseron": "4 caserones", **rho(list(mejor.values()))})
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)
log(f"cobertura: {R['cobertura']}")
for f in R["spearman"]: log(f)
