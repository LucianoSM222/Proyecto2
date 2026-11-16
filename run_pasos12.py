"""
run_pasos12.py — Propagación de RQD y pares de calibración, sobre datos reales.

Deja el terreno listo para el paso 3 (calibrar los pesos del DI contra el RQD
de los sondajes) y dice, con números, cuánta base hay para intentarlo.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
RADIOS = (5.0, 10.0, 25.0)


def cargar():
    gw.seed_attribute_registry()
    gw.seed_di_variants()
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


def main():
    t0 = time.time()
    cargar()
    print(f"pozos={len(gw.wells)}  sondajes={len(gw.drillholes)}  "
          f"({time.time()-t0:.1f}s)")

    print(f"\n{'='*72}\n  1 — VARIANTES DEL DI\n{'='*72}")
    for nombre, v in gw.di_variantes.items():
        marca = "  [SOLO LECTURA]" if v.get("solo_lectura") else ""
        print(f"  {nombre}{marca}")
        print(f"    ventana {v['window']} · umbral {v['threshold']} · "
              f"pesos {v['weights']}")
        print(f"    fuente: {v['fuente'][:100]}")

    print(f"\n{'='*72}\n  2 — RQD DE SONDAJE PROPAGADO AL MWD\n{'='*72}")
    for radio in RADIOS:
        rep = gw.propagate_drillhole_rqd(radio_m=radio)
        if rep["status"] != "ok":
            print(f"  radio {radio:g} m → {rep.get('motivo')}")
            continue
        tot = rep["n_etiquetados"] + rep["n_sin_etiqueta"]
        print(f"\n  radio {radio:g} m — etiquetados {rep['n_etiquetados']:,} de "
              f"{tot:,} ({100.0*rep['n_etiquetados']/tot:.1f}%)".replace(",", "."))
        print(f"    intervalos con RQD: {rep['n_intervalos']} en "
              f"{rep['n_sondajes']} sondaje(s)")
        if rep["distancia_m"]:
            print(f"    distancia de los etiquetados: mediana "
                  f"{rep['distancia_m']['mediana']} m · p90 "
                  f"{rep['distancia_m']['p90']} m")
        for c, d in sorted(rep["por_caseron"].items()):
            t = d["etiquetados"] + d["sin_etiqueta"]
            print(f"      {c:<12} {d['etiquetados']:>8,} de {t:>8,} "
                  f"({100.0*d['etiquetados']/max(t,1):>5.1f}%)".replace(",", "."))

    print(f"\n{'='*72}\n  2 — PARES DE CALIBRACIÓN (mismo soporte)\n{'='*72}")
    for radio in RADIOS:
        pares = gw.rqd_calibration_pairs(radio_m=radio)
        if pares["status"] != "ok":
            print(f"\n  radio {radio:g} m → {pares.get('motivo')}")
            continue
        a = [p["rqd_mwd"] for p in pares["pares"]]
        b = [p["rqd_sondaje"] for p in pares["pares"]]
        rho = gw.spearman_rho(a, b)
        av, bv = np.array(a), np.array(b)
        print(f"\n  radio {radio:g} m — {len(pares['pares'])} par(es) de "
              f"{pares['n_intervalos']} intervalo(s), en {pares['n_sondajes']} "
              f"sondaje(s)")
        print(f"    sin soporte: {pares['intervalos_sin_soporte']} intervalo(s)")
        print(f"    rho(RQD_MWD, RQD_sondaje) = "
              f"{rho if rho is None else round(rho, 4)}")
        print(f"    RQD_MWD    : {av.min():.1f} a {av.max():.1f}  "
              f"media {av.mean():.1f}  sd {av.std():.2f}")
        print(f"    RQD sondaje: {bv.min():.1f} a {bv.max():.1f}  "
              f"media {bv.mean():.1f}  sd {bv.std():.2f}")
        print(f"    → el RQD_MWD tiene {av.std()/max(bv.std(),1e-9)*100:.0f}% de "
              "la dispersión del RQD de sondaje")
        # Pares por sondaje: es la unidad de la validación dejando-uno-fuera.
        por_s = {}
        for p in pares["pares"]:
            por_s[p["sondaje"]] = por_s.get(p["sondaje"], 0) + 1
        print(f"    pares por sondaje: {dict(sorted(por_s.items()))}")
        print(f"    {pares['validacion']}")
    print(f"\n  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
