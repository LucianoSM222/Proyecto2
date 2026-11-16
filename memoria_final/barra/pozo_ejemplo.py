"""Elige pozos de ejemplo para la figura de depuración: periodicidad de barra
clara (muchas uniones sobre la grilla, pocas detenciones fuera) y emboquillado
nítido (salto de PP en el corte de la meseta). Guarda los 6 mejores con el
motivo de exclusión de cada registro.
Uso: python3 pozo_ejemplo.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
gw.aplicar_limpieza_estandar()
lim = gw.limites_equipo(); tope = gw.get_param("limites.pr_max_di")
cand = []
for wn, w in gw.wells.items():
    corte, modo = gw.inicio_por_pozo.get(wn, (None, None))
    if modo != "meseta" or not (0.8 <= corte <= 3.0): continue
    ps = sorted(w.points, key=lambda p: p.largo)
    if len(ps) < 1000: continue
    lar = np.array([p.largo for p in ps]); pp = np.array([p.pp for p in ps]); v = np.array([p.vel for p in ps])
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps)); gw.reset_param("barra.margen_despues")
    uniones = len({round(lar[i] / gw.LARGO_BARRA_M) for i in det})
    ceros_fuera = int(sum(1 for i in range(len(ps)) if v[i] <= 0 and i not in det and lar[i] >= corte))
    antes = pp[(lar < corte) & (v > 0)]; desp = pp[(lar >= corte) & (lar < corte + 1.0) & (v > 0)]
    if antes.size < 5 or desp.size < 20: continue
    salto = float(np.median(desp) - np.median(antes))
    estable = float(np.std(pp[(lar >= corte) & (v > 0)]))
    esperado = int(lar[-1] / gw.LARGO_BARRA_M)
    score = uniones / max(esperado, 1) - 0.05 * ceros_fuera + salto / 100 - estable / 100
    cand.append((score, wn, uniones, esperado, ceros_fuera, round(salto, 1), round(corte, 2), round(estable, 1)))
cand.sort(reverse=True)
for c in cand[:15]: print(c)
R = {}
for _, wn, *_r in cand[:6]:
    w = gw.wells[wn]; ps = sorted(w.points, key=lambda p: p.largo)
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps))
    gw.reset_param("barra.margen_despues"); cb = set(gw.detectar_cambio_de_barra(ps))
    co = {id(w.points[i]) for i in gw.puntos_tras_salto(w)}
    mot = []
    for i, p in enumerate(ps):
        eq = p.vel <= 0 or p.vel > tope or p.pp < lim["PP"][1] or p.pa < lim["FP"][1] or p.pf > lim["FLP"][2]
        mot.append("emboquillado" if p.emboquillado else "barra" if i in det else "margen" if i in cb else
                   "equipo" if eq else "continuidad" if id(p) in co else "roca" if not p.entrenable else "")
    R[wn] = {"largo": [round(p.largo, 3) for p in ps], "pp": [p.pp for p in ps], "pr": [p.vel for p in ps],
             "motivo": mot, "corte_emboquillado": list(gw.inicio_por_pozo[wn]), "info": _r}
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False)
