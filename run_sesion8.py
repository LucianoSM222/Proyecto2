"""
run_sesion8.py — Discriminador fractura/contacto y RQD_MWD sobre los datos reales.

Guion de corrida, no parte de la aplicación. Carga los caserones, cruza
geometría, calcula el DI con la configuración de convención y clasifica los
picos que ese DI ya encontró. El contraste contra sondajes corre solo si hay
sondajes cargados y cerca; si no, el reporte lo declara.
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
    # Sondajes: son la ÚNICA fuente de etiquetas de contraste del
    # discriminador. Sin ellos el reporte se declara sin etiquetas y no hay
    # matriz — que es correcto, pero no es el resultado que buscamos.
    td = os.path.join(HERE, "test_data")
    archivos = {}
    for k in gw.DRILLHOLE_KINDS:
        p = os.path.join(td, f"MPC_{k}.csv")
        if os.path.exists(p):
            archivos[k] = open(p, "rb").read()
    if archivos:
        gw.load_drillhole_csvs(archivos)
        gw.refresh_drillhole_selection()
        n_est = sum(len([s for s in d.structures if s.get("tipo") != "contacto_derivado"])
                    for d in gw.drillholes.values())
        n_cto = sum(len([s for s in d.structures if s.get("tipo") == "contacto_derivado"])
                    for d in gw.drillholes.values())
        print(f"sondajes: {len(gw.drillholes)}  estructuras logueadas={n_est}  "
              f"contactos derivados={n_cto}")
    print(f"pozos={len(gw.wells)}  mallas={len(gw.layers)}  "
          f"sondajes={len(gw.drillholes)}  ({time.time()-t0:.1f}s)")

    print(f"\n{'='*72}\n  8 — DISCRIMINADOR FRACTURA / CONTACTO\n{'='*72}")
    disc = gw.discriminate_all()
    print(f"  status: {disc['status']}")
    if disc["status"] != "ok":
        print(f"  motivo: {disc.get('motivo')}")
    else:
        n = disc["n_picos"]
        print(f"  picos del DI clasificados: {n:,}".replace(",", "."))
        for k, v in disc["conteo"].items():
            print(f"    {k:<16} {v:>8,}  ({100.0*v/n:5.1f}%)".replace(",", "."))
        print(f"  config: {disc['config']}")
        # Motivos de indeterminación más frecuentes: dice QUÉ firma faltó.
        motivos = {}
        for p in disc["picos"]:
            if p["clase"] == "indeterminado" and p["motivo"]:
                motivos[p["motivo"]] = motivos.get(p["motivo"], 0) + 1
        if motivos:
            print("  motivos de indeterminación más frecuentes:")
            for m, c in sorted(motivos.items(), key=lambda x: -x[1])[:5]:
                print(f"    {c:>7,} · {m}".replace(",", "."))

    print(f"\n{'='*72}\n  8 — CONTRASTE CONTRA SONDAJES\n{'='*72}")
    for radio in (3.0, 10.0):
        rep = gw.discriminator_report(radio_m=radio)
        print(f"\n  radio {radio:g} m → status: {rep['status']}")
        if rep["status"] != "ok":
            print(f"    {rep.get('motivo')}")
            continue
        print(f"    pares={rep['n_pares']}  aciertos={rep['aciertos']}/"
              f"{rep['n_evaluables']}  indeterminados={rep['n_indeterminados']}")
        print(f"    matriz (filas=etiqueta de sondaje, cols=clase MWD):")
        for e, row in rep["matriz"].items():
            print(f"      {e:<14} {row}")
        print(f"    {rep['interpretacion']}")

    print(f"\n{'='*72}\n  8 — RQD_MWD (Deere sobre el perfil de DI)\n{'='*72}")
    rq = gw.rqd_mwd_report()
    print(f"  status: {rq['status']}")
    if rq["status"] == "ok":
        print(f"  {rq['definicion']}")
        print(f"  {rq['uso']}")
        print(f"  pozos evaluados: {len(rq['pozos'])}  no evaluables: {len(rq['no_evaluables'])}")
        for c, d in sorted(rq["caserones"].items()):
            print(f"    {c:<14} RQD_MWD={d['rqd_mwd']:>6.2f}%  "
                  f"pozos={d['n_pozos']:>4}  metraje={d['largo_m']:,.0f} m".replace(",", "."))
        vals = sorted(r["rqd_mwd"] for r in rq["pozos"])
        q = lambda f: vals[min(len(vals) - 1, int(f * len(vals)))]
        print(f"  por pozo — p10={q(0.10):.1f}  mediana={q(0.50):.1f}  p90={q(0.90):.1f}")
    else:
        print(f"  motivo: {rq.get('motivo')}")

    os.makedirs(OUT, exist_ok=True)
    for nombre, texto in (("sesion8_discriminador.csv", gw.export_discriminator_csv()),
                          ("sesion8_rqd_mwd.csv", gw.export_rqd_mwd_csv(rq))):
        path = os.path.join(OUT, nombre)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(texto)
        print(f"  CSV: {path}  ({len(texto):,} bytes)".replace(",", "."))
    print(f"  total: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
