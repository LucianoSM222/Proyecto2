"""Cuántos registros saca cada uno de los dos filtros y cuántos coinciden:

  1. Cambio de barra: registros con PR = 0 en rachas cuyo centro cae a ±6 cm
     de la mejor grilla φ + k·1,756 m del pozo (la grilla se ajusta con las
     rachas fuera del emboquillado y debe repetirse en ≥ 3 uniones).
  2. Regulación automática de la percusión: caída de PP ≥ 0,25 respecto de
     sus dos vecinos, con los vecinos parecidos entre sí (filtro vigente).

Conteos sobre el total, fuera del emboquillado (2 m), intersección y unión.
Uso: python3 dos_filtros.py salida.json
"""
import sys, json
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

OUT = sys.argv[1]
L, TOL, MIN_UNIONES, EMB, U = gw.LARGO_BARRA_M, 0.06, 3, 2.0, 0.25
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)


def cambio_de_barra(ps):
    """Índices (en ps, ordenado por largo) de los registros PR = 0 sobre la grilla de barra."""
    v = np.array([p.vel for p in ps], float); lar = np.array([p.largo for p in ps]); n = len(ps)
    rachas, i = [], 0
    while i < n:
        if v[i] != 0: i += 1; continue
        j = i
        while j + 1 < n and v[j + 1] == 0: j += 1
        rachas.append((i, j, (lar[i] + lar[j]) / 2)); i = j + 1
    cand = [r for r in rachas if lar[r[1]] >= EMB]
    if not cand: return set()
    x = np.array([r[2] for r in cand]); mejor, phi_m = 0, None
    for phi in np.mod(x, L):
        en = np.abs(((x - phi + L / 2) % L) - L / 2) <= TOL
        if en.sum() > mejor and len({int(round((xi - x[en][0]) / L)) for xi in x[en]}) >= MIN_UNIONES:
            mejor, phi_m = int(en.sum()), phi
    if phi_m is None: return set()
    out = set()
    for (i, j, c) in cand:
        if abs(((c - phi_m + L / 2) % L) - L / 2) <= TOL: out.update(range(i, j + 1))
    return out


T = {"total": 0, "barra": 0, "regulacion": 0, "ambos": 0, "union": 0}
F = {k: 0 for k in T}; pozos_barra = 0
for w in gw.wells.values():
    ps = sorted(w.points, key=lambda p: p.largo)
    if len(ps) < 3: continue
    a = cambio_de_barra(ps); b = set(gw.detectar_percusion_de_empate(ps, U))
    pozos_barra += bool(a)
    fuera = {i for i, p in enumerate(ps) if p.largo >= EMB}
    for D, sel in ((T, set(range(len(ps)))), (F, fuera)):
        D["total"] += len(sel); D["barra"] += len(a & sel); D["regulacion"] += len(b & sel)
        D["ambos"] += len(a & b & sel); D["union"] += len((a | b) & sel)
R = {"largo_barra_m": L, "tol_m": TOL, "min_uniones": MIN_UNIONES, "umbral_pp": U,
     "todos_los_registros": T, "fuera_del_emboquillado": F, "pozos_con_grilla_de_barra": pozos_barra}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
