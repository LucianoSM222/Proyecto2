"""
run_sesion7.py — Curvas de respuesta a PP sobre los caserones reales.

No es parte de la aplicación: es el guion de la corrida que produce las
tablas del capítulo. Carga los caserones, cruza geometría, y saca las curvas
PP -> (ROP, SE, CV(SE)) POR DOMINIO más el agregado, que se imprime solo
para mostrar la trampa que documenta la sesión 7.
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
    print(f"pozos={len(gw.wells)}  puntos={sum(len(w.points) for w in gw.wells.values()):,}"
          f"  mallas={len(gw.layers)}  ({time.time()-t0:.1f}s)")

    t1 = time.time()
    gw.classify_all_wells_cached()
    gw.build_domain_index()
    print(f"cruce: {time.time()-t1:.1f}s  dominios={len(gw.domains)}")

    print(f"\n{'='*72}\n  7 — CURVAS DE RESPUESTA A PP\n{'='*72}")
    rep = gw.pp_response_curves()
    print(f"  status: {rep['status']}")
    if rep["status"] != "ok":
        print(f"  motivo: {rep.get('motivo')}")
        return
    print(f"  {rep['advertencia_confundimiento']}")
    for dom, d in sorted(rep["dominios"].items()):
        print(f"\n  ── {dom}  (n={d['n_puntos']:,})".replace(",", "."))
        print(f"     pendiente ROP/bar : {d['pendiente_rop']}")
        print(f"     PP saturación     : {d['pp_saturacion']}")
        print(f"     {d['interpretacion']}")
        print(f"       {'PP':>6} {'n':>8} {'ROP':>8} {'SE':>10} {'CV(SE)':>8}")
        for pt in d["curva"]:
            print(f"       {pt['pp']:>6.0f} {pt['n']:>8d} {pt['rop_mediana']:>8.3f} "
                  f"{pt['se_mediana']:>10.1f} {pt['cv_se']:>8.3f}")

    agg = rep.get("agregado_todos_los_dominios", {})
    print(f"\n  ── AGREGADO (NO USAR)")
    print(f"     pendiente ROP/bar : {agg.get('pendiente_rop')}")
    print(f"     {agg.get('advertencia')}")

    print(f"\n{'='*72}\n  7 — PRESCRIPCIÓN POR DOMINIO\n{'='*72}")
    for dom in sorted(rep["dominios"]):
        for obj in ("rop", "estabilidad"):
            rec = gw.pp_prescription(dom, objetivo=obj)
            if rec["status"] == "ok":
                print(f"  {dom:<24} {obj:<12} PP={rec['pp_recomendada']:.0f} bar  "
                      f"{rec.get('justificacion','')}")
            else:
                print(f"  {dom:<24} {obj:<12} SIN RECOMENDACIÓN — {rec.get('motivo')}")

    print(f"\n{'='*72}\n  7 — ANTICIPACIÓN DE CONTACTOS\n{'='*72}")
    ant = gw.contact_anticipation()
    print(f"  status: {ant['status']}  fuente_margen: {ant.get('fuente_margen')}")
    print(f"  margen_m: {ant.get('margen_m')}")
    for k in ("motivo", "advertencia", "interpretacion"):
        if ant.get(k):
            print(f"  {k}: {ant[k]}")

    os.makedirs(OUT, exist_ok=True)
    csv = gw.export_pp_curves_csv(rep)
    path = os.path.join(OUT, "sesion7_curvas_pp.csv")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(csv)
    print(f"\n  CSV: {path}  ({len(csv):,} bytes)".replace(",", "."))
    print(f"  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
