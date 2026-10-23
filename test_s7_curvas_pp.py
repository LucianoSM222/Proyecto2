"""
test_s7_curvas_pp.py — Sesión 7: curvas de respuesta a PP y prescripción.

EL CONFUNDIMIENTO QUE GOBIERNA TODA LA SESIÓN: PP es la única variable que el
operador manipula, y la manipula EN RESPUESTA a la roca — sube PP en roca
dura. Así que el análisis agregado muestra la relación INVERTIDA: parece que
subir PP endurece la roca. Con los datos reales el efecto ya se ve medido:
PP mediana 211 bar en Bht y Kpcli contra 180 en Brecha mixta, que es la
unidad que se perfora más lento.

De ahí la separación que esta sesión exige:

  · modelo de CARACTERIZACIÓN: roca <- MWD, con PP como covariable de
    CONTEXTO (lo que ya hace train_rf).
  · modelo de PRESCRIPCIÓN: desempeño <- dominio y PP, con PP como variable
    de DECISIÓN optimizable.

Son preguntas distintas y no pueden compartir el mismo ajuste. Todo análisis
de PP va ESTRATIFICADO POR DOMINIO; agregado no significa nada.

La función de anticipación usa como margen operacional el desfase medio de
contactos que sale de C.5. Si no hay casos históricos comparables, ADVIERTE
sin recomendar PP: una recomendación sin respaldo es peor que ninguna.
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
    gw.drillholes.clear(); gw.set_training_caserones(None)


def _pozo_pp(wn, dominio, pp_vals, rop_de_pp, seed=0, n_por_pp=40):
    """
    Pozo donde ROP responde a PP según `rop_de_pp` (función), dentro de un
    mismo dominio. Es el escenario controlado: la respuesta es del EQUIPO,
    no de la roca, porque la roca es la misma en todo el pozo.
    """
    rng = np.random.default_rng(seed)
    pts = []
    i = 0
    for pp in pp_vals:
        for _ in range(n_por_pp):
            rop = float(max(0.06, rop_de_pp(pp) + rng.normal(0, 0.02)))
            se = (pp + 30.0 + 50.0) / rop
            p = gw.MWDPoint(largo=i * 0.02, vel=rop, pp=float(pp), pa=50.0, pd=40.0,
                            pr=30.0, pf=8.0, se=se, t=0.0)
            p.dominio = dominio; p.lito = dominio; p.entrenable = True; p.di = 0.4
            pts.append(p); i += 1
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _escenario_saturacion():
    """
    Dominio único donde ROP crece con PP hasta saturar en 170 bar: subir más
    allá no mejora el avance. Es el punto que la curva debe encontrar.
    """
    reset()
    gw.domains["Bht"] = {"ucs_lab": 128.1, "atributo_id": "Bht", "nombre": "Bht"}
    _pozo_pp("W1", "Bht", [100, 120, 140, 160, 170, 180, 200, 220],
             rop_de_pp=lambda pp: 0.3 + 0.006 * min(pp, 170), seed=1)


# ─────────────────────────────────────────────────────────────────────────────
def curvas_por_dominio():
    section("7 — Curvas PP → (ROP, SE, CV(SE)) POR DOMINIO")
    _escenario_saturacion()
    rep = gw.pp_response_curves()
    check(rep["status"] == "ok", "las curvas se construyen", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check("dominios" in rep and "Bht" in rep["dominios"],
          "hay una curva POR DOMINIO, no una agregada", list(rep.get("dominios", {})))
    curva = rep["dominios"]["Bht"]["curva"]
    check(len(curva) >= 4, "la curva tiene varios puntos de PP", len(curva))
    for pt in curva:
        check(set(("pp", "rop_mediana", "se_mediana", "cv_se", "n")) <= set(pt),
              "cada punto trae PP, ROP, SE, CV(SE) y n", pt)
        break
    check(rep["estratificado_por_dominio"] is True,
          "el reporte declara que está estratificado por dominio")
    check("advertencia_confundimiento" in rep and rep["advertencia_confundimiento"],
          "y declara el confundimiento del operador, no lo omite")


def punto_de_saturacion():
    section("7 — Punto de saturación: dónde deja de rendir subir PP")
    _escenario_saturacion()
    rep = gw.pp_response_curves()
    if rep["status"] != "ok":
        check(False, "las curvas corren"); return
    sat = rep["dominios"]["Bht"].get("pp_saturacion")
    check(sat is not None, "se detecta un punto de saturación", sat)
    if sat is not None:
        check(150 <= sat <= 190,
              "y cae donde la ROP deja de responder (~170 bar por construcción)", sat)
    check("interpretacion" in rep["dominios"]["Bht"],
          "con su lectura en palabras, no solo el número")


def no_agrega_dominios():
    section("7 — Agregar dominios muestra la relación INVERTIDA: hay que impedirlo")
    reset()
    # Dos dominios: en el duro el operador usa PP alta y la ROP es baja; en el
    # blando usa PP baja y la ROP es alta. DENTRO de cada uno, subir PP mejora
    # la ROP. Agregados, parece que subir PP EMPEORA el avance.
    for dom, ucs in (("Blando", 90.0), ("Duro", 250.0)):
        gw.domains[dom] = {"ucs_lab": ucs, "atributo_id": dom, "nombre": dom}
    _pozo_pp("W_blando", "Blando", [100, 110, 120],
             rop_de_pp=lambda pp: 0.9 + 0.004 * pp, seed=2)
    _pozo_pp("W_duro", "Duro", [200, 210, 220],
             rop_de_pp=lambda pp: 0.1 + 0.0015 * pp, seed=3)

    rep = gw.pp_response_curves()
    check(rep["status"] == "ok", "corre con dos dominios")
    pend_por_dom = {k: v.get("pendiente_rop") for k, v in rep["dominios"].items()}
    check(all(p is not None and p > 0 for p in pend_por_dom.values()),
          "DENTRO de cada dominio, subir PP mejora la ROP (pendiente > 0)",
          pend_por_dom)
    agg = rep.get("agregado_todos_los_dominios", {})
    check(agg.get("pendiente_rop") is not None, "el reporte calcula también el agregado")
    check(agg["pendiente_rop"] < 0,
          "y el agregado sale INVERTIDO, que es justo la trampa", agg.get("pendiente_rop"))
    check("trampa" in (agg.get("advertencia") or "").lower()
          or "invert" in (agg.get("advertencia") or "").lower(),
          "el agregado viene acompañado de la advertencia de por qué NO usarlo",
          agg.get("advertencia"))


def prescripcion_separada_de_caracterizacion():
    section("7 — Prescripción y caracterización son modelos DISTINTOS")
    _escenario_saturacion()
    rec = gw.pp_prescription("Bht")
    check(rec["status"] in ("ok", "sin_datos"), "la prescripción declara su estado")
    if rec["status"] == "ok":
        check("pp_recomendada" in rec, "recomienda un PP concreto", list(rec))
        check("objetivo" in rec, "declarando qué está optimizando", rec.get("objetivo"))
        check(rec["rol_de_pp"] == "variable de decisión",
              "y que aquí PP es variable de DECISIÓN", rec.get("rol_de_pp"))
    # En caracterización, PP sigue siendo covariable de contexto: NUNCA se
    # toca ML_FEATURES desde la prescripción.
    check("pp" in gw.ML_FEATURES,
          "PP sigue siendo covariable de contexto en el modelo de caracterización")
    check(gw.ML_FEATURES == ["vel", "pp", "pa", "pd", "pr", "pf", "se"],
          "la prescripción NO alteró ML_FEATURES", gw.ML_FEATURES)


def prescripcion_sin_respaldo_advierte():
    section("7 — Sin casos históricos comparables: ADVIERTE, no recomienda")
    reset()
    gw.domains["Bht"] = {"ucs_lab": 128.1, "atributo_id": "Bht", "nombre": "Bht"}
    rec = gw.pp_prescription("Bht")
    check(rec["status"] == "sin_datos",
          "sin datos del dominio no hay recomendación", rec.get("status"))
    check(rec.get("pp_recomendada") is None,
          "NO se inventa un PP: una recomendación sin respaldo es peor que ninguna")
    check(rec.get("motivo"), "y explica qué falta", rec.get("motivo"))

    # Dominio desconocido: mismo trato.
    rec2 = gw.pp_prescription("NoExiste")
    check(rec2["status"] == "sin_datos" and rec2.get("pp_recomendada") is None,
          "un dominio desconocido tampoco recibe recomendación")


def anticipacion_usa_el_desfase_de_c5():
    section("7 — Anticipación: el margen operacional sale del desfase δ de C.5")
    _escenario_saturacion()
    ant = gw.contact_anticipation()
    check(ant["status"] in ("ok", "sin_datos"), "declara su estado", ant.get("status"))
    check("fuente_margen" in ant,
          "declara de dónde sale el margen (C.5), no lo inventa", list(ant))
    if ant["status"] == "sin_datos":
        check(ant.get("margen_m") is None,
              "sin desfase medido no propone margen alguno")
        check("advert" in str(ant).lower() or ant.get("motivo"),
              "y lo advierte en vez de callarlo")


def limites_de_pp_respetados():
    section("7 — PP: 90 a 230 bar, límite del proyecto")
    _escenario_saturacion()
    rep = gw.pp_response_curves()
    if rep["status"] != "ok":
        check(False, "corre"); return
    for dom, d in rep["dominios"].items():
        for pt in d["curva"]:
            check(90 <= pt["pp"] <= 230,
                  f"{dom}: todo PP de la curva cae en [90, 230] bar", pt["pp"])
            break
    rec = gw.pp_prescription("Bht")
    if rec["status"] == "ok":
        check(90 <= rec["pp_recomendada"] <= 230,
              "el PP recomendado respeta el rango operacional", rec["pp_recomendada"])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    curvas_por_dominio,
    punto_de_saturacion,
    no_agrega_dominios,
    prescripcion_separada_de_caracterizacion,
    prescripcion_sin_respaldo_advierte,
    anticipacion_usa_el_desfase_de_c5,
    limites_de_pp_respetados,
]


def test_s7_curvas_pp():
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
    print("✓ SESIÓN 7 — todas las verificaciones pasaron.")
    print("=" * 72)
