"""PRUEBA (no modifica nada): emboquillado de P20_H12 hasta 4,3 m; DI del barreno con los pesos vigentes."""
import sys, os, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np, geomech_wizard as gw, cargar_caserones as cc
CORTE = 4.3; WN = "PCC_0042_PR01_TH_P20_H12"; OUT = sys.argv[1]
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project("proyecto_final.gwz")
D = "/home/user/Proyecto2/test_data/reales/MPC Sondajes"
FILES = {"header": "MPC_header.csv", "survey": "MPC_survey.csv", "lithology": "MPC_lithology.csv",
         "structure": "MPC_structure.csv", "geomec": "MPC_geomec.csv", "density": "MPC_density.csv"}
if not gw.drillholes:
    gw.load_drillhole_csvs({k: open(os.path.join(D, v), "rb").read() for k, v in FILES.items()})
    gw.refresh_drillhole_selection()
w = gw.wells[WN]; ps = sorted(w.points, key=lambda p: p.largo)
antes = [p.di for p in ps]
for p in ps:
    if p.largo < CORTE: p.emboquillado = True
cfg = gw.di_config
di = gw.di_profile_serie(w.points, cfg["window"], cfg["params"], cfg["weights"])
for p, v in zip(w.points, di): p.di = None if not np.isfinite(v) else float(v)
F = json.load(open("final.json", encoding="utf-8"))
pp20 = {"largo": [round(p.largo, 3) for p in ps], "pp": [p.pp for p in ps],
        "di": [None if p.di is None else round(p.di, 4) for p in ps],
        "lito": [p.lito for p in ps], "estructura": [p.estructura for p in ps], "entrenable": [p.entrenable for p in ps],
        "empate_idx": F["pozo_P20_H12"]["empate_idx"]}
XYZ = np.array([[p.este, p.norte, p.cota] for p in ps]); L = np.array(pp20["largo"])
Dv = np.array([np.nan if v is None else v for v in pp20["di"]]); tramos = []
for iv in gw._intervalos_rqd_sondaje():
    dd = np.linalg.norm(XYZ - iv["centro"], axis=1); k = int(dd.argmin())
    if dd[k] <= 5.0:
        m = (np.abs(L - L[k]) <= max(iv["largo_m"], 0.2) / 2) & np.isfinite(Dv)
        rq = gw._rqd_deere_np(L[m], Dv[m], gw.di_threshold) if m.sum() >= 2 else None
        tramos.append({"sondaje": iv["sondaje"], "desde": iv["desde"], "hasta": iv["hasta"], "rqd": iv["rqd"],
                       "dist_m": round(float(dd[k]), 2), "largo_pozo_m": round(float(L[k]), 2),
                       "largo_tramo_m": iv["largo_m"], "rqd_mwd": None if rq is None else round(float(rq), 1)})
pp20["tramos_rqd"] = tramos
json.dump({"pozo_P20_H12": pp20, "di_vigente": F["di_vigente"]}, open(OUT, "w"), ensure_ascii=False, default=float)
a = np.array([np.nan if v is None else v for v in antes]); b = Dv
print("DI>1 antes %.1f%% (n %d)  ahora %.1f%% (n %d)  max antes %.2f ahora %.2f" % (
    100 * np.nanmean(a[np.isfinite(a)] > 1), np.isfinite(a).sum(), 100 * np.nanmean(b[np.isfinite(b)] > 1), np.isfinite(b).sum(), np.nanmax(a), np.nanmax(b)))
print("rqd_mwd antes", sorted({t["rqd_mwd"] for t in F["pozo_P20_H12"]["tramos_rqd"]}), "ahora", sorted({t["rqd_mwd"] for t in tramos}))
