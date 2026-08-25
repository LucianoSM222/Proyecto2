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
ALL_TESTS = [
    c1_procedencia_registrada,
    c1_rechaza_la_misma_malla,
    c1_admite_las_comparaciones_validas,
    c1_sin_modelo_no_hay_reporte,
    c0_terminologia,
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
