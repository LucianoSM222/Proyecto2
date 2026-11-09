"""Percusión de empate detectada por la caída relativa de la ROP (no de la PP).

Mismo detector que el filtro vigente (detectar_percusion_de_empate: un
registro cae ≥ umbral bajo el promedio de sus dos vecinos y estos se parecen
entre sí), aplicado a la ROP. Dos escenarios:

  R1: solo la caída relativa de ROP ≥ 0,25.
  R2: R1 + periodicidad de barra a lo largo del pozo: en cada pozo se busca la
      fase φ de la grilla φ + k·L (L = 1,756 m) que alinea más marcas a ±6 cm;
      se aceptan solo las marcas sobre esa grilla y solo si la grilla se
      repite en al menos 3 uniones del pozo.

Referencias: el filtro vigente por PP (umbral 0,25) y los empates esperados
por largo de barra. El azar se mide recolocando las marcas al azar en su pozo
(misma cantidad) y repitiendo R2 (30 veces, semilla 42).
Uso: python3 empate_rop.py salida.json
"""
import sys, json, time
from types import SimpleNamespace
sys.path.insert(0, "/home/user/Proyecto2")
import numpy as np
import geomech_wizard as gw
import cargar_caserones as cc

OUT = sys.argv[1]
T0 = time.time()
U, L, TOL, MIN_UNIONES, N_AZAR = 0.25, gw.LARGO_BARRA_M, 0.06, 3, 30


def log(m):
    print(f"[{time.time()-T0:5.0f}s] {m}", flush=True)


cc.asegurar_datos_extraidos()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
for c in cc.CASERONES: cc.cargar_caseron(c, verbose=False)
log(f"carga: {len(gw.wells)} pozos")


def grilla(x, largo_pozo):
    """Marcas sobre la mejor grilla φ + k·L del pozo (máscara) y nº de uniones que cubre."""
    if x.size == 0: return np.zeros(0, bool), 0
    mejor, n_mejor = None, -1
    for phi in np.mod(x, L):                       # candidatos: la fase de cada marca
        d = np.abs(((x - phi + L / 2) % L) - L / 2)
        en = d <= TOL; n = int(en.sum())
        if n > n_mejor: mejor, n_mejor = en, n
    uniones = len({int(round((xi - x[mejor][0]) / L)) for xi in x[mejor]})
    return (mejor if uniones >= MIN_UNIONES else np.zeros(x.size, bool)), uniones


tot = 0; R = {"umbral": U, "largo_barra_m": L, "tol_m": TOL, "min_uniones": MIN_UNIONES}
n_pp = n_r1 = n_r2 = n_ambos = n_ambos_r2 = 0; azar = np.zeros(N_AZAR); rng = np.random.default_rng(42)
pozos_r2 = 0; esperados = 0
for wn, w in gw.wells.items():
    ps = sorted(w.points, key=lambda p: p.largo)
    if len(ps) < 3: continue
    tot += len(ps); larg = np.array([p.largo for p in ps]); esperados += int((larg[-1] - larg[0]) // L)
    i_pp = set(gw.detectar_percusion_de_empate(ps, U))
    i_r1 = gw.detectar_percusion_de_empate([SimpleNamespace(pp=p.vel) for p in ps], U)
    x = larg[i_r1]; m2, _ = grilla(x, larg[-1])
    i_r2 = set(np.array(i_r1)[m2].tolist()) if len(i_r1) else set()
    n_pp += len(i_pp); n_r1 += len(i_r1); n_r2 += len(i_r2); pozos_r2 += bool(i_r2)
    n_ambos += len(i_pp & set(i_r1)); n_ambos_r2 += len(i_pp & i_r2)
    for k in range(N_AZAR):
        if len(i_r1): azar[k] += grilla(np.sort(rng.uniform(larg[0], larg[-1], len(i_r1))), larg[-1])[0].sum()
R.update({"registros": tot, "empates_esperados_por_barra": esperados,
          "PP_vigente": {"marcas": n_pp, "pct": round(100 * n_pp / tot, 3)},
          "R1_ROP": {"marcas": n_r1, "pct": round(100 * n_r1 / tot, 3), "coinciden_con_PP": n_ambos,
                     "pct_de_R1_que_tambien_marca_PP": round(100 * n_ambos / max(1, n_r1), 1)},
          "R2_ROP_barra": {"marcas": n_r2, "pct": round(100 * n_r2 / tot, 3), "pozos_con_grilla": pozos_r2,
                           "coinciden_con_PP": n_ambos_r2,
                           "marcas_azar_sobre_grilla": round(float(azar.mean()), 1), "marcas_azar_sd": round(float(azar.std()), 1),
                           "exceso_sobre_azar": round(float(n_r2 - azar.mean()), 1)}})
json.dump(R, open(OUT, "w"), ensure_ascii=False, indent=1)
log(json.dumps(R, ensure_ascii=False))
