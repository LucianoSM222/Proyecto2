"""Cálculo ÚNICO de la configuración final de la memoria (2026-10-22).

DI calibrado a 5 m (umbral 1,0, cuatro presiones sin el avance), emboquillado
2 m, percusión de empate 0,25, continuidad activa, bosque por mediana.
Todo número de las figuras finales sale de aquí; final_figs.py solo dibuja.
"""
import sys, os, time, json
from collections import defaultdict, Counter
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from sklearn.model_selection import GroupKFold, LeaveOneGroupOut
import geomech_wizard as gw
import cargar_caserones as cc

OUT = sys.argv[1]
T0 = time.time()
R = {"fecha": "2026-10-22"}


def log(m):
    print(f"[{time.time()-T0:6.0f}s] {m}", flush=True)


def guardar():
    json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)


# ── carga ───────────────────────────────────────────────────────────────────
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index(); gw.compute_di()
D = "/home/user/Proyecto2/test_data/reales/MPC Sondajes"
FILES = {"header": "MPC_header.csv", "survey": "MPC_survey.csv",
         "lithology": "MPC_lithology.csv", "structure": "MPC_structure.csv",
         "geomec": "MPC_geomec.csv", "density": "MPC_density.csv"}
gw.load_drillhole_csvs({k: open(os.path.join(D, v), "rb").read() for k, v in FILES.items()})
gw.refresh_drillhole_selection()
PTS = list(gw.all_points())
log(f"carga: {len(gw.wells)} pozos, {len(PTS)} puntos, {len(gw.drillholes)} sondajes")

# ── Tabla 6.1: sensibilidad del umbral de percusión de empate (sobre el total)
ORD = {wn: sorted(w.points, key=lambda p: p.largo) for wn, w in gw.wells.items()}
t61 = []
for u in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
    n = sum(len(gw.detectar_percusion_de_empate(ps, u)) for ps in ORD.values())
    t61.append({"umbral": u, "n": n, "pct": round(100 * n / len(PTS), 3)})
R["tabla_6_1"] = {"filas": t61, "teorico_largo_barra": round(len(PTS) * gw.MWD_PASO_NOMINAL_M / gw.LARGO_BARRA_M),
                  "largo_barra_m": gw.LARGO_BARRA_M, "n_total": len(PTS)}
log(f"tabla 6.1 OK: {t61[1]}")

# ── limpieza estándar ───────────────────────────────────────────────────────
R["limpieza"] = gw.aplicar_limpieza_estandar()
gw.compute_di()   # serie depurada: emboquillado y percusión de empate fuera del DI
R["limpieza"]["umbral_empate"] = gw.get_param("pp.percusion_empate_caida_rel")
log(f"limpieza: {R['limpieza']}")
guardar()

# ── Pearson: señales crudas y perfiles de varianza (entradas del DI) ────────
PAR5 = ["pp", "pr", "pd", "pf", "pa"]
crudo = {k: [] for k in PAR5}; var = {k: [] for k in PAR5}
for w in gw.wells.values():
    ps = w.points
    if len(ps) < 14: continue
    arrs = {k: np.array([getattr(p, k) for p in ps], float) for k in PAR5}
    if not all(np.isfinite(a).all() for a in arrs.values()): continue
    z2 = gw._z2_por_param(ps, 14, PAR5)
    if z2 is None: continue                      # serie depurada más corta que la ventana
    m = np.isfinite(z2[PAR5[0]])                 # misma serie que el DI
    for k in PAR5:
        crudo[k].append(arrs[k][m]); var[k].append(np.sqrt(z2[k][m]))
Mc = np.array([np.concatenate(crudo[k]) for k in PAR5]); Mv = np.array([np.concatenate(var[k]) for k in PAR5])
R["pearson"] = {"variables": [gw.CAL_SIGLAS[k] for k in PAR5], "n": int(Mc.shape[1]),
                "crudas": np.round(np.corrcoef(Mc), 3).tolist(),
                "perfiles_varianza": np.round(np.corrcoef(Mv), 3).tolist(),
                "nota_varianza": "|z| de la varianza móvil estandarizada por pozo (ventana 14)"}
del Mc, Mv, crudo, var
log("pearson OK"); guardar()

# ── Tabla 6.2: sensibilidad del radio de asignación del RQD ─────────────────
PARAMS_DI = ("pp", "pr", "pd", "pf")
t62 = []
for r in gw.RQD_RADIOS_TABLA:
    res = gw.calibrate_di_weights(radio_m=r, umbral=1.0, window=14, params=PARAMS_DI,
                                  registrar=False)
    fila = {"radio_m": r, "status": res.get("status")}
    if res.get("status") == "ok":
        fila.update({"n_pares": res["n_pares"], "n_sondajes": res["n_sondajes"],
                     "pesos": res["pesos"], "rho_ajuste": res["rho_ajuste"],
                     "rho_convencion": res["rho_convencion"],
                     "rho_validacion": res["rho_validacion"],
                     "pliegues": [{k: v for k, v in pl.items() if k != "pesos_pliegue"}
                                  for pl in res["validacion"]["pliegues"]],
                     "distancia_mediana_m": res.get("distancia_mediana_m")})
    else:
        fila.update({k: res.get(k) for k in ("motivo", "n_intervalos", "n_sondajes")})
    t62.append(fila); log(f"  radio {r}: {fila.get('pesos')} rho={fila.get('rho_ajuste')} val={fila.get('rho_validacion')}")
R["tabla_6_2"] = {"umbral": 1.0, "ventana": 14, "params": list(PARAMS_DI),
                  "n_candidatos": gw.CAL_N_MUESTRAS + 1, "semilla": gw.CAL_SEMILLA,
                  "min_puntos_intervalo": gw.get_param("rqd.min_puntos_intervalo"), "filas": t62}
guardar()

# ── DI calibrado a 5 m: se registra y se ACTIVA ─────────────────────────────
gw.confirmar_radio_rqd(5.0)
cal = gw.calibrate_di_weights(radio_m=5.0, umbral=1.0, window=14, params=PARAMS_DI,
                              nombre_variante="calibrada_RQD_5m", registrar=True)
gw.activar_di("calibrada_RQD_5m"); gw.compute_di()
R["di_vigente"] = {"variante": gw.di_activo(), "pesos": gw.di_config["weights"],
                   "window": gw.di_config["window"], "umbral": gw.di_threshold,
                   "rho_ajuste": cal["rho_ajuste"], "rho_validacion": cal["rho_validacion"],
                   "n_pares": cal["n_pares"], "n_sondajes": cal["n_sondajes"],
                   "sondajes": cal["sondajes"], "veredicto": cal["veredicto"]}
di_all = np.array([p.di for p in PTS if p.di is not None and np.isfinite(p.di)])
R["di_vigente"]["n_le_umbral"] = int((di_all <= 1.0).sum())
R["di_vigente"]["n_gt_umbral"] = int((di_all > 1.0).sum())
R["di_vigente"]["n_sin_di"] = len(PTS) - di_all.size
log(f"DI vigente: {R['di_vigente']['pesos']} ≤1:{R['di_vigente']['n_le_umbral']} >1:{R['di_vigente']['n_gt_umbral']}")
guardar()

# ── embudo de entrenamiento ─────────────────────────────────────────────────
X, y, groups, n_excl, funnel = gw._training_funnel(gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"])
R["embudo"] = funnel
cas_g = np.array([gw.caseron_de_pozo(gw.wells[g]) for g in groups])
lab = Counter(y.tolist())
lito_de = {}
for wn, w in gw.wells.items():
    pass
R["entrenamiento"] = {"n": int(len(y)), "n_pozos": int(len(set(groups.tolist()))),
                      "por_caseron": {c: {"n_puntos": int((cas_g == c).sum()),
                                          "n_pozos": int(len(set(groups[cas_g == c].tolist())))}
                                      for c in sorted(set(cas_g.tolist()))},
                      "etiquetas": {str(k): int(v) for k, v in sorted(lab.items())}}
log(f"embudo final: {funnel[-1]}  etiquetas={R['entrenamiento']['etiquetas']}")
guardar()

# ── perfil P20_H12: PP, marcas de empate, DI, tramos de RQD cercanos ────────
def perfil(wn, extra=()):
    ps = ORD[wn]
    d = {"largo": [round(p.largo, 3) for p in ps],
         "pp": [p.pp for p in ps], "di": [None if p.di is None else round(p.di, 4) for p in ps]}
    for k in extra:
        d[k] = [getattr(p, k) for p in ps]
    return d

P20 = "PCC_0042_PR01_TH_P20_H12"
pp20 = perfil(P20, ("lito", "estructura", "entrenable"))
pp20["empate_idx"] = gw.detectar_percusion_de_empate(ORD[P20], gw.get_param("pp.percusion_empate_caida_rel"))
XYZ = np.array([[p.este, p.norte, p.cota] for p in ORD[P20]])
tramos = []
for iv in gw._intervalos_rqd_sondaje():
    dd = np.linalg.norm(XYZ - iv["centro"], axis=1); k = int(dd.argmin())
    if dd[k] <= 5.0:
        L = np.array(pp20["largo"]); D_ = np.array([np.nan if v is None else v for v in pp20["di"]])
        m = np.abs(L - L[k]) <= max(iv["largo_m"], 0.2) / 2
        m &= np.isfinite(D_)   # emboquillado y empate no tienen DI
        rq = gw._rqd_deere_np(L[m], D_[m], gw.di_threshold) if m.sum() >= 2 else None
        tramos.append({"sondaje": iv["sondaje"], "desde": iv["desde"], "hasta": iv["hasta"],
                       "rqd": iv["rqd"], "dist_m": round(float(dd[k]), 2),
                       "largo_pozo_m": round(float(L[k]), 2), "largo_tramo_m": iv["largo_m"],
                       "rqd_mwd": None if rq is None else round(float(rq), 1)})
pp20["tramos_rqd"] = tramos
R["pozo_P20_H12"] = pp20
log(f"P20_H12: {len(pp20['empate_idx'])} marcas de empate, {len(tramos)} tramos RQD ≤5 m")
guardar()

# ── modelo de producción y validaciones (mediana) ───────────────────────────
res = gw.train_rf()
R["train_rf"] = {k: res.get(k) for k in ("cv_r2_mean", "cv_r2_std", "r2_train", "rmse_train",
                                         "feat_imp", "feat_imp_motivo", "n_train", "cv_warning")}
log(f"train_rf: cv={res.get('cv_r2_mean')} imp={res.get('feat_imp')}")
est0 = gw.rf_model.estimators_[0].tree_


def nodo(i, prof):
    if i == -1 or prof > 2: return None
    hoja = est0.children_left[i] == -1
    d = {"n_muestras": int(est0.n_node_samples[i]), "valor_UCS": round(float(est0.value[i].ravel()[0]), 1),
         "hoja": bool(hoja)}
    if not hoja:
        d["variable"] = gw.ML_LABELS[int(est0.feature[i])]; d["umbral"] = round(float(est0.threshold[i]), 3)
        if prof < 2:
            d["izq"] = nodo(int(est0.children_left[i]), prof + 1); d["der"] = nodo(int(est0.children_right[i]), prof + 1)
    return d
R["arbol_ejemplo"] = {"indice": 0, "profundidad_real": int(est0.max_depth), "n_nodos": int(est0.node_count),
                      "raiz": nodo(0, 0)}
guardar()

gk = gw.validacion_por_pliegue(GroupKFold(n_splits=5), groups, X, y)
R["groupkfold"] = {"pliegues": gk, "r2_medio": round(float(np.mean([f["r2"] for f in gk if f["r2"] is not None])), 3),
                   "rmse_medio": round(float(np.mean([f["rmse"] for f in gk])), 2),
                   "spearman_medio": round(float(np.mean([f["spearman"] for f in gk if f["spearman"] is not None])), 3)}
log(f"GroupKFold: {R['groupkfold']['r2_medio']} rmse {R['groupkfold']['rmse_medio']}")
guardar()
lo = gw.validacion_por_pliegue(LeaveOneGroupOut(), cas_g, X, y, etiqueta="caseron")
val = [f["r2"] for f in lo if f["r2"] is not None]
R["loocv_caseron"] = {"pliegues": lo, "r2_medio_definidos": round(float(np.mean(val)), 3) if val else None,
                      "n_definidos": len(val), "rmse_medio": round(float(np.mean([f["rmse"] for f in lo])), 2)}
log(f"LOOCV-Caserón: {lo}")
guardar()

# ── predicción a todos los puntos ───────────────────────────────────────────
gw.predict_all_wells()
anch = defaultdict(list)
for p in PTS:
    if p.ucs_ml_p10 is not None and p.ucs_ml_p90 is not None and p.di is not None:
        anch["fract" if (p.di is not None and p.di > 1.0) else "intacta"].append(p.ucs_ml_p90 - p.ucs_ml_p10)
R["p10_p90"] = {k: {"n": len(v), "media": round(float(np.mean(v)), 2), "mediana": round(float(np.median(v)), 2)}
                for k, v in anch.items()}

anclas = gw._anclas_por_litologia()   # UCS referencial de cada litología

# ── comparación de algoritmos (GroupKFold) ──────────────────────────────────
R["comparacion"] = gw.model_comparison_report(with_se=True)
log(f"comparación: {[(r['modelo'], r.get('r2_train_mean'), r['r2_mean']) for r in R['comparacion'].get('filas', R['comparacion'].get('rows', []))] if isinstance(R['comparacion'], dict) else R['comparacion']}")
guardar()

# ── dispersión PEP vs UCS predicha; UCS lab vs ML por litología ─────────────
rng = np.random.default_rng(42)
sc = {"intacta": [], "fracturada": []}
porlito = defaultdict(list)
for p in PTS:
    if p.ucs_ml is None or p.di is None or p.se is None or not np.isfinite(p.se) or p.vel is None or p.vel < gw.ROP_MIN_FISICA: continue
    k = "fracturada" if (p.di is not None and p.di > 1.0) else "intacta"
    sc[k].append((p.se, p.ucs_ml, p.lito))
    if k == "intacta" and p.entrenable: porlito[p.lito].append(p.ucs_ml)
R["pep_vs_ucs"] = {}
for k, v in sc.items():
    ii = rng.choice(len(v), min(25000, len(v)), replace=False)
    R["pep_vs_ucs"][k] = {"n": len(v), "pep": [round(v[i][0], 1) for i in ii],
                          "ucs_ml": [v[i][1] for i in ii], "lito": [v[i][2] for i in ii]}
R["ucs_por_litologia"] = {}
for lito, v in porlito.items():
    v = np.sort(np.array(v))
    R["ucs_por_litologia"][lito] = {"n": int(v.size), "ancla": anclas.get(lito),
                                    "p10": float(np.percentile(v, 10)), "p50": float(np.median(v)),
                                    "p90": float(np.percentile(v, 90)),
                                    "curva": v[np.linspace(0, v.size - 1, 400).astype(int)].round(1).tolist()}
log(f"ucs por litología: {[(k, v['ancla'], round(v['p50'],1)) for k, v in R['ucs_por_litologia'].items()]}")
guardar()

# ── PEP por litología × estrato de PP (figura PEP vs UCS lab, ROP, PP) ──────
cel = defaultdict(lambda: {"pep": [], "rop": []})
for p in PTS:
    if not p.entrenable or p.lito not in anclas or p.di is None or p.di > 1.0: continue
    if p.vel is None or p.vel < gw.ROP_MIN_FISICA or p.se is None or not np.isfinite(p.se) or p.pp is None: continue
    b = int(p.pp // 10 * 10)
    cel[(p.lito, b)]["pep"].append(p.se); cel[(p.lito, b)]["rop"].append(p.vel)
R["pep_estratos"] = [{"lito": l, "ucs_lab": anclas[l], "pp_bin": b, "n": len(v["pep"]),
                      "pep_mediana": float(np.median(v["pep"])), "rop_mediana": float(np.median(v["rop"])),
                      "pep_cv": float(np.std(v["pep"]) / np.mean(v["pep"]))}
                     for (l, b), v in sorted(cel.items()) if len(v["pep"]) >= gw.get_param("pp.min_puntos_bin")]
guardar()

# ── concordancia DI ↔ cruces de malla en PCC_1541 ───────────────────────────
RADIO = 3.0
cruces, rango, perf = {}, {}, {}
for wn, ww in gw.wells.items():
    if gw.caseron_de_pozo(ww) != "PCC_1541": continue
    p2 = ORD[wn]
    if len(p2) < 2: continue
    l2 = np.array([p.largo for p in p2])
    perf[wn] = (l2, np.array([p.di if p.di is not None else np.nan for p in p2]))
    rango[wn] = (float(l2[0]), float(l2[-1]))
    cr, prev = [], None
    for p in p2:
        if prev is not None and p.dominio != prev[1] and p.dominio and prev[1]:
            cr.append((prev[0] + p.largo) / 2.0)
        prev = (p.largo, p.dominio)
    cruces[wn] = np.array(cr)
pcz = [wn for wn in cruces if len(cruces[wn])]


def picos_de(wn, u):
    l2, d2 = perf[wn]
    ix = np.flatnonzero(np.nan_to_num(d2, nan=-1) > u)
    if ix.size == 0: return np.array([])
    out, ult = [l2[ix[0]]], l2[ix[0]]
    for i in ix[1:]:
        if l2[i] - ult >= gw.DI_PICOS_MIN_GAP_M: out.append(l2[i])
        ult = l2[i]
    return np.array(out)


PR = []
rng = np.random.default_rng(42)
for u in [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]:
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
    for _ in range(30):
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
    a, b = picos_de(wn, 1.0), cruces[wn]
    if a.size and b.size:
        j = np.argmin(np.abs(a[:, None] - b[None, :]), axis=1); dl.extend((a - b[j]).tolist())
R["concordancia_1541"] = {"radio_m": RADIO, "pr": PR, "desfases": [round(x, 3) for x in dl],
                          "n_pozos": len(pcz), "n_picos_total_1541": int(sum(picos_de(wn, 1.0).size for wn in perf))}
log(f"concordancia: {PR[2]}")
guardar()

# ── perfil PCS_1043_PR01_TH_P07_H4 ──────────────────────────────────────────
P07 = "PCS_1043_PR01_TH_P07_H4"
if P07 in ORD:
    R["pozo_P07_H4"] = perfil(P07, ("vel", "pa", "pd", "pr", "pf", "se", "ucs_ml", "ucs_ml_p10",
                                    "ucs_ml_p90", "lito", "estructura", "dominio"))
guardar()

# ── dominios y ranking de 5 recomendaciones históricas ──────────────────────
ng = gw.compute_domain_groups()
grupos = sorted(gw.domain_groups, key=lambda g: -g.get("count", g.get("n", 0)))
R["dominios"] = {"n_grupos": ng if isinstance(ng, int) else len(gw.domain_groups),
                 "tol_ucs": gw.DOMINIO_TOL_UCS, "tol_di": gw.DOMINIO_TOL_DI, "tramo_m": gw.DOMINIO_TRAMO_M,
                 "grupos": [{k: g.get(k) for k in g if not isinstance(g.get(k), (list, dict))} for g in grupos[:15]],
                 "n_puntos_con_grupo": sum(1 for p in PTS if p.grupo)}
log(f"dominios: {R['dominios']['n_grupos']} grupos; top: {R['dominios']['grupos'][:3]}")
g0 = grupos[0]["id"]
R["ranking"] = {"grupo": g0, "criterios": {}}
for met in ("min_se_cv", "min_se", "max_rop"):
    R["ranking"]["criterios"][met] = gw.top_drilling(g0, n=5, method=met)
guardar()

# ── modelo de bloques: sección y clasificación DI × UCS ─────────────────────
bm = gw.interpolate_block_model()
R["bloques"] = {"status": bm.get("status"), "n_bloques": bm.get("n_bloques"), "bloque_m": bm.get("bloque_m"),
                "por_caseron": bm.get("por_caseron"), "fuente_ucs": bm.get("fuente_ucs")}
if bm.get("status") == "ok":
    bl = bm["bloques"]
    R["bloques"]["resumen"] = gw.tronadura_resumen(bm)
    R["bloques"]["resumen"].pop("modelo_ucs", None)

    def cdi(d):
        return None if d is None else ("sana (DI ≤ 1)" if d <= 1.0 else "transición (1 < DI ≤ 1,5)" if d <= 1.5 else "fracturada (DI > 1,5)")
    tab = Counter((cdi(b.get("di")), b.get("banda")) for b in bl)
    R["bloques"]["tabla"] = [{"di": a, "banda": b, "n": n} for (a, b), n in tab.items()]
    N0 = 6958905.0
    sec = [b for b in bl if b["caseron"] == "PCC_0042" and abs(b["y"] - N0) <= bm["bloque_m"] / 2 + 1e-6]
    if not sec:
        ys = sorted({b["y"] for b in bl if b["caseron"] == "PCC_0042"}, key=lambda v: abs(v - N0))
        sec = [b for b in bl if b["caseron"] == "PCC_0042" and b["y"] == ys[0]]
    R["bloques"]["seccion"] = {"norte": sec[0]["y"] if sec else None,
                               "x": [b["x"] for b in sec], "z": [b["z"] for b in sec],
                               "di": [b["di"] for b in sec], "ucs": [b["ucs"] for b in sec]}
    log(f"bloques: {len(bl)}; sección N={R['bloques']['seccion']['norte']} con {len(sec)} bloques")
guardar()

# ── estado para las figuras que necesitan el proyecto entero ────────────────
gw.save_project(os.path.join(os.path.dirname(OUT), "proyecto_final.gwz"))
log("FIN")
