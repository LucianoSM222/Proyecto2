"""
run_paso3.py — Calibración de los pesos del DI contra el RQD, datos reales.

Mismo procedimiento que Fernández et al. 2023, que busca los pesos de su DI
con varianza móvil (movvar): esto es ese procedimiento aplicado a los datos de
Punta del Cobre. La variante de convención no se toca.
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
OUT = os.path.join(HERE, "resultados")


def cargar():
    gw.seed_attribute_registry()
    gw.seed_di_variants()
    gw.seed_param_registry()
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

    print(f"\n{'='*72}\n  PARES CON VECINDAD POR SEGMENTO (no por bola)\n{'='*72}")
    for radio in RADIOS:
        pares = gw.rqd_calibration_pairs(radio_m=radio)
        if pares["status"] != "ok":
            print(f"  radio {radio:g} m → {pares.get('motivo')}")
            continue
        a = [p["rqd_mwd"] for p in pares["pares"]]
        b = [p["rqd_sondaje"] for p in pares["pares"]]
        rho = gw.spearman_rho(a, b)
        av, bv = np.array(a), np.array(b)
        print(f"  radio {radio:>4.0f} m · {len(a):>4} pares · "
              f"{pares['n_sondajes']} sondaje(s) · rho={rho if rho is None else round(rho,4):>7} "
              f"· sd(RQD_MWD)={av.std():>5.2f} sd(RQD_sond)={bv.std():>5.2f}")

    print(f"\n{'='*72}\n  CALIBRACIÓN\n{'='*72}")
    resultados = []
    for radio in RADIOS:
        t1 = time.time()
        rep = gw.calibrate_di_weights(radio_m=radio,
                                      nombre_variante=f"calibrada_RQD_{radio:g}m",
                                      n_muestras=300, seed=42)
        print(f"\n  ── radio {radio:g} m — status: {rep['status']}  "
              f"({time.time()-t1:.1f}s)")
        if rep["status"] != "ok":
            print(f"     {rep.get('motivo')}")
            continue
        resultados.append(rep)
        print(f"     pares={rep['n_pares']} · sondajes={rep['n_sondajes']} "
              f"{rep['sondajes']}")
        print(f"     pesos convención : {rep['pesos_convencion']}")
        print(f"     pesos calibrados : {rep['pesos']}")
        print(f"     rho convención   : {rep['rho_convencion']}")
        print(f"     rho ajuste       : {rep['rho_ajuste']}")
        print(f"     rho VALIDACIÓN   : {rep['rho_validacion']}")
        print(f"     {rep['veredicto']}")
        print(f"     pliegues (dejando-un-sondaje-fuera):")
        for pl in rep["validacion"]["pliegues"]:
            r = pl.get("rho")
            print(f"       {pl['sondaje']:<16} rho={('%+.3f' % r) if r is not None else '  n/d'}"
                  f"  n={pl.get('n_pares')}  pesos={pl.get('pesos_pliegue')}")

    print(f"\n{'='*72}\n  VARIANTES REGISTRADAS\n{'='*72}")
    for nombre, v in gw.di_variantes.items():
        marca = "  [SOLO LECTURA]" if v.get("solo_lectura") else ""
        print(f"  {nombre}{marca}")
        print(f"    ventana {v['window']} · umbral {v['threshold']} · pesos "
              f"{ {k: round(x, 4) for k, x in v['weights'].items()} }")

    os.makedirs(OUT, exist_ok=True)
    perfil = os.path.join(OUT, "perfil_faena_MPC.json")
    with open(perfil, "w", encoding="utf-8") as fh:
        fh.write(gw.export_site_profile())
    print(f"\n  perfil de faena exportado: {perfil}")
    print(f"  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
