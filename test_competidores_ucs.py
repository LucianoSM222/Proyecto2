"""
test_competidores_ucs.py — Tres formas de estimar UCS, una sola vara.

EL CAMBIO DE ENCUADRE, por decisión del autor.

La auditoría demostró que el R² sobre PUNTOS no significa nada: con la etiqueta
constante por litología, predecir la media del dominio da R² = 1,000000 exacto.
Ese resultado sigue en pie y no se discute acá.

Lo que estaba mal no era el objetivo: era la MÉTRICA. La pregunta que la
memoria hace de verdad es otra —

    dada la respuesta de perforación de una roca que el modelo NUNCA VIO,
    ¿cuál es su UCS?

— y esa sí se puede contestar: se deja UNA LITOLOGÍA FUERA, se ajusta con las
demás, se predice el ancla de la que se sacó, y se anota el error EN MPa. Con
esa vara la etiqueta constante deja de ser el problema, porque no se está
midiendo variación dentro del dominio sino transferencia a un dominio nuevo.

TRES COMPETIDORES, la misma vara:

  · línea base   ignora el MWD, predice la media de las anclas de entrenamiento.
                 Es el piso que los otros dos TIENEN que superar. Si no lo
                 superan, el MWD no aporta y eso también es un resultado.
  · relación     SE mediana por litología y estrato de PP → curva SE↔UCS,
                 aplicada punto a punto. Es como se calibran la dureza Leeb y
                 el índice de carga puntual: práctica estándar, no un rodeo.
  · ML           las siete variables menos SE, cuyos cuatro componentes ya
                 están (SE = (PP+RP+AP)/ROP, verificado con error 3,5e-07).

El nombre de la memoria dice "machine learning" y por eso el ML corre siempre.
Si pierde contra la relación directa, se reporta que perdió: demostrarlo es un
resultado legítimo, pero hay que demostrarlo, no suponerlo.

SIN ACOTE A LA BANDA DE LA LITOLOGÍA. Se probó y se descartó: un punto sin
litología no tiene banda, acotar impide que el modelo diga "más duro que su
rango documentado" —que es el hallazgo que uno querría ver— y rompe el caso de
uso de los tiros piloto, donde todavía NO se conoce la litología. Se acota solo
a los límites físicos 0–450 MPa, que aplican a todo punto, y cada punto lleva
su marca de banda como INFORMACIÓN, no como corrección.
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
    gw.seed_di_variants(force=True)
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear(); gw.attribute_exclusions.clear()
    gw.set_training_caserones(None)


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _escenario(n_litos=4, seed=0):
    """
    Cuatro litologías con anclas conocidas y una respuesta MWD que las ordena.
    La SE se construye MONÓTONA con la UCS: es el caso en que la relación
    directa DEBE funcionar. Si no funciona acá, no funciona nunca.
    """
    reset()
    rng = np.random.default_rng(seed)
    anclas = {"Bht": 128.1, "Kfa": 289.6, "Lutitas_normales": 126.0,
              "Kpcsb_sedimentaria": 83.6}
    items = list(anclas.items())[:n_litos]
    for k, (lito, ucs) in enumerate(items):
        for w_i in range(4):                      # cuatro pozos por litología
            wn = f"{lito}_W{w_i}"
            pts = []
            for i in range(220):
                # SE crece con la UCS; ROP baja. PP la mueve el operador.
                pp = float(rng.choice([110.0, 150.0, 200.0]))
                se = ucs * 2.4 + rng.normal(0, 18.0)
                rop = max(0.05, 2.2 - ucs / 180.0 + rng.normal(0, 0.05))
                pa = float(60.0 + rng.normal(0, 3))
                pr = float(se * rop - pp - pa)     # cierra la identidad de SE
                p = gw.MWDPoint(largo=i * 0.02, vel=rop, pp=pp, pa=pa,
                                pd=float(75.0 + rng.normal(0, 4)), pr=pr,
                                pf=float(8.0 + rng.normal(0, .5)),
                                se=(pp + pr + pa) / rop, t=0.0)
                p.este = E0 + k * 40.0 + w_i * 3.0
                p.norte = N0; p.cota = Z0 - i * 0.02
                p.entrenable = True
                p.dominio = lito; p.lito = lito
                p.di = 0.4
                pts.append(p)
            w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{lito}", hole_id=wn,
                        points=pts)
            w.caseron = "CAS_A"
            gw.wells[wn] = w
        gw.domains[lito] = {"count": 880, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}
    return anclas


# ─────────────────────────────────────────────────────────────────────────────
def la_vara_deja_una_litologia_fuera():
    section("Vara — dejar una litología fuera, error en MPa")
    _escenario()
    rep = gw.leave_one_lithology_out("relacion")
    check(rep["status"] == "ok", "la evaluación corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    for k in ("mae_mpa", "rmse_mpa", "n_litologias", "pliegues", "metodo"):
        check(k in rep, f"declara {k}", sorted(rep))
    check(rep["n_litologias"] == 4, "un pliegue por litología", rep["n_litologias"])
    check(len(rep["pliegues"]) == 4, "y los cuatro se reportan uno a uno")
    for pl in rep["pliegues"]:
        for k in ("litologia", "ucs_real", "ucs_predicho", "error_mpa"):
            check(k in pl, f"cada pliegue declara {k}", sorted(pl))
        break
    check(rep["mae_mpa"] >= 0, "el error va en MPa, no en R²", rep["mae_mpa"])
    # Con menos de tres litologías no hay vara: dejar una fuera deja una sola.
    _escenario(n_litos=2)
    r2 = gw.leave_one_lithology_out("relacion")
    check(r2["status"] != "ok",
          "con dos litologías se declara que no hay vara, en vez de dar un "
          "número que nadie puede interpretar", r2.get("motivo"))
    check(r2.get("motivo"), "con el motivo", r2.get("motivo"))


def los_tres_competidores_corren():
    section("Competidores — línea base, relación directa y ML, misma vara")
    _escenario()
    comp = gw.compare_ucs_methods()
    check(comp["status"] == "ok", "la comparación corre", comp.get("motivo"))
    if comp["status"] != "ok":
        return
    metodos = {m["metodo"] for m in comp["metodos"]}
    check({"linea_base", "relacion", "ml"} <= metodos,
          "los tres compiten", sorted(metodos))
    for m in comp["metodos"]:
        check("mae_mpa" in m or m.get("motivo"),
              f"{m['metodo']}: entrega error o motivo", m)
    check(comp.get("ganador"), "se declara un ganador", comp.get("ganador"))
    check(comp.get("n_anclas"), "y con cuántas anclas se decidió",
          comp.get("n_anclas"))
    check(comp.get("advertencia_n"),
          "con la advertencia de que cuatro anclas no zanjan nada",
          comp.get("advertencia_n"))
    # La línea base es el PISO: se reporta siempre, gane o pierda.
    lb = [m for m in comp["metodos"] if m["metodo"] == "linea_base"][0]
    check("mae_mpa" in lb,
          "la línea base entrega su número: es lo que los otros deben superar",
          lb)


def el_ml_no_usa_se():
    section("ML — SE fuera de las predictoras, sus componentes ya están")
    _escenario()
    comp = gw.compare_ucs_methods()
    ml = [m for m in comp["metodos"] if m["metodo"] == "ml"][0]
    check("se" not in (ml.get("predictoras") or []),
          "SE no está entre las predictoras del ML", ml.get("predictoras"))
    check(set(ml.get("predictoras") or []) == {"vel", "pp", "pa", "pd", "pr", "pf"},
          "están sus cuatro componentes y las otras dos", ml.get("predictoras"))
    check(ml.get("motivo_sin_se"),
          "y se declara POR QUÉ se sacó, con el número que lo justifica",
          ml.get("motivo_sin_se"))
    # SE sigue existiendo: es el eje de la relación directa.
    rel = [m for m in comp["metodos"] if m["metodo"] == "relacion"][0]
    check("se" in (rel.get("predictoras") or []),
          "y en la relación directa SE es el modelo, no una predictora más",
          rel.get("predictoras"))


def la_relacion_da_un_valor_por_punto():
    section("Relación — cada medición recibe su propio valor, no la constante")
    _escenario()
    rep = gw.predict_ucs_relacion()
    check(rep["status"] == "ok", "la relación predice", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    vals = [p.ucs_ml for w in gw.wells.values() for p in w.points
            if p.ucs_ml is not None]
    check(len(vals) > 1000, "sobre todos los puntos", len(vals))
    # Dentro de UNA litología los valores tienen que VARIAR: ese es el punto.
    de_bht = [p.ucs_ml for w in gw.wells.values() for p in w.points
              if p.lito == "Bht" and p.ucs_ml is not None]
    check(len(set(de_bht)) > 50,
          "y VARÍAN dentro de una misma litología: es un valor por medición, "
          "no la constante del dominio repetida", len(set(de_bht)))
    check(min(vals) >= 0.0 and max(vals) <= 450.0,
          "acotados a los límites físicos", (min(vals), max(vals)))


def cada_punto_declara_su_modelo():
    section("Procedencia — la predicción dice de qué modelo salió")
    _escenario()
    gw.predict_ucs_relacion()
    p = next(p for w in gw.wells.values() for p in w.points if p.ucs_ml is not None)
    check(p.ucs_modelo == "relacion",
          "un punto predicho por la relación lo declara", p.ucs_modelo)
    check("relacion" in gw.ucs_model_summary(),
          "y el resumen nombra el modelo vigente", gw.ucs_model_summary())


def la_marca_de_banda_informa_no_corrige():
    section("Banda — se marca el apartamiento, NO se acota la predicción")
    _escenario()
    a = gw.attr_registry["Bht"]
    lo, hi = a.ucs_min, a.ucs_max
    gw.predict_ucs_relacion()
    marcas = {p.banda_check for w in gw.wells.values() for p in w.points}
    check(marcas <= {"dentro", "sobre", "bajo", "sin_banda", None},
          "las marcas son las declaradas", marcas)
    # Un punto marcado "sobre" tiene que estar EFECTIVAMENTE sobre el máximo:
    # si estuviera acotado, no existiría ninguno y la marca sería decorativa.
    sobre = [p for w in gw.wells.values() for p in w.points
             if p.banda_check == "sobre" and p.lito == "Bht"]
    if sobre and hi is not None:
        check(all(p.ucs_ml > hi for p in sobre),
              "y un punto «sobre» conserva su valor por encima del máximo de "
              "su unidad: se informa, no se corrige", (sobre[0].ucs_ml, hi))
    # Un punto SIN litología recibe predicción igual, marcada sin_banda.
    w = next(iter(gw.wells.values()))
    w.points[0].lito = None; w.points[0].dominio = None
    gw.predict_ucs_relacion()
    check(w.points[0].ucs_ml is not None,
          "un punto sin litología igual recibe UCS: es el caso de los tiros "
          "piloto, donde todavía no se conoce la litología", w.points[0].ucs_ml)
    check(w.points[0].banda_check == "sin_banda",
          "marcado como sin banda de referencia", w.points[0].banda_check)


def el_vocabulario_incompleto_advierte_pero_no_bloquea():
    section("Vocabulario — advierte y sigue, con la declaración pegada al dato")
    _escenario()
    # Una litología sin ancla: antes esto abortaba el entrenamiento entero.
    gw.domains["SinAncla"] = {"count": 500, "ucs_lab": None, "atributo_id": None,
                              "alteracion_id": None, "estructura_id": None,
                              "pi_factor": None, "calidad": 0,
                              "fuente_ucs": None, "modo_ucs": None}
    w = next(iter(gw.wells.values()))
    for p in w.points[:60]:
        p.dominio = "SinAncla"; p.lito = "SinAncla"
    comp = gw.compare_ucs_methods()
    check(comp["status"] == "ok",
          "la comparación corre igual: qué tan sucio está el dato lo decide "
          "quien calibra, no la herramienta", comp.get("motivo"))
    check(comp.get("sin_ancla"),
          "pero declara qué litologías quedaron sin ancla y cuántos puntos",
          comp.get("sin_ancla"))
    rep = gw.predict_ucs_relacion()
    check(rep.get("procedencia"),
          "y la procedencia viaja PEGADA al resultado, no en otra pantalla",
          rep.get("procedencia"))
    check(str(comp.get("n_anclas")) in gw.ucs_model_summary()
          or "ancla" in gw.ucs_model_summary().lower(),
          "el resumen dice con cuántas anclas se calibró",
          gw.ucs_model_summary())


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_vara_deja_una_litologia_fuera,
    los_tres_competidores_corren,
    el_ml_no_usa_se,
    la_relacion_da_un_valor_por_punto,
    cada_punto_declara_su_modelo,
    la_marca_de_banda_informa_no_corrige,
    el_vocabulario_incompleto_advierte_pero_no_bloquea,
]


def test_competidores_ucs():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
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
    print("✓ COMPETIDORES UCS — todas las verificaciones pasaron.")
    print("=" * 72)
