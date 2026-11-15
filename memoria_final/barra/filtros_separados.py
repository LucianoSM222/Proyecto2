"""Datos para las figuras del efecto de cada filtro por separado (marcas NO
exclusivas: cada filtro marca lo suyo, aunque otro filtro también lo marque).
Uso: python3 filtros_separados.py proyecto_final.gwz salida.json BARRENO [BARRENO...]"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
print("filtros activos:", [f.get("method") for f in gw.clean_filters], "inicio_aplicado:", gw.inicio_aplicado)
lim = gw.limites_equipo(); tope = float(gw.get_param("limites.pr_max_di"))
print("limites:", lim, "tope PR DI:", tope)
R = {"limites": lim, "pr_max_di": tope, "barrenos": {}}
for wn in sys.argv[3:]:
    w = gw.wells[wn]; ps = sorted(w.points, key=lambda p: p.largo)
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps))
    gw.reset_param("barra.margen_despues"); cb = set(gw.detectar_cambio_de_barra(ps))
    co = {id(p) for p in [w.points[i] for i in gw.puntos_tras_salto(w)]}
    eq = []
    for p in ps:
        c = []
        if p.vel <= 0: c.append("PR = 0")
        if p.vel > tope: c.append("PR > 10")
        if p.pp < lim["PP"][1]: c.append("PP < mín")
        if p.pa < lim["FP"][1]: c.append("FP < mín")
        if p.pf > lim["FLP"][2]: c.append("FLP > máx")
        eq.append(c)
    roca = []
    for p, e in zip(ps, eq):
        c = []
        if not e:
            if not (lim["PR"][1] <= p.vel <= lim["PR"][2]): c.append("PR")
            if not (lim["RP"][1] <= p.pr <= lim["RP"][2]): c.append("RP")
            if not (lim["DP"][1] <= p.pd <= lim["DP"][2]): c.append("DP")
        roca.append(c)
    R["barrenos"][wn] = {
        "largo": [p.largo for p in ps], "PR": [p.vel for p in ps], "PP": [p.pp for p in ps], "FP": [p.pa for p in ps],
        "DP": [p.pd for p in ps], "RP": [p.pr for p in ps], "FLP": [p.pf for p in ps],
        "barra": [i in det for i in range(len(ps))], "margen": [(i in cb and i not in det) for i in range(len(ps))],
        "emboquillado": [bool(p.emboquillado) for p in ps], "corte": list(gw.inicio_por_pozo.get(wn, (None, None))),
        "equipo": eq, "roca": roca, "continuidad": [id(p) in co for p in ps]}
    from collections import Counter
    print(wn, "barra", len(det), "margen", len(cb - det), "emb", sum(p.emboquillado for p in ps),
          "equipo", Counter(c for e in eq for c in e), "roca", Counter(c for r in roca for c in r),
          "continuidad", sum(id(p) in co for p in ps))
json.dump(R, open(sys.argv[2], "w"))
