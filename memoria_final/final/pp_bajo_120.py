"""¿Dónde y en qué condición aparecen los registros con PP < 120 bar que se
salen de la tendencia? Se comparan contra la operación normal (PP 140–200 bar)
en: concentración por pozo y caserón, posición en el pozo, persistencia
(rachas), demás presiones, ROP/PEP, orientación del tiro y vecindad de
discontinuidades. Configuración final (limpieza estándar, serie depurada,
pesos a 5 m). Registros entrenables de roca continua con UCS referencial y
ROP ≥ mínimo físico, como la figura de PEP/ROP por intervalo de PP.
Uso: python3 pp_bajo_120.py final.json pp_bajo_120.json
"""
import sys, json, time
from collections import Counter, defaultdict
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
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
anclas = gw._anclas_por_litologia()
log("carga y DI listos")

GRUPOS = {"bajo": (90, 120), "normal": (140, 200)}
reg = defaultdict(list)          # grupo -> lista de dicts
rachas = []                      # largo (n registros) de cada racha continua de PP < 120 en un pozo
por_pozo = {}
for wn, w in gw.wells.items():
    pts = sorted(w.points, key=lambda p: p.largo)
    if len(pts) < 2: continue
    L = pts[-1].largo; cas = gw.caseron_de_pozo(w)
    dz = pts[-1].cota - pts[0].cota; dh = np.hypot(pts[-1].este - pts[0].este, pts[-1].norte - pts[0].norte)
    incl = float(np.degrees(np.arctan2(dz, dh)))          # + ascendente, − descendente
    n_ok = n_bajo = 0; racha = 0
    for i, p in enumerate(pts):
        ok = (p.entrenable and p.lito in anclas and p.di is not None and p.di <= FIN["umbral"]
              and p.vel is not None and p.vel >= gw.ROP_MIN_FISICA and p.se is not None and np.isfinite(p.se) and p.pp is not None)
        bajo = ok and 90 <= p.pp < 120
        if bajo: racha += 1
        elif racha: rachas.append(racha); racha = 0
        if not ok: continue
        n_ok += 1; n_bajo += bajo
        for g, (lo, hi) in GRUPOS.items():
            if lo <= p.pp < hi:
                # vecindad: ¿hay DI > umbral a menos de 0,5 m?
                vec = [q.di for q in pts[max(0, i - 25): i + 26] if q.di is not None]
                reg[g].append({"pozo": wn, "caseron": cas, "lito": p.lito, "largo": p.largo, "rel": p.largo / L if L else None,
                               "largo_pozo": L, "incl": incl, "pp": p.pp, "pa": p.pa, "pr": p.pr, "pd": p.pd, "pf": p.pf,
                               "rop": p.vel, "pep": p.se, "di_vecino_alto": bool(vec and max(vec) > FIN["umbral"])})
    if racha: rachas.append(racha)
    if n_ok: por_pozo[wn] = {"caseron": cas, "n": n_ok, "n_bajo": n_bajo, "incl": incl, "largo": L}


def med(v): return round(float(np.median(v)), 3) if len(v) else None


R = {"grupos": {}, "rachas": {}, "pozos": {}}
for g, v in reg.items():
    a = lambda k: np.array([x[k] for x in v], float)
    lar, rel, inc = a("largo"), a("rel"), a("incl")
    cuenta_pozo = Counter(x["pozo"] for x in v)
    top10 = sum(n for _, n in cuenta_pozo.most_common(10))
    R["grupos"][g] = {
        "n": len(v), "n_pozos": len(cuenta_pozo), "pct_top10_pozos": round(100 * top10 / len(v), 1),
        "por_caseron": {k: round(100 * n / len(v), 1) for k, n in sorted(Counter(x["caseron"] for x in v).items())},
        "por_litologia": {k: round(100 * n / len(v), 1) for k, n in sorted(Counter(x["lito"] for x in v).items())},
        "largo_mediana_m": med(lar), "pct_2_a_4m": round(100 * float(np.mean((lar >= 2) & (lar < 4))), 1),
        "pct_ultimo_metro": round(100 * float(np.mean(a("largo_pozo") - lar <= 1.0)), 1),
        "pos_relativa_mediana": med(rel), "pct_ascendentes": round(100 * float(np.mean(inc > 0)), 1),
        "inclinacion_mediana_deg": med(inc),
        "medianas": {k: med(a(k)) for k in ("pp", "pa", "pr", "pd", "pf", "rop", "pep")},
        "pct_con_DI_alto_a_0_5m": round(100 * float(np.mean([x["di_vecino_alto"] for x in v])), 1),
        "top_pozos": cuenta_pozo.most_common(10)}
ra = np.array(rachas)
R["rachas"] = {"n_rachas": int(ra.size), "mediana_registros": med(ra), "pct_registros_en_rachas_ge_50": round(100 * float(ra[ra >= 50].sum() / ra.sum()), 1),
               "pct_registros_en_rachas_le_3": round(100 * float(ra[ra <= 3].sum() / ra.sum()), 1)}
fr = np.array([d["n_bajo"] / d["n"] for d in por_pozo.values()])
R["pozos"] = {"pozos_con_bajo": int((fr > 0).sum()), "pozos_mayoria_bajo_(>50%)": int((fr > 0.5).sum()),
              "registros_bajo_en_pozos_mayoria_bajo_pct": round(100 * sum(d["n_bajo"] for d in por_pozo.values() if d["n_bajo"] / d["n"] > 0.5)
                                                              / max(1, sum(d["n_bajo"] for d in por_pozo.values())), 1)}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1, default=float)
for g in R["grupos"]: log(f"{g}: {json.dumps({k: v for k, v in R['grupos'][g].items() if k != 'top_pozos'}, ensure_ascii=False)}")
log(f"rachas: {R['rachas']}"); log(f"pozos: {R['pozos']}"); log(f"top pozos bajo: {R['grupos']['bajo']['top_pozos']}")
