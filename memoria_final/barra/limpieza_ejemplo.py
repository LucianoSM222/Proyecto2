"""Motivo de exclusión de cada registro en pozos de ejemplo, con la limpieza
estándar vigente. Cada registro excluido se asigna a UN motivo, en este orden:
emboquillado, cambio de barra (detención y margen), equipo (no perfora),
continuidad, roca (fuera de rango, solo sale del entrenamiento).
Uso: python3 limpieza_ejemplo.py salida.json"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc
POZOS = ["PCC_0042_PR01_TH_P20_H12"]
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
cc.cargar_caseron("PCC_0042", verbose=False)
gw.aplicar_limpieza_estandar()
lim = gw.limites_equipo(); tope = gw.get_param("limites.pr_max_di")
R = {}
for wn in POZOS:
    w = gw.wells[wn]; ps = sorted(w.points, key=lambda p: p.largo)
    gw.set_param("barra.margen_despues", 0); det = set(gw.detectar_cambio_de_barra(ps))
    gw.reset_param("barra.margen_despues"); cb = set(gw.detectar_cambio_de_barra(ps))
    co = {id(w.points[i]) for i in gw.puntos_tras_salto(w)}
    serie = dict(zip(map(id, w.points), gw.mascara_serie_di(w.points)))
    mot = []
    for i, p in enumerate(ps):
        equipo = (p.vel <= 0 or p.vel > tope or p.pp < lim["PP"][1] or p.pa < lim["FP"][1] or p.pf > lim["FLP"][2])
        if p.emboquillado: m = "emboquillado"
        elif i in det: m = "barra"
        elif i in cb: m = "margen"
        elif equipo: m = "equipo"
        elif id(p) in co: m = "continuidad"
        elif not p.entrenable: m = "roca"
        else: m = ""
        mot.append(m)
        assert bool(serie[id(p)]) == (m in ("", "roca")), (wn, i, m)
    R[wn] = {"largo": [round(p.largo, 3) for p in ps], "pp": [p.pp for p in ps], "pr": [p.vel for p in ps],
             "motivo": mot, "corte_emboquillado": list(gw.inicio_por_pozo[wn])}
    print(wn, {k: mot.count(k) for k in sorted(set(mot))}, gw.inicio_por_pozo[wn])
json.dump(R, open(sys.argv[1], "w"), ensure_ascii=False)
