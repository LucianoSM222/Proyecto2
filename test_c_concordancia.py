"""
test_c_concordancia.py — Sesión C (docs/C_concordancia.md).

C.0 — ENCUADRE, que gobierna todo lo demás: esto es ANÁLISIS DE CONCORDANCIA,
no validación. La malla de Leapfrog NO es verdad terreno: es una interpolación
construida desde los sondajes, casi exacta junto al sondaje porque ahí está
restringida, e hipótesis progresivamente más débil al alejarse. Un desacuerdo
entre MWD y malla no es un error del MWD hasta que se demuestre cuál de los
dos falla.

C.1 es BLOQUEANTE y es el corazón: si el modelo se entrenó con etiquetas
derivadas de una malla, comparar sus predicciones contra ESA MISMA malla solo
demuestra memorización. El sistema debe RECHAZAR ese reporte e indicar por
qué. Este archivo prueba primero que el rechazo ocurre cuando debe ocurrir, y
—igual de importante— que NO ocurre cuando la comparación sí es admisible:
una guardia que rechace todo sería tan inútil como una que no rechace nada.

Comparaciones admitidas (C.1):
  1. Contra registros de sondaje — fuente independiente del entrenamiento.
  2. Contra la malla del caserón EXCLUIDO del entrenamiento.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import geomech_wizard as gw

FAILURES = []


def check(cond, label, detail=""):
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}" + (f"  → {detail}" if detail else ""))
        FAILURES.append(label)


def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


def reset():
    gw.seed_attribute_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.attribute_exclusions.clear(); gw.pending_aliases.clear()
    gw.attribute_meters.clear(); gw.drillholes.clear()
    gw.rf_model = None; gw.rf_stats = None
    gw.training_provenance_reset()
    gw.set_training_caserones(None)


def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    f = [(0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,5,1),(0,4,5),
         (2,6,7),(2,7,3),(0,3,7),(0,7,4),(1,5,6),(1,6,2)]
    return np.array([[v[a],v[b],v[c]] for a,b,c in f], dtype=np.float64)


E0, N0, Z0 = 376700.0, 6958900.0, 300.0


def _mk_layer(name, attr, caseron, box=None):
    tris = box if box is not None else _box(E0, N0, Z0, E0+40, N0+40, Z0+40)
    lay = gw.Layer(name=name, kind="litologia", triangles=tris,
                   bbox_min=tris.reshape(-1,3).min(0), bbox_max=tris.reshape(-1,3).max(0))
    gw.set_layer_attributes(lay, {"litologia": attr})
    lay.caseron = caseron
    gw.layers[name] = lay
    return lay


def _mk_well(wn, caseron, dominio, n=30, capa=None, este=None):
    rng = np.random.default_rng(abs(hash(wn)) % 2**31)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i*0.02, vel=float(rng.uniform(1,9)), pp=float(rng.uniform(1,9)),
                        pa=float(rng.uniform(1,9)), pd=float(rng.uniform(1,9)),
                        pr=float(rng.uniform(1,9)), pf=float(rng.uniform(1,9)),
                        se=float(rng.uniform(1,9)), t=0.0,
                        este=(este if este is not None else E0+10)+i*0.01,
                        norte=N0+10, cota=Z0+10)
        p.dominio = dominio; p.lito = dominio; p.entrenable = True; p.di = 0.5
        p.capa_lito = capa
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"{caseron}_PR01_TH_P01", hole_id=wn, points=pts)
    w.caseron = caseron
    gw.wells[wn] = w
    return w


def _escenario_dos_caserones():
    """
    Entrena con CAS_A; CAS_B queda como holdout. Es el escenario de C.1: la
    malla de CAS_B nunca produjo etiquetas, así que comparar contra ella es
    admisible; la de CAS_A sí, y comparar contra ella es circular.
    """
    reset()
    gw.domains["Bht"] = {"ucs_lab": 128.1, "atributo_id": "Bht", "nombre": "Bht"}
    gw.domains["Kfa"] = {"ucs_lab": 289.6, "atributo_id": "Kfa", "nombre": "Kfa"}
    _mk_layer("CAS_A:Bht", "Bht", "CAS_A")
    _mk_layer("CAS_A:Kfa", "Kfa", "CAS_A")
    _mk_layer("CAS_B:Bht", "Bht", "CAS_B")
    _mk_well("A1", "CAS_A", "Bht", capa="CAS_A:Bht")
    _mk_well("A2", "CAS_A", "Kfa", capa="CAS_A:Kfa")
    _mk_well("A3", "CAS_A", "Bht", capa="CAS_A:Bht")
    _mk_well("B1", "CAS_B", "Bht", capa="CAS_B:Bht")
    gw.set_training_caserones({"CAS_A"})       # CAS_B = holdout


# ─────────────────────────────────────────────────────────────────────────────
def c1_procedencia_registrada():
    section("C.1 — El entrenamiento registra DE QUÉ mallas salieron sus etiquetas")
    _escenario_dos_caserones()
    stats = gw.train_rf(0.0, 450.0)
    check("error" not in stats, "el modelo entrena en el escenario base", stats.get("error"))

    prov = gw.training_provenance()
    check(prov["capas"] == {"CAS_A:Bht", "CAS_A:Kfa"},
          "la procedencia nombra las capas que aportaron etiquetas", prov["capas"])
    check(prov["caserones"] == {"CAS_A"},
          "y los caserones de esos puntos", prov["caserones"])
    check("CAS_B:Bht" not in prov["capas"],
          "una capa cuyos puntos NO entrenaron queda fuera de la procedencia")


def c1_rechaza_la_misma_malla():
    section("C.1 — RECHAZA comparar contra la malla que produjo las etiquetas")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)

    veredicto = gw.circularity_check(["CAS_A:Bht"])
    check(veredicto is not None, "comparar contra una malla de entrenamiento se RECHAZA")
    check("CAS_A:Bht" in (veredicto or ""), "el motivo nombra la malla culpable", veredicto)
    check("memoriz" in (veredicto or "").lower(),
          "el motivo explica QUÉ demostraría la comparación (memorización)", veredicto)

    rep = gw.concordance_report(fuente="malla", capas=["CAS_A:Bht"])
    check(rep["status"] == "rechazado",
          "concordance_report devuelve status=rechazado, no un número", rep.get("status"))
    check("motivo" in rep and rep["motivo"], "y trae el motivo del rechazo")
    check("concordancia" not in rep,
          "NO se calcula ninguna métrica de concordancia en un reporte rechazado",
          list(rep))

    # Mezclar una malla válida con una de entrenamiento tampoco pasa: bastaría
    # una sola contaminada para que el resultado global sea circular.
    rep2 = gw.concordance_report(fuente="malla", capas=["CAS_B:Bht", "CAS_A:Kfa"])
    check(rep2["status"] == "rechazado",
          "una sola malla de entrenamiento contamina todo el reporte", rep2.get("status"))


def c1_admite_las_comparaciones_validas():
    section("C.1 — ADMITE las dos comparaciones válidas (no rechaza todo)")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)

    check(gw.circularity_check(["CAS_B:Bht"]) is None,
          "la malla del caserón EXCLUIDO es comparación admitida",
          gw.circularity_check(["CAS_B:Bht"]))
    check(gw.circularity_check([]) is None,
          "comparar contra sondajes (sin mallas) es admitido")

    rep = gw.concordance_report(fuente="sondajes")
    check(rep["status"] != "rechazado",
          "el reporte contra sondajes NO se rechaza por circularidad", rep.get("motivo"))


def c1_sin_modelo_no_hay_reporte():
    section("C.1 — Sin modelo entrenado no hay procedencia que verificar")
    reset()
    rep = gw.concordance_report(fuente="malla", capas=["X"])
    check(rep["status"] == "sin_modelo",
          "sin modelo entrenado el reporte lo declara, no finge un resultado",
          rep.get("status"))
    check(gw.circularity_check(["X"]) is not None,
          "y la guardia no deja pasar la comparación por omisión")


def c0_terminologia():
    section("C.0 — Terminología: nunca 'corregido' ni 'exacto' en las salidas")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    salidas = [
        str(gw.concordance_report(fuente="malla", capas=["CAS_A:Bht"])),
        str(gw.concordance_report(fuente="sondajes")),
        str(gw.circularity_check(["CAS_A:Bht"])),
    ]
    for i, s in enumerate(salidas):
        low = s.lower()
        check("corregido" not in low, f"salida {i}: no aparece «corregido»")
        check("exacto" not in low and "exacta" not in low,
              f"salida {i}: no aparece «exacto/exacta»")
    check("informado por mwd" in " ".join(salidas).lower(),
          "la terminología obligatoria «modelo geológico informado por MWD» sí aparece")


# ─────────────────────────────────────────────────────────────────────────────
def _mk_sondaje(hid, este, norte, cota, largo=50.0, unidad="Bht"):
    """Sondaje sintético vertical con una sola unidad logueada."""
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=norte, z_utm=cota, length=largo)
    dh.trace = [(d, este, norte, cota - d) for d in np.arange(0, largo + 0.5, 1.0)]
    dh.lithology = [{"from": 0.0, "to": largo, "unidad": unidad}]
    gw.drillholes[hid] = dh
    return dh


def c3_distancia_al_sondaje():
    section("C.3 — Distancia al sondaje más cercano")
    reset()
    _mk_sondaje("S1", E0, N0, Z0 + 50)
    d0 = gw.distancia_a_sondaje(E0, N0, Z0 + 25)
    check(abs(d0) < 1.5, "un punto sobre la traza da distancia ~0", d0)
    d1 = gw.distancia_a_sondaje(E0 + 30, N0, Z0 + 25)
    check(abs(d1 - 30.0) < 1.5, "un punto a 30 m lateral da ~30 m", d1)
    check(gw.distancia_a_sondaje(E0, N0, Z0) is not None, "siempre devuelve un número")

    reset()
    check(gw.distancia_a_sondaje(E0, N0, Z0) is None,
          "sin sondajes cargados devuelve None, no un 0 engañoso")


def c3_concordancia_decae_con_la_distancia():
    section("C.3 — Concordancia vs distancia: se reporta la PENDIENTE")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    gw.predict_all_wells()          # sin predicciones no hay nada que contrastar
    _mk_sondaje("S1", E0 + 10, N0 + 10, Z0 + 40, largo=40, unidad="Bht")

    rep = gw.concordance_vs_distance(fuente="sondajes", n_bins=4)
    check(rep["status"] == "ok", "el diagnóstico principal corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check("pendiente" in rep, "reporta la PENDIENTE, no solo el gráfico", list(rep))
    check("interpretacion" in rep and rep["interpretacion"],
          "y la interpretación del signo de esa pendiente", rep.get("interpretacion"))
    check(isinstance(rep["bins"], list) and rep["bins"],
          "trae los bins con su concordancia y su n", rep.get("bins"))
    for b in rep["bins"]:
        check(set(("d_min", "d_max", "n", "concordancia")) <= set(b),
              "cada bin declara rango, n y concordancia", b)
        break
    low = str(rep).lower()
    check("error" not in low.replace("errores", ""),
          "el desacuerdo NUNCA se llama «error» (C.2 nivel 2)", rep.get("interpretacion"))


def c4_estructura_espacial_del_desacuerdo():
    section("C.4 — Desacuerdo por distancia al borde de malla")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    d = gw.distancia_a_borde_malla(E0 + 20, N0 + 20, Z0 + 20, "CAS_A:Bht")
    check(d is not None and d > 0, "un punto interior tiene distancia al borde > 0", d)
    d_borde = gw.distancia_a_borde_malla(E0 + 0.2, N0 + 20, Z0 + 20, "CAS_A:Bht")
    check(d_borde is not None and d_borde < d,
          "un punto pegado al borde da menos distancia que uno interior", (d_borde, d))

    rep = gw.disagreement_vs_mesh_edge(fuente="sondajes")
    check(rep["status"] in ("ok", "sin_desacuerdos", "sin_datos"),
          "el reporte declara su estado", rep.get("status"))
    if rep["status"] == "ok":
        check("histograma" in rep, "trae el histograma que pide C.4", list(rep))
        check("interior_macizo" in rep,
              "y separa el desacuerdo de borde del interior macizo", list(rep))


def c5_desfase_de_contactos():
    section("C.5 — Desfase δ de contactos: media, mediana, desviación y sesgo")
    reset()
    rep = gw.contact_offset_report()
    check(rep["status"] in ("ok", "sin_datos"), "declara su estado", rep.get("status"))

    # Escenario sintético: contactos de malla desplazados 3 m respecto del MWD.
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    rep = gw.contact_offset_report()
    if rep["status"] == "ok":
        for k in ("media", "mediana", "desviacion", "sesgo", "n"):
            check(k in rep, f"reporta {k}", list(rep))
        check("interpretacion" in rep,
              "distingue sesgo sistemático (malla desplazada) de dispersión (ruido)")


def c6_matriz_de_confusion():
    section("C.6 — Matriz de confusión cruzada con el traslape de bandas (B.7)")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    gw.predict_all_wells()
    _mk_sondaje("S1", E0 + 10, N0 + 10, Z0 + 40, largo=40, unidad="Bht")

    rep = gw.confusion_matrix_report(fuente="sondajes")
    check(rep["status"] in ("ok", "sin_datos"), "declara su estado", rep.get("status"))
    if rep["status"] != "ok":
        return
    check("matriz" in rep and "unidades" in rep, "trae matriz y unidades", list(rep))
    check("concordancia_global" in rep, "reporta concordancia global")
    check("por_unidad" in rep, "y concordancia por unidad")
    check("pares_confundidos" in rep, "lista los pares que más se confunden")
    check("cruce_traslape_ucs" in rep,
          "CRUZA con B.7: los pares confundidos contra el traslape de bandas",
          list(rep))


def c7_exportacion():
    section("C.7 — Salidas exportables")
    _escenario_dos_caserones()
    gw.train_rf(0.0, 450.0)
    gw.predict_all_wells()
    _mk_sondaje("S1", E0 + 10, N0 + 10, Z0 + 40, largo=40, unidad="Bht")

    full = gw.concordance_full_report(fuente="sondajes")
    check(set(("encuadre", "c3", "c4", "c5", "c6")) <= set(full),
          "el reporte completo reúne C.3 a C.6", list(full))
    csv = gw.export_concordance_csv(full)
    check(isinstance(csv, str) and len(csv) > 0, "se exporta como CSV")
    low = (csv + str(full)).lower()
    check("corregido" not in low, "la exportación no dice «corregido»")
    check("exacto" not in low and "exacta" not in low, "ni «exacto/exacta»")
    check(gw.TERMINOLOGIA_C.lower() in low,
          "y sí lleva la terminología obligatoria")

    # C.7 pide el listado de zonas de desacuerdo interior con coordenadas.
    zonas = gw.interior_disagreement_zones(fuente="sondajes")
    check(isinstance(zonas, list), "las zonas de desacuerdo interior son una lista")
    if zonas:
        z = zonas[0]
        check(set(("este", "norte", "cota")) <= set(z),
              "cada zona trae coordenadas para que geología la revise", z)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    c1_procedencia_registrada,
    c1_rechaza_la_misma_malla,
    c1_admite_las_comparaciones_validas,
    c1_sin_modelo_no_hay_reporte,
    c0_terminologia,
    c3_distancia_al_sondaje,
    c3_concordancia_decae_con_la_distancia,
    c4_estructura_espacial_del_desacuerdo,
    c5_desfase_de_contactos,
    c6_matriz_de_confusion,
    c7_exportacion,
]


def test_c_concordancia():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        # El reparto entrena/prueba es estado GLOBAL: dejarlo fijado
        # contaminaría las suites que corran después, cuyos pozos no son de
        # estos caserones sintéticos y quedarían fuera del entrenamiento.
        reset()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ SESIÓN C — todas las verificaciones pasaron.")
    print("=" * 72)
