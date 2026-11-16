import sys, os, json
sys.path.insert(0, "/home/user/Proyecto2"); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, geomech_wizard as gw, cargar_caserones as cc, est_caseron as ec
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project("/home/user/Proyecto2/memoria_final/final/proyecto_final.gwz")
D = "/home/user/Proyecto2/test_data/reales/MPC Sondajes"
FILES = {"header": "MPC_header.csv", "survey": "MPC_survey.csv", "lithology": "MPC_lithology.csv",
         "structure": "MPC_structure.csv", "geomec": "MPC_geomec.csv", "density": "MPC_density.csv"}
if not gw.drillholes:
    gw.load_drillhole_csvs({k: open(os.path.join(D, v), "rb").read() for k, v in FILES.items()})
    gw.refresh_drillhole_selection()
gw.confirmar_radio_rqd(5.0)
PAR = ("pp", "pr", "pd", "pf"); W0 = dict(gw.di_config["weights"])
def pr_conc(cas, u=1.0, R=3.0):
    op = tp = oc = tc = 0
    for w in gw.wells.values():
        if gw.caseron_de_pozo(w) != cas: continue
        p2 = sorted(w.points, key=lambda p: p.largo)
        if len(p2) < 2: continue
        l2 = np.array([p.largo for p in p2]); d2 = np.array([np.nan if p.di is None else p.di for p in p2])
        cr, prev = [], None
        for p in p2:
            if prev is not None and p.dominio != prev[1] and p.dominio and prev[1]: cr.append((prev[0] + p.largo) / 2)
            prev = (p.largo, p.dominio)
        b = np.array(cr)
        if not b.size: continue
        ix = np.flatnonzero(np.nan_to_num(d2, nan=-1) > u); a = []
        if ix.size:
            a, ult = [l2[ix[0]]], l2[ix[0]]
            for i in ix[1:]:
                if l2[i] - ult >= gw.DI_PICOS_MIN_GAP_M: a.append(l2[i])
                ult = l2[i]
        a = np.array(a)
        if a.size:
            dd = np.abs(a[:, None] - b[None, :]); op += int((dd.min(1) <= R).sum()); tp += a.size; oc += int((dd.min(0) <= R).sum())
        tc += b.size
    return {"precision": round(100 * op / tp, 1), "recall": round(100 * oc / tc, 1), "zonas": tp, "cruces": tc}
def resumen(tag):
    r = {"pr": {c: pr_conc(c) for c in ("PCC_0042", "PCC_1541", "PCS_1043")}}
    por_b = []
    for w in gw.wells.values():
        d = np.array([p.di for p in w.points if p.di is not None and np.isfinite(p.di)])
        if d.size > 100: por_b.append(100 * (d > 1).mean())
    allv = np.array([p.di for p in gw.all_points() if p.di is not None and np.isfinite(p.di)])
    r["pct_discontinua"] = round(100 * float((allv > 1).mean()), 2)
    r["pct_por_barreno"] = {"p10": round(float(np.percentile(por_b, 10)), 1), "mediana": round(float(np.median(por_b)), 1),
                            "p90": round(float(np.percentile(por_b, 90)), 1), "min": round(min(por_b), 1), "max": round(max(por_b), 1)}
    cas = {}
    for c in ("PCC_0042", "PCC_1541", "PCS_1043", "PCS_1059"):
        v = np.array([p.di for w in gw.wells.values() if gw.caseron_de_pozo(w) == c for p in w.points if p.di is not None and np.isfinite(p.di)])
        cas[c] = round(100 * float((v > 1).mean()), 1)
    r["pct_por_caseron"] = cas; print(tag, json.dumps(r, ensure_ascii=False), flush=True); return r
R = {"por_barreno_vigente": dict(pesos=W0, **resumen("barreno"))}
ec.preparar(gw, gw.caseron_de_pozo); ec.parchear(gw)
gw.compute_di(); R["caseron_pesos_vigentes"] = dict(pesos=W0, **resumen("caseron_vigentes"))
cal = gw.calibrate_di_weights(radio_m=5.0, umbral=1.0, window=14, params=PAR, nombre_variante="prueba_est_caseron", registrar=True)
gw.activar_di("prueba_est_caseron"); gw.compute_di()
R["caseron_recalibrado"] = dict(pesos=cal["pesos"], rho_ajuste=cal["rho_ajuste"], rho_validacion=cal["rho_validacion"],
                                n_pares=cal["n_pares"], veredicto=cal.get("veredicto"), **resumen("caseron_recal"))
print("CAL", cal["pesos"], cal["rho_ajuste"], cal["rho_validacion"], flush=True)
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, indent=1, default=float)
