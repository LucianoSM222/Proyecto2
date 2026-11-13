"""
diag_rqd_di2.py — Segunda pasada, corrigiendo el soporte.

La primera comparó DI PUNTUAL (un valor cada 2 cm) contra RQD de INTERVALO
(un número por 1-3 m de testigo). Son soportes distintos y la comparación
está sesgada a la baja por construcción.

Acá se compara como corresponde: por cada intervalo de la tabla geomec con
RQD, se juntan los puntos MWD que caen cerca de ESE intervalo y se calcula
sobre ellos, con la regla de Deere, el RQD_MWD del mismo tramo. Un número
contra un número, sobre el mismo soporte.

Se prueba además el proxy más simple —la fracción de metraje con DI sobre el
umbral— y se barre el umbral, para saber si la falta de relación viene del
umbral 1,5 o de los pesos.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from scipy.spatial import cKDTree

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
RADIOS = (5.0, 10.0, 15.0, 25.0)
UMBRALES = (0.8, 1.0, 1.2, 1.5, 2.0, 2.5)
MIN_PTS_INTERVALO = 30


def cargar():
    gw.seed_attribute_registry()
    voc.aplicar_vocabulario_mpc(verbose=False)
    voc.aplicar_bandas_ucs(verbose=False)
    for c in CASERONES:
        cc.cargar_caseron(c, verbose=False)
    td = os.path.join(HERE, "test_data")
    arch = {k: open(os.path.join(td, f"MPC_{k}.csv"), "rb").read()
            for k in gw.DRILLHOLE_KINDS
            if os.path.exists(os.path.join(td, f"MPC_{k}.csv"))}
    if arch:
        gw.load_drillhole_csvs(arch)
        gw.refresh_drillhole_selection()
    gw.classify_all_wells_cached()
    gw.build_domain_index()
    gw.compute_di()


def intervalos_rqd():
    out = []
    for hid, dh in gw.drillholes.items():
        if not dh.trace:
            continue
        for r in dh.geomec:
            if r.get("rqd") is None:
                continue
            a = gw.trace_interp(dh.trace, float(r["from"]))
            b = gw.trace_interp(dh.trace, float(r["to"]))
            if not np.isfinite(a[0]) or not np.isfinite(b[0]):
                continue
            out.append({"sondaje": hid, "rqd": float(r["rqd"]),
                        "largo": float(r["to"] - r["from"]),
                        "a": np.array(a), "b": np.array(b),
                        "c": (np.array(a) + np.array(b)) / 2.0})
    return out


def rqd_mwd_de_puntos(pts, umbral):
    """
    Regla de Deere sobre una lista de puntos MWD de UN pozo, ya ordenada por
    largo: porcentaje del metraje en tramos continuos de ≥10 cm sin
    discontinuidad, con la discontinuidad definida por DI > umbral.
    """
    if len(pts) < 2:
        return None
    total = pts[-1].largo - pts[0].largo
    if total <= 0:
        return None
    tramos, ini, fin = [], None, None
    for p in pts:
        if p.di is not None and np.isfinite(p.di) and p.di > umbral:
            if ini is not None:
                tramos.append(fin - ini); ini = fin = None
        else:
            if ini is None:
                ini = p.largo
            fin = p.largo
    if ini is not None:
        tramos.append(fin - ini)
    buenos = [t for t in tramos if t >= gw.RQD_TRAMO_MIN_M]
    return 100.0 * sum(buenos) / total


def main():
    t0 = time.time()
    cargar()
    intervalos = intervalos_rqd()
    print(f"sondajes={len(gw.drillholes)}  intervalos con RQD={len(intervalos)}  "
          f"({time.time()-t0:.1f}s)")

    # Índice de todos los puntos MWD, con su pozo.
    pts_all, meta = [], []
    for wn, w in gw.wells.items():
        for p in w.points:
            if p.entrenable and p.di is not None and np.isfinite(p.di):
                pts_all.append((p.este, p.norte, p.cota))
                meta.append((wn, p))
    P = np.array(pts_all)
    arbol = cKDTree(P)
    print(f"puntos MWD con DI: {len(P):,}".replace(",", "."))

    for radio in RADIOS:
        print(f"\n{'='*72}\n  RADIO {radio:g} m — un número por intervalo, "
              f"mismo soporte\n{'='*72}")
        pares = {u: [] for u in UMBRALES}
        pares_frac = []
        n_con_datos = 0
        for iv in intervalos:
            idx = arbol.query_ball_point(iv["c"], radio)
            if len(idx) < MIN_PTS_INTERVALO:
                continue
            # Los puntos vecinos se agrupan POR POZO: la regla de Deere solo
            # tiene sentido a lo largo de una perforación, no sobre una nube.
            por_pozo = {}
            for i in idx:
                wn, p = meta[i]
                por_pozo.setdefault(wn, []).append(p)
            vals = {u: [] for u in UMBRALES}
            fracs = []
            for wn, lista in por_pozo.items():
                lista.sort(key=lambda p: p.largo)
                if len(lista) < MIN_PTS_INTERVALO // 2:
                    continue
                for u in UMBRALES:
                    v = rqd_mwd_de_puntos(lista, u)
                    if v is not None:
                        vals[u].append(v)
                dis = np.array([p.di for p in lista])
                fracs.append(100.0 * float((dis <= gw.di_threshold).mean()))
            if not fracs:
                continue
            n_con_datos += 1
            for u in UMBRALES:
                if vals[u]:
                    pares[u].append((float(np.mean(vals[u])), iv["rqd"]))
            pares_frac.append((float(np.mean(fracs)), iv["rqd"]))

        print(f"  intervalos con ≥{MIN_PTS_INTERVALO} puntos MWD a {radio:g} m: "
              f"{n_con_datos} de {len(intervalos)}")
        if n_con_datos < 20:
            print("  muestra insuficiente para hablar de correlación.")
            continue
        print(f"\n  RQD_MWD (Deere) contra RQD del sondaje, barriendo el umbral de DI:")
        print(f"    {'umbral DI':>10}{'n':>7}{'rho':>9}{'RQD_MWD medio':>16}"
              f"{'RQD sondaje medio':>19}")
        for u in UMBRALES:
            pr = pares[u]
            if len(pr) < 20:
                continue
            a = [x[0] for x in pr]; b = [x[1] for x in pr]
            rho = gw.spearman_rho(a, b)
            marca = "  ←convención" if abs(u - gw.di_threshold) < 1e-9 else ""
            print(f"    {u:>10.1f}{len(pr):>7}"
                  f"{(rho if rho is not None else float('nan')):>9.3f}"
                  f"{np.mean(a):>16.1f}{np.mean(b):>19.1f}{marca}")
        a = [x[0] for x in pares_frac]; b = [x[1] for x in pares_frac]
        rho = gw.spearman_rho(a, b)
        print(f"\n  proxy simple (% de metraje con DI ≤ {gw.di_threshold:g}): "
              f"rho={rho if rho is None else round(rho,3)}  n={len(a)}")
        # ¿El RQD_MWD tiene siquiera rango? Si todos los intervalos dan ~91%,
        # no hay nada que correlacionar: el problema es de VARIANZA, no de signo.
        av = np.array(a); bv = np.array(b)
        print(f"    rango RQD_MWD  : {av.min():.1f} a {av.max():.1f}  "
              f"(sd {av.std():.2f})")
        print(f"    rango RQD sondaje: {bv.min():.1f} a {bv.max():.1f}  "
              f"(sd {bv.std():.2f})")

    print(f"\n  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
