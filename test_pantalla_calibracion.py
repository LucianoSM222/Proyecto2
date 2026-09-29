"""
test_pantalla_calibracion.py — La búsqueda de pesos, alcanzable desde el programa.

LO PEDIDO, en palabras del autor: «No hay ningún apartado para que haga el
análisis de cercanía RQD y ajuste los pesos del DI con movvar ni nada, no está
la variable de flujo para DI».

Dos cosas distintas, y las dos son ciertas:

  1. `calibrate_di_weights()` existía desde S8d y NO había forma de llamarla
     desde la interfaz. Buscar los pesos por varianza móvil es el método de
     Fernández —el mismo que produjo los pesos de convención— y quedaba fuera
     del alcance de quien usa la plataforma.

  2. LAS SIGLAS ESTABAN CRUZADAS. En IREDES el cuarto campo de `Val` es «FP» =
     Feed Pressure, la de AVANCE, que el código guarda en `pa`; el séptimo es
     «FLP» = Flushing, el BARRIDO, que el código guarda en `pf`. El panel del
     DI rotulaba la entrada de `pf` como "FP": la sigla de la variable de al
     lado. El número nunca cambió —los pesos siguen siendo los mismos— pero
     quien leía la pantalla creía estar ajustando el avance cuando ajustaba el
     barrido, y el avance no aparecía por ninguna parte.

Este test fija las dos cosas: que la pantalla existe y que cada presión se
llama por su nombre, sin siglas ambiguas.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()
    gw.olvidar_radio_rqd()


def _ids(x, out=None):
    out = [] if out is None else out
    if isinstance(x, (list, tuple)):
        for y in x:
            _ids(y, out)
        return out
    i = getattr(x, "id", None)
    if i is not None:
        out.append(i)
    for a in ("children", "title", "label"):
        v = getattr(x, a, None)
        if v is not None:
            _ids(v, out)
    return out


def _textos(x, out=None):
    out = [] if out is None else out
    if isinstance(x, str):
        out.append(x); return out
    if isinstance(x, (list, tuple)):
        for y in x:
            _textos(y, out)
        return out
    for a in ("children", "label", "title"):
        v = getattr(x, a, None)
        if v is not None:
            _textos(v, out)
    for o in (getattr(x, "options", None) or []):
        if isinstance(o, dict):
            _textos(o.get("label"), out)
    return out


def _sondaje(nombre, e, n, z, rqds):
    """Un sondaje vertical con tramos de RQD de 3 m."""
    largo = 3.0 * len(rqds)
    dh = gw.DrillHole(holeid=nombre, x_utm=e, y_utm=n, z_utm=z, length=largo)
    dh.trace = [(0.0, e, n, z), (largo, e, n, z - largo)]
    dh.geomec = [{"from": i * 3.0, "to": (i + 1) * 3.0, "rqd": v, "rmr": None}
                 for i, v in enumerate(rqds)]
    gw.drillholes[nombre] = dh
    return dh


# ─────────────────────────────────────────────────────────────────────────────
def la_pantalla_existe_y_se_alcanza():
    section("Calibración — hay una pantalla, no solo una función")
    reset()
    card = gw._di_calibracion_card()
    check(card is not None, "sin sondajes la tarjeta se arma igual")
    txt = " ".join(_textos(card))
    check("sondaje" in txt.lower(),
          "y dice que sin testigo no hay contra qué calibrar", txt[:120])

    _sondaje("S1", 376700.0, 6959000.0, 300.0, [80, 45, 90, 30])
    card = gw._di_calibracion_card()
    ids = _ids(card)
    for i in ("cal-params", "cal-muestras", "cal-semilla", "btn-calibrar-di",
              "cal-output"):
        check(i in ids, f"con sondajes la tarjeta tiene {i}", ids)


def estan_las_cinco_presiones_con_su_nombre():
    section("Calibración — las cinco candidatas, cada una por su nombre")
    reset()
    _sondaje("S1", 376700.0, 6959000.0, 300.0, [80, 45, 90, 30])
    check(set(gw.CAL_PARAMS) == {"pp", "pr", "pd", "pf", "pa"},
          "las cinco presiones son candidatas, incluido el avance",
          gw.CAL_PARAMS)
    check(set(gw.CAL_ETIQUETAS) == set(gw.CAL_PARAMS),
          "y todas tienen etiqueta", sorted(gw.CAL_ETIQUETAS))
    txt = " ".join(_textos(gw._di_calibracion_card())).lower()
    for palabra in ("percusión", "dámper", "rotación", "barrido", "avance"):
        check(palabra in txt, f"la pantalla ofrece «{palabra}»")

    # El punto 2 del pedido: la sigla no puede estar sobre la variable de al lado.
    check("flp" in gw.CAL_ETIQUETAS["pf"].lower(),
          "el BARRIDO se rotula FLP, que es su sigla en IREDES",
          gw.CAL_ETIQUETAS["pf"])
    check("barrido" in gw.CAL_ETIQUETAS["pf"].lower(),
          "y se nombra barrido, no «FP»", gw.CAL_ETIQUETAS["pf"])
    check("avance" in gw.CAL_ETIQUETAS["pa"].lower(),
          "el AVANCE es el que lleva FP/AP", gw.CAL_ETIQUETAS["pa"])
    # Contra el orden inmutable de Val, que es la fuente de verdad.
    check(gw.MWD_VAL_ORDER == ("LT", "ROP", "PP", "FP", "DP", "RP", "FLP"),
          "el orden de Val sigue siendo el de la convención", gw.MWD_VAL_ORDER)


def el_panel_del_di_ya_no_llama_FP_al_barrido():
    section("Calibración — el panel del DI deja de cruzar las siglas")
    reset()
    txt = " ".join(_textos(gw._step3()))
    check("Barrido (FLP)" in txt,
          "la entrada que escribe `pf` se rotula Barrido (FLP)", txt[:200])
    check("Percusión (PP)" in txt and "Dámper (DP)" in txt
          and "Rotación (RP)" in txt,
          "y las otras tres también se nombran completas")
    check("avance" in txt.lower(),
          "y se declara que el avance no está entre esos cuatro pesos, "
          "en vez de simplemente faltar sin explicación")
    # Lo que NO puede cambiar: los pesos de convención.
    check(gw.DI_DEFAULTS["weights"] == {"pp": 0.35, "pr": 0.20, "pd": 0.25,
                                        "pf": 0.20},
          "los pesos de convención siguen exactamente iguales: se corrigió el "
          "rótulo, no el número", gw.DI_DEFAULTS["weights"])


def sin_radio_elegido_no_calibra_y_dice_por_que():
    section("Calibración — el radio no se elige por omisión")
    reset()
    _sondaje("S1", 376700.0, 6959000.0, 300.0, [80, 45, 90, 30])
    gw.olvidar_radio_rqd()
    rep = gw.calibrate_di_weights()
    check(rep["status"] == "sin_radio",
          "sin radio confirmado la calibración se niega a correr", rep["status"])
    check(rep.get("motivo"), "con el motivo", (rep.get("motivo") or "")[:80])
    check(rep.get("tabla") is not None,
          "y trae la tabla para poder elegirlo ahí mismo, no solo el reproche")
    vista = gw._render_calibracion(rep)
    check(vista is not None, "la pantalla sabe mostrar ese rechazo")
    txt = " ".join(_textos(gw._di_calibracion_card())).lower()
    check("radio" in txt, "y la tarjeta avisa que falta elegir el radio")


def el_resultado_se_lee_con_el_veredicto_por_delante():
    section("Calibración — se lee el veredicto, no una tabla de números")
    rep = {
        "status": "ok",
        "pesos": {"pp": 0.1, "pd": 0.65, "pr": 0.1, "pf": 0.1, "pa": 0.05},
        "pesos_convencion": {"pp": 0.35, "pd": 0.25, "pr": 0.20, "pf": 0.20},
        "rho_ajuste": 0.83, "rho_convencion": 0.12, "rho_validacion": -0.21,
        "veredicto": "NO GENERALIZA: hacen falta más sondajes con RQD.",
        "n_pares": 14, "n_intervalos": 20, "n_sondajes": 4,
        "sondajes": ["S1", "S2", "S3", "S4"], "radio_m": 5.0,
        "params_candidatos": ["pp", "pd", "pr", "pf", "pa"],
        "variante": "calibrada_RQD",
        "encuadre": "La variante de convención queda intacta.",
    }
    vista = gw._render_calibracion(rep)
    txt = " ".join(_textos(vista))
    check("NO GENERALIZA" in txt, "el veredicto aparece", txt[:90])
    check("0.650" in txt or "0.65" in txt, "los pesos calibrados aparecen")
    check("0.25" in txt,
          "y AL LADO los de convención: un peso calibrado sin su referencia no "
          "se puede juzgar")
    check("validación" in txt.lower(),
          "se declara el rho de VALIDACIÓN, que es el que manda, no solo el "
          "de ajuste")
    check("calibrada_RQD" in txt, "y con qué nombre quedó registrada la variante")
    check("convención queda intacta" in txt,
          "diciendo que la de convención no se tocó")


def calibrar_no_pisa_la_convencion():
    section("Calibración — calibrar registra una variante, no reescribe Fernández")
    reset()
    antes_pesos = dict(gw.di_config["weights"])
    antes_activa = gw.di_activo()
    _sondaje("S1", 376700.0, 6959000.0, 300.0, [80, 45, 90, 30])
    gw.confirmar_radio_rqd(5.0)
    rep = gw.calibrate_di_weights()
    check(rep["status"] != "sin_radio",
          "con el radio fijado ya no se niega por el radio", rep["status"])
    check(gw.di_config["weights"] == antes_pesos,
          "los pesos que corren no cambiaron por haber calibrado",
          gw.di_config["weights"])
    check(gw.di_activo() == antes_activa,
          "y la variante activa tampoco: activarla es una decisión aparte, "
          "que se toma mirando el veredicto", gw.di_activo())
    check(gw.di_variantes[gw.DI_VARIANTE_CONVENCION]["weights"]
          == gw.DI_DEFAULTS["weights"],
          "la variante de convención sigue con los pesos de Fernández")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_pantalla_existe_y_se_alcanza,
    estan_las_cinco_presiones_con_su_nombre,
    el_panel_del_di_ya_no_llama_FP_al_barrido,
    sin_radio_elegido_no_calibra_y_dice_por_que,
    el_resultado_se_lee_con_el_veredicto_por_delante,
    calibrar_no_pisa_la_convencion,
]


def test_pantalla_calibracion():
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
    print("✓ PANTALLA DE CALIBRACIÓN — todas las verificaciones pasaron.")
    print("=" * 72)
