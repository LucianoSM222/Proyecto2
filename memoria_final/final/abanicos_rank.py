"""Ordena los abanicos por qué tan buena sección ilustrativa dan: barrenos,
litologías distintas, transiciones de litología a lo largo de los barrenos y
estructuras cruzadas. Uso: python3 abanicos_rank.py proyecto_final.gwz salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import defaultdict
import numpy as np
import geomech_wizard as gw, cargar_caserones as cc
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1])
F = defaultdict(list)
for wn, w in gw.wells.items():
    F[(w.caseron or gw.caseron_de_pozo(w), gw._abanico_de_pozo(w))].append(wn)
filas = []
for (cas, ab), ws in F.items():
    if len(ws) < 6: continue
    litos, ests, trans, n = set(), set(), 0, 0
    for wn in ws:
        ps = sorted(gw.wells[wn].points, key=lambda p: p.largo); n += len(ps)
        L = [p.lito for p in ps]; E = [p.estructura for p in ps]
        litos |= {l for l in L if l}; ests |= {e for e in E if e}
        trans += sum(1 for a, b in zip(L, L[1:]) if a != b) + sum(1 for a, b in zip(E, E[1:]) if (a is None) != (b is None))
    filas.append({"caseron": cas, "abanico": ab, "barrenos": len(ws), "registros": n, "litologias": sorted(litos),
                  "estructuras": sorted(ests), "transiciones": trans,
                  "puntaje": len(litos) * 3 + len(ests) * 2 + trans / max(len(ws), 1)})
filas.sort(key=lambda r: -r["puntaje"])
for r in filas[:15]: print(r["caseron"], r["abanico"], r["barrenos"], r["litologias"], r["estructuras"], r["transiciones"], round(r["puntaje"], 1))
json.dump({"filas": filas, "pozos": {f"{c}|{a}": ws for (c, a), ws in F.items()}}, open(sys.argv[2], "w"), ensure_ascii=False)
