"""
diag_geometria_mwd.py — ¿Por qué hay pozos traslapados y mediciones sueltas?

Dos sospechas concretas sobre el código de posicionamiento:

  A. Los puntos se colocan por PARÁMETRO NORMALIZADO t = largo/largo_max, y
     luego se interpolan entre collar y final del DQ. Si el MWD dejó de
     registrar antes del fondo, los metros medidos se ESTIRAN sobre todo el
     tiro: un pozo con 10 m de registro y un tiro de 35 m queda con sus puntos
     repartidos a lo largo de 35 m. La colocación correcta es a la profundidad
     REALMENTE medida sobre la dirección del tiro.

  B. Los pozos SIN DQ reciben posición ficticia en el centro global. Todos
     ellos quedan apilados sobre la misma vertical, de cualquier caserón: eso
     es exactamente el traslape que se ve en la vista 3D.

Y la consecuencia visible de A cuando un pozo tiene 2 o 3 muestras: se ve el
collar y "una sola medición a lo lejos", sin nada en medio.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]


def main():
    t0 = time.time()
    gw.seed_attribute_registry(); gw.seed_di_variants(); gw.seed_param_registry()
    voc.aplicar_vocabulario_mpc(verbose=False)
    for c in CASERONES:
        cc.cargar_caseron(c, verbose=False)
    print(f"pozos={len(gw.wells)}  ({time.time()-t0:.1f}s)")

    print(f"\n{'='*72}\n  A — ¿SE ESTIRAN LOS PUNTOS SOBRE TODO EL TIRO?\n{'='*72}")
    filas = []
    for wn, w in gw.wells.items():
        if not w.collar or not w.final_pt:
            continue
        largo_max = max(p.largo for p in w.points)
        d = gw._dist3d(w.collar, w.final_pt)
        filas.append((wn, largo_max, d, (d - largo_max), len(w.points)))
    if filas:
        err = np.array([f[3] for f in filas])
        print(f"  pozos con collar y final: {len(filas)}")
        print(f"  dist(collar,final) − largo_max, en metros:")
        print(f"    mediana {np.median(err):+.3f}  p90 {np.percentile(err,90):+.3f}  "
              f"máx {err.max():+.3f}  mín {err.min():+.3f}")
        graves = [f for f in filas if abs(f[3]) > 1.0]
        print(f"  pozos donde el estiramiento supera 1 m: {len(graves)}")
        for f in sorted(graves, key=lambda x: -abs(x[3]))[:10]:
            print(f"    {f[0]:<34} largo_max={f[1]:7.2f}  dist={f[2]:7.2f}  "
                  f"estira {f[3]:+7.2f} m  ({f[4]} pts)")

    print(f"\n{'='*72}\n  B — ¿CUÁNTOS POZOS QUEDAN EN POSICIÓN FICTICIA?\n{'='*72}")
    por_origen = {}
    for wn, w in gw.wells.items():
        por_origen.setdefault(w.origin, []).append(wn)
    for o, lista in sorted(por_origen.items()):
        print(f"  {o:<12} {len(lista):>5} pozo(s)")
    sin_pos = [wn for wn, w in gw.wells.items() if not w.collar or not w.final_pt]
    print(f"  sin collar o sin final: {len(sin_pos)}")
    if sin_pos:
        # ¿Están todos apilados en el mismo XY?
        xy = {(round(gw.wells[wn].points[0].este, 1),
               round(gw.wells[wn].points[0].norte, 1)) for wn in sin_pos}
        print(f"  posiciones XY distintas entre ellos: {len(xy)}  "
              f"(si es 1, están TODOS apilados en la misma vertical)")
        for wn in sin_pos[:8]:
            p = gw.wells[wn].points[0]
            print(f"    {wn:<40} E={p.este:.1f} N={p.norte:.1f} Z={p.cota:.1f}")

    print(f"\n{'='*72}\n  C — POZOS CON POQUÍSIMAS MUESTRAS\n{'='*72}")
    n_pts = np.array([len(w.points) for w in gw.wells.values()])
    print(f"  puntos por pozo — mín {n_pts.min()}  p10 {np.percentile(n_pts,10):.0f}  "
          f"mediana {np.median(n_pts):.0f}  máx {n_pts.max()}")
    for umbral in (2, 5, 14, 50):
        k = int((n_pts < umbral).sum())
        print(f"    pozos con menos de {umbral:>3} puntos: {k}")
    cortos = sorted(((len(w.points), wn) for wn, w in gw.wells.items()))[:10]
    for n, wn in cortos:
        w = gw.wells[wn]
        lm = max((p.largo for p in w.points), default=0.0)
        d = gw._dist3d(w.collar, w.final_pt) if (w.collar and w.final_pt) else float("nan")
        print(f"    {wn:<40} {n:>4} pts  largo_max={lm:7.2f}  tiro={d:7.2f}")

    print(f"\n{'='*72}\n  D — ¿EL PASO ENTRE MUESTRAS ES UNIFORME?\n{'='*72}")
    pasos_todos = []
    irregulares = []
    for wn, w in gw.wells.items():
        largos = np.array(sorted(p.largo for p in w.points))
        if largos.size < 3:
            continue
        d = np.diff(largos)
        d = d[d > 0]
        if d.size < 2:
            continue
        pasos_todos.append(np.median(d))
        if d.max() > 10 * np.median(d):
            irregulares.append((wn, float(np.median(d)), float(d.max()), len(largos)))
    pa = np.array(pasos_todos)
    print(f"  paso mediano entre muestras, por pozo: mediana {np.median(pa):.4f} m  "
          f"mín {pa.min():.4f}  máx {pa.max():.4f}")
    print(f"  pozos con algún salto > 10x su paso mediano: {len(irregulares)}")
    for wn, med, mx, n in sorted(irregulares, key=lambda x: -x[2])[:10]:
        print(f"    {wn:<40} paso={med:.3f} m  salto máx={mx:8.2f} m  ({n} pts)")

    print(f"\n  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
