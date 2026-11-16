"""Conteos de la limpieza estándar vigente sobre los cuatro caserones.
Uso: python3 limpieza_vigente.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
from collections import Counter
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.classify_all_wells_cached(); gw.build_domain_index()
res = gw.aplicar_limpieza_estandar()
res["pozos_sin_meseta"] = len(res["pozos_sin_meseta"])
tot = Counter(); ent = Counter(); serie = 0; equipo = Counter(); n = 0
lim = gw.limites_equipo(); tope = gw.get_param("limites.pr_max_di")
for wn, w in gw.wells.items():
    m = gw.mascara_serie_di(w.points); serie += int(m.sum()); n += len(w.points)
    cas = wn.split("_TH")[0].replace("_PR01", "").replace("_PR03", "").replace("_CL01", "")[:8]
    for p in w.points:
        for k in (cas, p.lito or "(sin)"):
            tot[k] += 1; ent[k] += p.entrenable
        if not p.emboquillado:
            equipo["PR = 0"] += p.vel <= 0; equipo["PR > 10"] += p.vel > tope
            equipo["PP < min"] += p.pp < lim["PP"][1]; equipo["FP < min"] += p.pa < lim["FP"][1]
R = {"limpieza": res, "registros": n, "en_serie_DI": serie, "fuera_serie_DI": n - serie,
     "entrenables": sum(1 for p in gw.all_points() if p.entrenable),
     "equipo_fuera_del_emboquillado": dict(equipo),
     "por_grupo": {k: {"total": tot[k], "entrenables": ent[k], "pct": round(100 * ent[k] / tot[k], 1)} for k in tot}}
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
