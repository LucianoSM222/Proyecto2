"""
diag_rqd_di.py — Diagnóstico previo a la calibración DI↔RQD.

No modifica nada. Responde tres preguntas con números, antes de escribir una
sola línea de calibración:

  1. ¿CUÁNTO MWD tiene un sondaje con RQD lo bastante cerca como para que
     "tú tienes el RQD de ese sondaje" sea creíble? Si son cuatro pozos, la
     calibración no tiene con qué.

  2. ¿Los picos del DI son ESTRUCTURA o RUIDO? Se agrupan en 3D y de cada
     grupo se mide la planaridad por SVD: un grupo plano que cruza varios
     pozos es un plano de falla o fractura; un grupo de un solo pico en un
     solo pozo es un evento local o ruido.

  3. ¿Qué relación empírica hay HOY entre el DI y el RQD del sondaje más
     cercano, con los pesos de la convención sin tocar?
"""

import os, sys, time
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
RADIOS = (2.0, 3.0, 5.0, 10.0, 15.0, 25.0, 50.0)
# Radio de agrupamiento de picos: dos picos a menos de esto son candidatos a
# pertenecer a la misma discontinuidad. 2,5 m es el burden de la operación.
EPS_CLUSTER = 2.5
MIN_PICOS_CLUSTER = 3


def cargar():
    gw.seed_attribute_registry()
    voc.aplicar_vocabulario_mpc(verbose=False)
    voc.aplicar_bandas_ucs(verbose=False)
    for c in CASERONES:
        cc.cargar_caseron(c, verbose=False)
    td = os.path.join(HERE, "test_data")
    archivos = {k: open(os.path.join(td, f"MPC_{k}.csv"), "rb").read()
                for k in gw.DRILLHOLE_KINDS
                if os.path.exists(os.path.join(td, f"MPC_{k}.csv"))}
    if archivos:
        gw.load_drillhole_csvs(archivos)
        gw.refresh_drillhole_selection()
    gw.classify_all_wells_cached()
    gw.build_domain_index()
    gw.compute_di()


def muestras_rqd():
    """Intervalos de la tabla geomec con RQD, llevados a UTM por el desurvey."""
    filas = []
    for hid, dh in gw.drillholes.items():
        if not dh.trace:
            continue
        for r in dh.geomec:
            if r.get("rqd") is None:
                continue
            prof = (r["from"] + r["to"]) / 2.0
            e, n, z = gw.trace_interp(dh.trace, float(prof))
            if not np.isfinite(e):
                continue
            filas.append({"sondaje": hid, "prof": prof, "rqd": float(r["rqd"]),
                          "largo_m": float(r["to"] - r["from"]),
                          "pt": (e, n, z)})
    return filas


def p1_cobertura(rqd_filas):
    print(f"\n{'='*72}\n  1 — ¿CUÁNTO MWD TIENE UN SONDAJE CON RQD CERCA?\n{'='*72}")
    if not rqd_filas:
        print("  No hay intervalos de RQD en la tabla geomec de los sondajes.")
        return None
    rqd = np.array([f["rqd"] for f in rqd_filas])
    metros = sum(f["largo_m"] for f in rqd_filas)
    print(f"  intervalos con RQD : {len(rqd_filas):,}".replace(",", "."))
    print(f"  sondajes           : {len({f['sondaje'] for f in rqd_filas})}")
    print(f"  metraje logueado   : {metros:,.1f} m".replace(",", "."))
    print(f"  RQD  min/p25/med/p75/max : {rqd.min():.0f} / {np.percentile(rqd,25):.0f} / "
          f"{np.median(rqd):.0f} / {np.percentile(rqd,75):.0f} / {rqd.max():.0f}")

    P = np.array([f["pt"] for f in rqd_filas])
    arbol = cKDTree(P)
    pts, wns = [], []
    for wn, w in gw.wells.items():
        for p in w.points:
            if p.entrenable:
                pts.append((p.este, p.norte, p.cota)); wns.append(wn)
    Q = np.array(pts)
    d, idx = arbol.query(Q, k=1)
    print(f"\n  puntos MWD entrenables: {len(Q):,}".replace(",", "."))
    print(f"  distancia al intervalo de RQD más cercano:")
    print(f"    {'radio':>8}{'puntos':>12}{'%':>8}{'pozos':>8}")
    wn_arr = np.array(wns)
    for r in RADIOS:
        m = d <= r
        print(f"    {r:>7.0f}m{int(m.sum()):>12,}{100.0*m.mean():>7.1f}%"
              f"{len(set(wn_arr[m].tolist())):>8}".replace(",", "."))
    print(f"    {'mediana':>8}{np.median(d):>11.1f}m")
    return {"P": P, "rqd": rqd, "arbol": arbol, "d_mwd": d, "idx_mwd": idx,
            "Q": Q, "wn": wn_arr}


def p2_estructura_de_los_picos():
    print(f"\n{'='*72}\n  2 — ¿LOS PICOS DEL DI SON ESTRUCTURA O RUIDO?\n{'='*72}")
    picos = []
    por_pozo = Counter()
    espaciamientos = []
    for wn, w in gw.wells.items():
        pk = gw.di_peaks(w)
        por_pozo[wn] = len(pk)
        largos = sorted(p[0] for p in pk)
        espaciamientos.extend(np.diff(largos).tolist())
        for largo, coord, di in pk:
            picos.append({"pozo": wn, "largo": largo, "pt": coord, "di": di,
                          "caseron": getattr(w, "caseron", None)})
    if not picos:
        print("  Sin picos.")
        return
    n = len(picos)
    cnt = np.array(list(por_pozo.values()))
    print(f"  picos totales: {n:,}  ·  pozos: {len(por_pozo)}".replace(",", "."))
    print(f"  picos por pozo — media {cnt.mean():.1f}  mediana {np.median(cnt):.0f}  "
          f"máx {cnt.max()}  pozos sin ningún pico: {int((cnt==0).sum())}")
    if espaciamientos:
        esp = np.array(espaciamientos)
        print(f"  espaciamiento entre picos consecutivos del mismo pozo — "
              f"mediana {np.median(esp):.2f} m  p10 {np.percentile(esp,10):.2f}  "
              f"p90 {np.percentile(esp,90):.2f}")

    X = np.array([p["pt"] for p in picos])
    lab = DBSCAN(eps=EPS_CLUSTER, min_samples=2).fit_predict(X)
    n_ruido = int((lab == -1).sum())
    grupos = [np.where(lab == g)[0] for g in sorted(set(lab.tolist())) if g >= 0]
    print(f"\n  agrupamiento 3D (eps={EPS_CLUSTER:g} m, el burden de la operación):")
    print(f"    picos AISLADOS (ningún otro pico a {EPS_CLUSTER:g} m): "
          f"{n_ruido:,}  ({100.0*n_ruido/n:.1f}%)".replace(",", "."))
    print(f"    grupos formados: {len(grupos):,}".replace(",", "."))

    planos, difusos, lineales = 0, 0, 0
    detalle = []
    for g in grupos:
        if len(g) < MIN_PICOS_CLUSTER:
            continue
        Pg = X[g]
        c = Pg.mean(axis=0)
        _, S, Vt = np.linalg.svd(Pg - c, full_matrices=False)
        if S[0] < 1e-9:
            continue
        # s3/s2 pequeño = los puntos caen en un plano. s2/s1 pequeño = caen en
        # una recta (que en un solo pozo es trivial: el pozo mismo).
        r32, r21 = S[2] / max(S[1], 1e-12), S[1] / max(S[0], 1e-12)
        pozos_g = len({picos[i]["pozo"] for i in g})
        if r21 < 0.15:
            lineales += 1
        elif r32 < 0.25:
            planos += 1
            detalle.append({"n": len(g), "pozos": pozos_g,
                            "extension_m": float(S[0] * 2 / np.sqrt(len(g))),
                            "normal": Vt[2], "centro": c,
                            "di_medio": float(np.mean([picos[i]["di"] for i in g]))})
        else:
            difusos += 1
    grandes = [g for g in grupos if len(g) >= MIN_PICOS_CLUSTER]
    print(f"    grupos de ≥{MIN_PICOS_CLUSTER} picos: {len(grandes):,}".replace(",", "."))
    print(f"      · PLANOS   (caen en un plano → falla o fractura): {planos}")
    print(f"      · lineales (alineados con el propio pozo, no informan): {lineales}")
    print(f"      · difusos  (nube sin forma → zona fracturada o ruido): {difusos}")

    multipozo = [d for d in detalle if d["pozos"] >= 2]
    print(f"\n  planos que cruzan 2 o más POZOS (lo que sería una estructura real): "
          f"{len(multipozo)}")
    for d in sorted(multipozo, key=lambda d: -d["n"])[:8]:
        nx, ny, nz = d["normal"]
        # Manteo desde la normal: 90° = plano vertical, 0° = horizontal.
        manteo = np.degrees(np.arccos(abs(nz)))
        rumbo = (np.degrees(np.arctan2(nx, ny)) + 90.0) % 360.0
        print(f"    n={d['n']:>3} picos · {d['pozos']} pozos · DI medio {d['di_medio']:.2f} · "
              f"manteo {manteo:.0f}° · rumbo {rumbo:.0f}° · "
              f"E{d['centro'][0]:.0f} N{d['centro'][1]:.0f} Z{d['centro'][2]:.0f}")
    if not multipozo:
        print("    ninguno: cada grupo plano vive dentro de un solo pozo.")


def p3_relacion_di_rqd(cob):
    print(f"\n{'='*72}\n  3 — RELACIÓN EMPÍRICA DI ↔ RQD (pesos de convención, SIN tocar)\n{'='*72}")
    if cob is None:
        print("  Sin RQD no hay relación que medir.")
        return
    d, idx, Q, wn = cob["d_mwd"], cob["idx_mwd"], cob["Q"], cob["wn"]
    rqd = cob["rqd"]
    di_todos = []
    for w in gw.wells.values():
        for p in w.points:
            if p.entrenable:
                di_todos.append(p.di if p.di is not None else np.nan)
    DI = np.array(di_todos, dtype=np.float64)
    for radio in (5.0, 10.0, 25.0):
        m = (d <= radio) & np.isfinite(DI)
        if m.sum() < 100:
            print(f"  radio {radio:g} m: solo {int(m.sum())} punto(s), no alcanza.")
            continue
        di_m, rqd_m = DI[m], rqd[idx[m]]
        rho = gw.spearman_rho(di_m.tolist(), rqd_m.tolist())
        print(f"\n  radio {radio:g} m — n={int(m.sum()):,}".replace(",", "."))
        print(f"    ρ(DI, RQD) = {rho if rho is None else round(rho, 4)}   "
              f"(se espera NEGATIVO: más DI → menos RQD)")
        # DI medio por banda de RQD.
        print(f"    {'banda RQD':>12}{'n':>10}{'DI medio':>10}{'DI p90':>9}")
        for lo, hi in ((0, 25), (25, 50), (50, 75), (75, 90), (90, 101)):
            b = (rqd_m >= lo) & (rqd_m < hi)
            if b.sum() < 20:
                continue
            print(f"    {f'{lo}-{hi}':>12}{int(b.sum()):>10,}"
                  f"{di_m[b].mean():>10.3f}{np.percentile(di_m[b],90):>9.3f}".replace(",", "."))
        # Y el RQD_MWD que la sesión 8 ya calcula, contra el RQD del sondaje.
        print(f"    fracción de puntos sobre el umbral DI>{gw.di_threshold:g}: "
              f"{100.0*(di_m > gw.di_threshold).mean():.2f}%  "
              f"(el RQD del sondaje dice que hay {100.0-np.mean(rqd_m):.1f}% de "
              "roca no recuperable)")


def main():
    t0 = time.time()
    cargar()
    print(f"pozos={len(gw.wells)}  sondajes={len(gw.drillholes)}  ({time.time()-t0:.1f}s)")
    filas = muestras_rqd()
    cob = p1_cobertura(filas)
    p2_estructura_de_los_picos()
    p3_relacion_di_rqd(cob)
    print(f"\n  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
