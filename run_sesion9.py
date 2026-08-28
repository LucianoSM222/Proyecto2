"""
run_sesion9.py — Modelo de bloques sobre los datos reales.

Carga los caserones, cruza geometría, entrena, predice UCS punto a punto e
interpola al modelo de bloques con máscara de soporte. Exporta CSV y DXF.
"""

import os, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geomech_wizard as gw
import vocabulario_mpc as voc
import cargar_caserones as cc

CASERONES = ["PCS_1043", "PCC_0042", "PCC_1541"]
OUT = os.path.join(HERE, "resultados")


def main():
    t0 = time.time()
    gw.seed_attribute_registry()
    voc.aplicar_vocabulario_mpc(verbose=False)
    voc.aplicar_bandas_ucs(verbose=False)
    for c in CASERONES:
        cc.cargar_caseron(c, verbose=False)
    gw.classify_all_wells_cached()
    gw.build_domain_index()
    gw.compute_di()
    print(f"pozos={len(gw.wells)}  mallas={len(gw.layers)}  ({time.time()-t0:.1f}s)")

    t1 = time.time()
    res = gw.train_rf()
    print(f"entrenamiento: {({k: res[k] for k in res if k != 'model'})}  "
          f"({time.time()-t1:.1f}s)")
    if res.get("error"):
        print("  sin modelo entrenado: el modelo de bloques no puede correr.")
        return
    gw.predict_all_wells()

    print(f"\n{'='*72}\n  9 — MODELO DE BLOQUES (IDW anisotrópico)\n{'='*72}")
    t2 = time.time()
    rep = gw.interpolate_block_model()
    print(f"  status: {rep['status']}  ({time.time()-t2:.1f}s)")
    if rep["status"] != "ok":
        print(f"  motivo: {rep.get('motivo')}")
        return
    tot = rep["n_bloques"] + rep["n_vacios"]
    print(f"  bloque {rep['bloque_m']:g} m · IDW p={rep['potencia']:g} · "
          f"anisotropía {rep['anisotropia']} · radio {rep['radio_h_m']:g}/"
          f"{rep['radio_v_m']:g} m")
    print(f"    {'caserón':<12}{'bloques':>9}{'vacíos':>9}{'fuera':>10}"
          f"{'cobertura':>11}  encajonado (E×N×Z m)")
    for c, d in sorted(rep.get("por_caseron", {}).items()):
        print(f"    {c:<12}{d['n_bloques']:>9,}{d['n_vacios']:>9,}"
              f"{d['n_fuera_del_dominio']:>10,}{d['cobertura']*100:>10.1f}%  "
              f"{d['encajonado_m']}".replace(",", "."))
    print(f"  muestras MWD con UCS: {rep['n_muestras']:,}".replace(",", "."))
    print(f"  bloques con valor : {rep['n_bloques']:,}".replace(",", "."))
    print(f"  bloques VACÍOS    : {rep['n_vacios']:,}  "
          f"({100.0*rep['n_vacios']/tot:.1f}% del volumen encajonado)".replace(",", "."))
    print(f"  {rep['motivo_vacios']}")

    res_b = gw.block_model_summary(rep)
    print(f"\n  por banda ISRM ({rep['bandas_fuente']}):")
    print(f"    {'banda':<18}{'bloques':>9}{'m³':>12}{'UCS med':>9}"
          f"{'DI med':>9}{'conf med':>10}")
    for banda, d in res_b["por_banda"].items():
        print(f"    {banda:<18}{d['n_bloques']:>9,}{d['volumen_m3']:>12,.0f}"
              f"{d['ucs_mediana']:>9.1f}"
              f"{(d['di_mediana'] if d['di_mediana'] is not None else float('nan')):>9.3f}"
              f"{d['confianza_mediana']:>10.3f}".replace(",", "."))
    print(f"\n  cobertura del encajonado: {res_b['cobertura']*100:.1f}%")
    print(f"  {rep['definicion_confianza']}")

    os.makedirs(OUT, exist_ok=True)
    csv_path = os.path.join(OUT, "sesion9_modelo_bloques.csv")
    texto = gw.export_block_model_csv(rep)
    with open(csv_path, "w", encoding="utf-8") as fh:
        fh.write(texto)
    print(f"\n  CSV: {csv_path}  ({len(texto):,} bytes)".replace(",", "."))
    dxf_path = os.path.join(OUT, "sesion9_modelo_bloques.dxf")
    gw.export_block_model_dxf(rep, dxf_path)
    print(f"  DXF: {dxf_path}  ({os.path.getsize(dxf_path)/1e6:.1f} MB)")
    print(f"  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
