"""
test_radio_rqd.py — El radio de asignación del RQD se elige mirando la tabla.

LO PEDIDO, en palabras del autor: «sería ideal que esta tabla pudiese
reportarse en algún lado del programa al usuario para que este decida el radio
(hipotético: tengo muchos sondajes y son cerca, es mejor achicar el radio y
obtener más calidad, por eso debe poder verse la tabla y dejar ajustable el
radio) sí o sí previo a determinar los pesos de las variables MWD al determinar
DI».

POR QUÉ IMPORTA. El radio decide con qué RQD se calibran los pesos del DI, y no
hay un valor correcto universal: depende de la densidad de sondajes de la
faena. Sobre los datos de MPC la tabla medida es

    2 m →  3 pares (2 sondajes)      7,5 m → 53 pares (4 sondajes)
    3 m → 13 pares (3 sondajes)       10 m → 67 pares (4 sondajes)
    5 m → 34 pares (4 sondajes)       15 m → 84 pares (4 sondajes)

y trae un hallazgo que no se ve sin la tabla: el RQD de estos sondajes está
logueado en tramos de 3,00 m exactos, así que bajar de ~3 m no compra
resolución —la variación más fina que 3 m no está en el dato— y solo destruye
la muestra. Con otra faena, otro logueo, otra respuesta.

EL CANDADO. calibrate_di_weights() se niega mientras el radio no haya sido
elegido a la vista de la tabla. Calibrar con un radio que nadie miró es
exactamente el default silencioso que el proyecto prohíbe, y acá el default
decide el resultado entero: a 5 m manda el dámper, a 25 m manda el barrido.
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
    gw.drillholes.clear()
    gw.olvidar_radio_rqd()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
PASO = 0.02


def _pozo(wn, este, n=1400, seed=0):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * PASO, vel=float(0.9 + rng.normal(0, .01)),
                        pp=float(200 + rng.normal(0, 1)), pa=float(60 + rng.normal(0, .5)),
                        pd=float(75 + rng.normal(0, .5)), pr=float(45 + rng.normal(0, .4)),
                        pf=float(8 + rng.normal(0, .08)), se=340.0, t=0.0)
        p.este = este; p.norte = N0; p.cota = Z0 - i * PASO
        p.entrenable = True; p.dominio = p.lito = "Bht"
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w


def _sondaje(hid, este):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=N0, z_utm=Z0, length=28.0)
    dh.trace = [(d, este, N0, Z0 - d) for d in np.arange(0.0, 28.5, 1.0)]
    dh.geomec = [{"from": float(a), "to": float(a + 3), "rqd": 90.0 - a, "rmr": None}
                 for a in range(0, 27, 3)]
    gw.drillholes[hid] = dh


def _escenario():
    """Sondajes a distancias crecientes: 1, 4, 8 y 20 m del pozo más cercano."""
    reset()
    for k, dx in enumerate((0.0, 30.0, 60.0)):
        _pozo(f"W{k}", E0 + dx, seed=k)
    _sondaje("DH_cerca", E0 + 1.0)
    _sondaje("DH_media", E0 + 30.0 + 4.0)
    _sondaje("DH_lejos", E0 + 60.0 + 8.0)
    _sondaje("DH_muy_lejos", E0 + 200.0)
    gw.compute_di()


# ─────────────────────────────────────────────────────────────────────────────
def la_tabla_existe_y_es_monotona():
    section("Radio — la tabla de sensibilidad se puede pedir")
    _escenario()
    t = gw.rqd_radius_sensitivity()
    check(t["status"] == "ok", "la tabla se calcula", t.get("motivo"))
    if t["status"] != "ok":
        return
    filas = t["filas"]
    check(len(filas) >= 4, "con varios radios", len(filas))
    for f in filas:
        for k in ("radio_m", "n_pares", "n_sondajes", "pct_tramos"):
            check(k in f, f"cada fila declara {k}", sorted(f))
        break
    pares = [f["n_pares"] for f in filas]
    check(pares == sorted(pares),
          "los pares no bajan al ampliar el radio: ampliar solo puede sumar",
          pares)
    check(t.get("n_tramos_totales"),
          "declara cuántos tramos con RQD hay en total, que es el techo",
          t.get("n_tramos_totales"))
    check(t.get("largo_tramo_mediano"),
          "y el largo del tramo de logueo: es lo que fija hasta dónde vale "
          "apretar el radio", t.get("largo_tramo_mediano"))


def la_tabla_dice_cuanto_se_pierde():
    section("Radio — la tabla muestra el costo de apretar, no solo el beneficio")
    _escenario()
    t = gw.rqd_radius_sensitivity(radios=(1.0, 5.0, 50.0))
    f = {x["radio_m"]: x for x in t["filas"]}
    check(f[1.0]["n_pares"] <= f[5.0]["n_pares"] <= f[50.0]["n_pares"],
          "apretar el radio pierde pares", [f[r]["n_pares"] for r in (1.0, 5.0, 50.0)])
    check(f[50.0]["n_sondajes"] >= f[1.0]["n_sondajes"],
          "y ampliarlo alcanza más sondajes",
          (f[1.0]["n_sondajes"], f[50.0]["n_sondajes"]))
    check(all(0 <= x["pct_tramos"] <= 100 for x in t["filas"]),
          "el porcentaje de tramos alcanzados es un porcentaje",
          [x["pct_tramos"] for x in t["filas"]])
    check(t.get("recomendacion"),
          "y la tabla trae una recomendación razonada, que el usuario puede "
          "ignorar", t.get("recomendacion"))


def el_radio_se_elige_y_manda():
    section("Radio — elegirlo mueve el parámetro del perfil")
    _escenario()
    gw.confirmar_radio_rqd(7.0)
    check(gw.get_param("rqd.radio_max_m") == 7.0,
          "el radio elegido queda en el perfil de faena",
          gw.get_param("rqd.radio_max_m"))
    check(gw.RQD_RADIO_MAX_M == 7.0, "y en el módulo", gw.RQD_RADIO_MAX_M)
    check(gw.radio_rqd_confirmado() == 7.0,
          "y queda constancia de que fue una elección", gw.radio_rqd_confirmado())
    # Un radio absurdo se rechaza con su motivo, sin dejar a medias el estado.
    try:
        gw.confirmar_radio_rqd(-3.0)
        check(False, "un radio negativo tenía que fallar")
    except ValueError:
        check(True, "un radio imposible se rechaza")
    check(gw.get_param("rqd.radio_max_m") == 7.0, "sin mover el vigente")


def sin_elegir_radio_no_se_calibran_los_pesos():
    section("Radio — no se calibran pesos con un radio que nadie miró")
    _escenario()
    r = gw.calibrate_di_weights(registrar=False)
    check(r["status"] != "ok",
          "calibrar sin elegir el radio se rechaza: el radio decide el "
          "resultado —a 5 m manda el dámper, a 25 m el barrido— y elegirlo por "
          "omisión es dejar que el default decida la tesis", r.get("status"))
    check("radio" in (r.get("motivo") or "").lower(),
          "el motivo dice que falta elegir el radio", r.get("motivo"))
    check(r.get("tabla"),
          "y trae la tabla en el mismo rechazo, para poder elegir ahí mismo",
          bool(r.get("tabla")))
    gw.confirmar_radio_rqd(10.0)
    r2 = gw.calibrate_di_weights(registrar=False)
    check(r2["status"] != "sin_radio",
          "elegido el radio, la calibración procede", r2.get("status"))
    check(r2.get("radio_m") == 10.0 or r2.get("status") in ("sin_datos", "ok"),
          "con el radio elegido", r2.get("radio_m"))


def el_panel_muestra_la_tabla():
    section("Radio — la tabla se ve en el programa, no solo desde código")
    _escenario()
    cuerpo = gw._rqd_radio_panel_body()
    txt = []
    def rec(x):
        if isinstance(x, str): txt.append(x); return
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        for a in ("children", "title"):
            v = getattr(x, a, None)
            if v is not None: rec(v)
    rec(cuerpo)
    t = " | ".join(txt)
    check("radio" in t.lower(), "el panel habla del radio", t[:160])
    for palabra in ("pares", "sondaje"):
        check(palabra in t.lower(), f"y muestra {palabra}", t[:200])
    ids = []
    def rid(x):
        if isinstance(x, (list, tuple)):
            for y in x: rid(y)
            return
        i = getattr(x, "id", None)
        if i is not None: ids.append(i)
        for a in ("children", "title"):
            v = getattr(x, a, None)
            if v is not None: rid(v)
    rid(cuerpo)
    check("rqd-radio-input" in ids, "con el radio ajustable", ids)
    check("btn-rqd-radio" in ids, "y el botón para fijarlo", ids)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_tabla_existe_y_es_monotona,
    la_tabla_dice_cuanto_se_pierde,
    el_radio_se_elige_y_manda,
    sin_elegir_radio_no_se_calibran_los_pesos,
    el_panel_muestra_la_tabla,
]


def test_radio_rqd():
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
    print("✓ RADIO RQD — todas las verificaciones pasaron.")
    print("=" * 72)
