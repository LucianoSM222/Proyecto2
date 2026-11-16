"""
diag_planos.py — ¿Los planos de picos son estructuras o son el propio abanico?

Un abanico de tiros ES un plano. Si los picos se reparten a lo largo de los
tiros de un mismo abanico, cualquier subconjunto suyo sale "plano" por
construcción, sin que exista ninguna estructura. Antes de decir que el MWD ve
fallas hay que descartar ese artefacto.

Tres pruebas por grupo:

  1. ¿Cuántos ABANICOS distintos cruza? Un grupo dentro de un solo abanico es
     sospechoso; uno que cruza varios no puede ser el plano de un abanico.

  2. ¿El plano del grupo COINCIDE con el plano de los tiros involucrados? Se
     ajusta un plano a los propios trazados y se compara la normal. Ángulo
     chico entre normales = el grupo es el abanico.

  3. ¿Los picos forman una banda ESTRECHA que corta los tiros, o están
     desparramados a lo largo de ellos? Se proyecta cada pico sobre la
     dirección media de perforación: dispersión chica = estructura transversal
     real; dispersión grande = repartidos por el abanico.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from sklearn.cluster import DBSCAN

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
EPS = 2.5
MIN_PICOS = 3


def cargar():
    gw.seed_attribute_registry()
    voc.aplicar_vocabulario_mpc(verbose=False)
    voc.aplicar_bandas_ucs(verbose=False)
    for c in CASERONES:
        cc.cargar_caseron(c, verbose=False)
    gw.classify_all_wells_cached()
    gw.build_domain_index()
    gw.compute_di()


def direccion_pozo(w):
    """Vector unitario del trazado del pozo, del collar al fondo."""
    if len(w.points) < 2:
        return None
    a = np.array([w.points[0].este, w.points[0].norte, w.points[0].cota])
    b = np.array([w.points[-1].este, w.points[-1].norte, w.points[-1].cota])
    v = b - a
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else None


def main():
    t0 = time.time()
    cargar()
    picos = []
    for wn, w in gw.wells.items():
        for largo, coord, di in gw.di_peaks(w):
            picos.append({"pozo": wn, "plan": w.plan_id, "pt": coord, "di": di,
                          "dir": direccion_pozo(w)})
    X = np.array([p["pt"] for p in picos])
    print(f"picos={len(picos)}  pozos={len(gw.wells)}  ({time.time()-t0:.1f}s)")

    lab = DBSCAN(eps=EPS, min_samples=2).fit_predict(X)
    grupos = [np.where(lab == g)[0] for g in sorted(set(lab.tolist())) if g >= 0]
    grandes = sorted([g for g in grupos if len(g) >= MIN_PICOS],
                     key=lambda g: -len(g))
    print(f"grupos de ≥{MIN_PICOS} picos: {len(grandes)}\n")

    print(f"{'n':>5}{'pozos':>7}{'abanicos':>10}{'planar':>8}"
          f"{'ang(normal,abanico)':>21}{'banda_m':>9}{'largo_m':>9}{'veredicto':>28}")
    print("-" * 100)
    reales, artefactos, dudosos = 0, 0, 0
    for g in grandes:
        Pg = X[g]
        c = Pg.mean(axis=0)
        _, S, Vt = np.linalg.svd(Pg - c, full_matrices=False)
        if S[0] < 1e-9:
            continue
        r32 = S[2] / max(S[1], 1e-12)
        r21 = S[1] / max(S[0], 1e-12)
        if r21 < 0.15:            # alineado con el propio pozo: no informa
            continue
        normal = Vt[2]
        pozos = sorted({picos[i]["pozo"] for i in g})
        planes = sorted({picos[i]["plan"] for i in g})

        # Plano de los TIROS involucrados: se ajusta a los puntos de sus
        # trazados, no a los picos.
        trazas = []
        for wn in pozos:
            w = gw.wells[wn]
            paso = max(1, len(w.points) // 20)
            for p in w.points[::paso]:
                trazas.append((p.este, p.norte, p.cota))
        T = np.array(trazas)
        ct = T.mean(axis=0)
        _, St, Vtt = np.linalg.svd(T - ct, full_matrices=False)
        normal_abanico = Vtt[2]
        plano_abanico = St[2] / max(St[1], 1e-12)      # ¿los tiros son coplanares?
        ang = np.degrees(np.arccos(min(1.0, abs(float(np.dot(normal, normal_abanico))))))

        # Dispersión de los picos a lo largo de la dirección de perforación.
        dirs = [p["dir"] for p in (picos[i] for i in g) if p["dir"] is not None]
        if dirs:
            d_med = np.mean(dirs, axis=0)
            nd = np.linalg.norm(d_med)
            d_med = d_med / nd if nd > 1e-6 else np.array([0.0, 0.0, 1.0])
            proy = (Pg - c) @ d_med
            banda = float(proy.std())
        else:
            banda = float("nan")
        largo = float(S[0] * 2 / np.sqrt(len(g)))

        # Veredicto. El artefacto del abanico exige DOS cosas a la vez: que los
        # tiros involucrados sean coplanares Y que el plano del grupo sea ese
        # mismo plano.
        if plano_abanico < 0.15 and ang < 20.0:
            v = "ARTEFACTO: es el abanico"; artefactos += 1
        elif len(planes) >= 3 and banda < largo * 0.5:
            v = "estructura (cruza abanicos)"; reales += 1
        else:
            v = "dudoso"; dudosos += 1
        print(f"{len(g):>5}{len(pozos):>7}{len(planes):>10}{r32:>8.3f}"
              f"{ang:>21.1f}{banda:>9.2f}{largo:>9.2f}{v:>28}")

    print("-" * 100)
    print(f"  estructuras que cruzan ≥3 abanicos con banda estrecha: {reales}")
    print(f"  artefactos del plano del abanico                     : {artefactos}")
    print(f"  dudosos                                              : {dudosos}")
    print(f"\n  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
