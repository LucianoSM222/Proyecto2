"""
run_sesion10.py — Kit completo del Capítulo 5 sobre los datos reales.

Corre el pipeline entero (carga, cruce, DI, entrenamiento, predicción,
modelo de bloques) y después genera el kit: todas las figuras y tablas con
nomenclatura consistente, más el índice que mapea cada archivo a su sección.

De paso imprime el modelo de bloques por caserón, que es la corrida real de
la sesión 9.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
OUT = os.path.join(HERE, "resultados")
KIT = os.path.join(OUT, "kit_capitulo5")


def main():
    t0 = time.time()
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
    res = gw.train_rf()
    if res.get("error"):
        print(f"sin modelo entrenado: {res['error']}")
    else:
        gw.predict_all_wells()
    print(f"pozos={len(gw.wells)}  mallas={len(gw.layers)}  "
          f"sondajes={len(gw.drillholes)}  R²CV={res.get('cv_r2_mean')}  "
          f"({time.time()-t0:.1f}s)")

    print(f"\n{'='*72}\n  9 — MODELO DE BLOQUES POR CASERÓN\n{'='*72}")
    rep = gw.interpolate_block_model()
    print(f"  status: {rep['status']}")
    if rep["status"] == "ok":
        print(f"  bloque {rep['bloque_m']:g} m · anisotropía {rep['anisotropia']} · "
              f"radio {rep['radio_h_m']:g}/{rep['radio_v_m']:g} m")
        print(f"    {'caserón':<12}{'bloques':>9}{'vacíos':>10}{'cobertura':>11}"
              f"{'muestras':>11}  encajonado (E×N×Z m)")
        for c, d in sorted(rep["por_caseron"].items()):
            print(f"    {c:<12}{d['n_bloques']:>9,}{d['n_vacios']:>10,}"
                  f"{d['cobertura']*100:>10.1f}%{d['n_muestras']:>11,}  "
                  f"{d['encajonado_m']}".replace(",", "."))
        res_b = gw.block_model_summary(rep)
        print(f"\n    {'banda ISRM':<18}{'bloques':>9}{'m³':>12}{'UCS med':>9}"
              f"{'DI med':>9}{'conf med':>10}")
        for banda, d in res_b["por_banda"].items():
            di_m = d["di_mediana"] if d["di_mediana"] is not None else float("nan")
            print(f"    {banda:<18}{d['n_bloques']:>9,}{d['volumen_m3']:>12,.0f}"
                  f"{d['ucs_mediana']:>9.1f}{di_m:>9.3f}"
                  f"{d['confianza_mediana']:>10.3f}".replace(",", "."))

    print(f"\n{'='*72}\n  10 — KIT DEL CAPÍTULO 5\n{'='*72}")
    t1 = time.time()
    kit = gw.build_chapter5_kit(KIT)
    print(f"  destino: {KIT}")
    print(f"  generados: {kit['n_generados']} · no generados: {kit['n_fallidos']} "
          f"de {len(kit['items'])}  ({time.time()-t1:.1f}s)")
    seccion = None
    for i in kit["items"]:
        if i["seccion"] != seccion:
            seccion = i["seccion"]
            print(f"\n  {seccion}")
        marca = "✓" if i["estado"] == "ok" else "✗"
        detalle = i["archivo"] or (i["motivo"] or "")[:90]
        print(f"    {marca} {i['id']:<6} {i['titulo'][:46]:<46} {detalle}")
        if i.get("nota"):
            print(f"      nota: {i['nota']}")
    print(f"\n  índice: {kit['indice_csv']} · {kit['indice_md']}")
    print(f"  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
