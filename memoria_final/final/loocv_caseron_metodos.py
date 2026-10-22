"""Los cuatro métodos de UCS bajo LOOCV-Caserón: se deja UN caserón fuera, se
ajusta con los otros tres y se predice cada registro del excluido. Misma
configuración que final_calc.py (limpieza estándar, DI calibrado a 5 m con los
pesos de final.json) y mismos registros que el bosque (embudo de entrenamiento).
Uso: python3 loocv_caseron_metodos.py final.json loocv_caseron_metodos.json

Métodos (los mismos de la herramienta, con el caserón en vez de la litología
como unidad que se deja fuera):
- Línea base (media litología): media de las UCS referenciales de las
  litologías presentes en los caserones de ajuste. Ignora el MWD; es constante.
- Banda por unidad: centro = curva PEP→UCS ajustada SIN el caserón, evaluada en
  la PEP mediana de la litología dentro del caserón excluido; cada registro se
  aparta del centro según su PEP (z robusto × σ de la banda de su unidad).
- Relación directa PEP↔UCS: la misma curva, un valor por litología del
  caserón excluido (su PEP mediana).
- ML (Random Forest): RF_PRODUCCION, predicción = mediana de los 200 árboles.
Las métricas van por registro contra la UCS referencial de su litología.
"""
import sys, json, time
from collections import defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
from scipy.stats import spearmanr, pearsonr
from sklearn.ensemble import RandomForestRegressor
import geomech_wizard as gw
import cargar_caserones as cc

SRC, OUT = sys.argv[1], sys.argv[2]
T0 = time.time()
FIN = json.load(open(SRC, encoding="utf-8"))["di_vigente"]


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

X, y, groups, _, _ = gw._training_funnel(gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"])
cas = np.array([gw.caseron_de_pozo(gw.wells[g]) for g in groups])
anclas = gw._anclas_por_litologia()
lito_de = {round(v, 3): k for k, v in anclas.items()}
lito = np.array([lito_de[round(float(v), 3)] for v in y])
se = X[:, gw.ML_FEATURES.index("se")]
LO, HI = gw.UCS_CONFIG["physical_min"], gw.UCS_CONFIG["physical_max"]

# PEP de cada litología por caserón, con el mismo criterio que la herramienta
# (_puntos_de_litologia): entrenable, ROP ≥ mínimo físico, roca intacta.
pep_cl = defaultdict(list)
for w in gw.wells.values():
    c = gw.caseron_de_pozo(w)
    for p in w.points:
        if (p.lito in anclas and p.entrenable and p.se is not None and np.isfinite(p.se)
                and p.vel is not None and np.isfinite(p.vel) and p.vel >= gw.ROP_MIN_FISICA
                and (p.di is None or p.di <= gw.di_threshold)):
            pep_cl[(c, p.lito)].append(p.se)
pep_cl = {k: np.array(v) for k, v in pep_cl.items()}
sigma_banda = {l: gw.ucs_escala(gw.attr_registry.get(l)).get("sigma") for l in anclas}
log(f"σ de banda: {sigma_banda}")


def escala(v):
    """(mediana, σ robusta) como _se_escala_lito: mitad del rango p16–p84."""
    s = float((np.percentile(v, 84) - np.percentile(v, 16)) / 2.0)
    return float(np.median(v)), (s if s > 1e-9 else 1.0)


def metricas(yt, pred):
    unica = np.unique(yt).size < 2; const = np.unique(pred).size < 2
    motivo = ("una sola etiqueta en la prueba" if unica else
              "predicción constante" if const else None)
    return {"n": int(yt.size), "rmse": round(float(np.sqrt(np.mean((yt - pred) ** 2))), 2),
            "mae": round(float(np.mean(np.abs(yt - pred))), 2),
            "pearson": None if motivo else round(float(pearsonr(yt, pred).statistic), 3),
            "spearman": None if motivo else round(float(spearmanr(yt, pred).statistic), 3),
            "motivo_correlacion": motivo}


R = {"metodos": ["linea_base", "banda", "relacion", "ml"], "pliegues": []}
for c in sorted(set(cas.tolist())):
    te, tr = cas == c, cas != c
    yt, lt = y[te], lito[te]
    lit_tr = sorted(set(lito[tr].tolist()))
    # curva PEP → UCS con los caserones de ajuste
    pares = []
    for l in lit_tr:
        v = np.concatenate([pep_cl[(k, l)] for k in set(cas[tr].tolist()) if (k, l) in pep_cl])
        pares.append((float(np.median(v)), anclas[l]))
    curva = gw._ajustar_curva_se_ucs(pares)
    ses = [a for a, _ in pares]
    pred = {"linea_base": np.full(yt.size, float(np.mean([anclas[l] for l in lit_tr])))}
    pb, pr_, extrap = np.empty(yt.size), np.empty(yt.size), []
    for l in sorted(set(lt.tolist())):
        m = lt == l
        med, sig = escala(pep_cl[(c, l)])
        centro = gw._aplicar_curva(curva, med)
        if med < min(ses) or med > max(ses):
            extrap.append({"litologia": l, "pep_mediana": round(med, 1),
                           "rango_ajuste": [round(min(ses), 1), round(max(ses), 1)]})
        pr_[m] = centro
        pb[m] = centro + (se[te][m] - med) / sig * sigma_banda[l]
    pred["relacion"] = np.clip(pr_, LO, HI); pred["banda"] = np.clip(pb, LO, HI)
    rf = RandomForestRegressor(**gw.RF_PRODUCCION).fit(X[tr], y[tr])
    pred["ml"] = gw.prediccion_mediana(rf, X[te])
    fila = {"caseron": c, "n_prueba": int(te.sum()), "n_etiquetas": int(np.unique(yt).size),
            "curva": {"forma": curva["forma"], "coef": [round(float(k), 6) for k in curva["coef"]],
                      "pares": [(round(a, 1), b) for a, b in pares]},
            "extrapolacion": extrap,
            "metricas": {k: metricas(yt, v) for k, v in pred.items()}}
    R["pliegues"].append(fila)
    log(f"{c}: " + " · ".join(f"{k} rmse {v['rmse']} r {v['pearson']} ρ {v['spearman']}" for k, v in fila["metricas"].items()))
    json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)

for k in R["metodos"]:
    def media(cl):
        v = [f["metricas"][k][cl] for f in R["pliegues"] if f["metricas"][k][cl] is not None]
        return round(float(np.mean(v)), 3) if v else None
    R.setdefault("medias", {})[k] = {"rmse": media("rmse"), "mae": media("mae"),
                                     "pearson": media("pearson"), "spearman": media("spearman")}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)
log(f"medias: {R['medias']}")
