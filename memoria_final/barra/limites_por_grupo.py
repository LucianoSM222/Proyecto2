"""Cuánto sacan los límites del equipo por caserón y por litología.
Base: emboquillado + cambio de barra + continuidad (sin límites de rango).
Uso: python3 limites_por_grupo.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import defaultdict
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
gw.set_param("barra.margen_antes", 0); gw.set_param("barra.margen_despues", 0)
gw.emboquillado_modo = "meseta"; gw.apply_inicio_meseta()
LIM = gw.limites_equipo()
G = {"caseron": defaultdict(lambda: defaultdict(int)), "litologia": defaultdict(lambda: defaultdict(int))}
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    cb = set(gw.detectar_cambio_de_barra(ps)); co = {id(w.points[i]) for i in gw.puntos_tras_salto(w)}
    cas = getattr(w, "caseron", None) or wn.split("_TH")[0].replace("_PR01", "")
    for i, p in enumerate(ps):
        if p.emboquillado or i in cb or id(p) in co: continue
        malo = {s for s, (a, lo, hi) in LIM.items() if not (lo <= getattr(p, a) <= hi)}
        for g, k in (("caseron", cas), ("litologia", p.lito or "(sin)")):
            D = G[g][k]; D["base"] += 1; D["fuera"] += bool(malo)
            for s in malo: D[s] += 1
R = {g: {k: dict(v) | {"pct_fuera": round(100 * v["fuera"] / v["base"], 1)} for k, v in d.items()} for g, d in G.items()}
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
for g, d in R.items():
    print(g)
    for k, v in sorted(d.items(), key=lambda x: -x[1]["base"]):
        print(f"  {k:28s} base {v['base']:8d} fuera {v['pct_fuera']:5.1f}%  PP {100*v.get('PP',0)/v['base']:5.1f}%  RP {100*v.get('RP',0)/v['base']:5.1f}%  PR {100*v.get('PR',0)/v['base']:5.1f}%")
