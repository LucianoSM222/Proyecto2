"""Registros con PR = 0 (velocidad de penetración nula): dónde caen, por qué el
detector de «cae y se recupera» no los marca y si se repiten cada largo de
barra (1,756 m).

- Rachas: secuencias de registros consecutivos con PR = 0 en un pozo.
- Por qué no se detectan: el detector exige UN registro hundido con sus dos
  vecinos parecidos entre sí; se clasifica cada racha según cuál condición
  falla.
- Periodicidad: centro de cada racha fuera del emboquillado; en cada pozo se
  busca la grilla φ + k·L que alinea más rachas a ±6 cm (≥ 3 uniones), y se
  compara con las mismas rachas recolocadas al azar en el pozo (30 veces).
Uso: python3 pr_cero.py salida.json
"""
import sys, json
from collections import Counter
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

OUT = sys.argv[1]
L, TOL, MIN_UNIONES, N_AZAR, EMB = gw.LARGO_BARRA_M, 0.06, 3, 30, 2.0
cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)


def grilla(x):
    if x.size == 0: return 0
    mejor = 0
    for phi in np.mod(x, L):
        d = np.abs(((x - phi + L / 2) % L) - L / 2); en = d <= TOL
        if en.sum() > mejor:
            uniones = len({int(round((xi - x[en][0]) / L)) for xi in x[en]})
            if uniones >= MIN_UNIONES: mejor = int(en.sum())
    return mejor


n0 = 0; rachas = []; motivo = Counter(); pos = Counter(); en_grilla = 0; azar = np.zeros(N_AZAR); n_rachas_fuera = 0
rng = np.random.default_rng(42); pozos_con = 0
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo); n = len(ps)
    if n < 3: continue
    v = np.array([p.vel for p in ps], float); lar = np.array([p.largo for p in ps]); z = v == 0
    n0 += int(z.sum())
    if not z.any(): continue
    pozos_con += 1; centros = []
    i = 0
    while i < n:
        if not z[i]: i += 1; continue
        j = i
        while j + 1 < n and z[j + 1]: j += 1
        largo_r = j - i + 1; rachas.append(largo_r)
        c = (lar[i] + lar[j]) / 2
        if lar[j] < EMB: pos["emboquillado (< 2 m)"] += largo_r
        elif j == n - 1: pos["final del pozo"] += largo_r
        else: pos["cuerpo del pozo"] += largo_r
        # ¿por qué no lo marca el detector?
        if i == 0 or j == n - 1: motivo["en el borde del registro (sin vecino a un lado)"] += largo_r
        elif largo_r > 1: motivo["racha de 2 o más registros (el detector busca uno solo)"] += largo_r
        else:
            a, c_ = v[i - 1], v[j + 1]; prom = (a + c_) / 2
            if prom <= 0: motivo["vecinos también en cero"] += 1
            elif min(a, c_) < prom * (1 - 0.5 * 0.25): motivo["vecinos distintos entre sí (no «se recupera»)"] += 1
            else: motivo["cumple: el detector sí lo marca"] += 1
        if lar[j] >= EMB: centros.append(c)
        i = j + 1
    x = np.array(centros); n_rachas_fuera += x.size
    en_grilla += grilla(np.sort(x))
    for k in range(N_AZAR):
        if x.size: azar[k] += grilla(np.sort(rng.uniform(EMB, lar[-1], x.size)))
r = np.array(rachas)
R = {"registros_PR_cero": n0, "pozos_con_PR_cero": pozos_con, "rachas": int(r.size),
     "rachas_por_largo": {str(k): int((r == k).sum()) for k in (1, 2, 3, 4, 5)} | {"6 o más": int((r >= 6).sum())},
     "registros_en_rachas_ge_10": int(r[r >= 10].sum()), "racha_mas_larga": int(r.max()),
     "posicion_registros": dict(pos), "por_que_no_se_detecta_registros": dict(motivo),
     "periodicidad": {"rachas_fuera_emboquillado": n_rachas_fuera, "rachas_sobre_grilla_de_barra": en_grilla,
                      "esperado_al_azar": round(float(azar.mean()), 1), "azar_sd": round(float(azar.std()), 1)}}
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
print(json.dumps(R, ensure_ascii=False, indent=1))
