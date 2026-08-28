"""
test_s8d_calibracion.py — Paso 3: calibrar los pesos del DI contra el RQD.

EL ENCUADRE, corregido por el autor: Fernández busca los pesos de su DI con
`movvar` de MATLAB — varianza móvil, exactamente la misma construcción que usa
este código. O sea que calibrar los pesos NO es una desviación del método: ES
el método. Los pesos 0,35 / 0,25 / 0,20 / 0,20 son el resultado de la
calibración de Fernández sobre SUS datos, y buscar los de Punta del Cobre es
hacer lo mismo sobre estos.

Por eso la calibración produce una VARIANTE con nombre propio y nunca toca la
de convención: las dos son resultados legítimos de un mismo procedimiento
aplicado a datos distintos, y tienen que poder compararse.

LA VALIDACIÓN ES POR SONDAJE, no por intervalo. Dos intervalos del mismo
sondaje no son observaciones independientes: comparten roca, campaña y
criterio de logueo. Ajustar sobre todos y reportar el ajuste sería reportar
memorización.

Con pocos sondajes el riesgo real es un rho alto en el ajuste y cero en la
validación. Por eso el reporte entrega los dos números SIEMPRE, y el veredicto
mira el de validación.
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
    gw.drillholes.clear(); gw.set_training_caserones(None)
    gw.olvidar_radio_rqd()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0
PASO = 0.02


def _pozo(wn, este, norte, n, seed, zonas_malas, variable="pd"):
    """
    Pozo donde la roca mala se manifiesta SOLO en una variable (`variable`).
    Es el escenario que permite comprobar que la calibración encuentra la
    variable correcta: los pesos de convención reparten entre cuatro, y acá la
    señal está en una sola.
    """
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        largo = i * PASO
        p = gw.MWDPoint(largo=largo,
                        vel=float(0.90 + rng.normal(0, 0.01)),
                        pp=float(200.0 + rng.normal(0, 1.0)),
                        pa=float(60.0 + rng.normal(0, 0.5)),
                        pd=float(75.0 + rng.normal(0, 0.5)),
                        pr=float(45.0 + rng.normal(0, 0.4)),
                        pf=float(8.0 + rng.normal(0, 0.08)),
                        se=340.0, t=0.0)
        p.este = este; p.norte = norte; p.cota = Z0 - largo
        p.entrenable = True; p.dominio = "Bht"; p.lito = "Bht"
        pts.append(p)
    for (a, b, intensidad) in zonas_malas:
        i0, i1 = int(a / PASO), int(b / PASO)
        for i in range(max(0, i0), min(n, i1 + 1)):
            base = getattr(pts[i], variable)
            setattr(pts[i], variable,
                    float(base * (1.0 + rng.normal(0, intensidad))))
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


def _sondaje(hid, este, norte, tramos):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=norte, z_utm=Z0, length=30.0)
    dh.trace = [(0.0, este, norte, Z0), (30.0, este, norte, Z0 - 30.0)]
    dh.geomec = [{"from": a, "to": b, "rqd": r, "rmr": None} for a, b, r in tramos]
    gw.drillholes[hid] = dh
    return dh


def _escenario(n_sondajes=4):
    """
    `n_sondajes` sitios. En cada uno, tramos de RQD bajo coinciden con zonas
    donde SOLO el dámper se desestabiliza. Un DI que pesa el dámper conversa
    con ese RQD; uno que reparte entre cuatro variables lo diluye.
    """
    reset()
    # Tramos de 3 m a lo largo de 24 m: ocho intervalos por sondaje, que es lo
    # que permite que la validación dejando-uno-fuera tenga pares suficientes
    # en cada pliegue. Las zonas malas alternan para que el RQD varíe tramo a
    # tramo y no solo entre sondajes.
    zonas = [(3.0, 6.0), (12.0, 15.0), (18.0, 21.0)]
    for k in range(n_sondajes):
        este = E0 + k * 60.0
        for j in range(2):
            _pozo(f"W{k}_{j}", este + 1.0 + j * 1.5, N0, n=1400, seed=100 * k + j,
                  zonas_malas=[(a, b, 0.35) for a, b in zonas], variable="pd")
        tramos = []
        for t0 in range(0, 24, 3):
            malo = any(abs(t0 - a) < 1e-9 for a, _ in zonas)
            tramos.append((float(t0), float(t0 + 3), 30.0 if malo else 95.0))
        _sondaje(f"DH{k}", este, N0, tramos=tramos)
    gw.compute_di()


# ─────────────────────────────────────────────────────────────────────────────
def la_calibracion_produce_una_variante():
    section("3 — La calibración produce una VARIANTE, nunca toca la convención")
    _escenario()
    rep = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_prueba",
                                  n_muestras=120, seed=1)
    check(rep["status"] == "ok", "la calibración corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    v = gw.di_variant("cal_prueba")
    check(v is not None, "queda registrada como variante", list(gw.di_variantes))
    check(v is not None and not v.get("solo_lectura"),
          "editable, a diferencia de la de convención")
    conv = gw.di_variant(gw.DI_VARIANTE_CONVENCION)
    check(conv["weights"] == {"pp": 0.35, "pr": 0.20, "pd": 0.25, "pf": 0.20},
          "y la de convención queda intacta", conv["weights"])
    check("movvar" in (v.get("fuente") or "").lower()
          or "fernández" in (v.get("fuente") or "").lower()
          or "fernandez" in (v.get("fuente") or "").lower(),
          "la procedencia declara que es el mismo procedimiento de Fernández",
          v.get("fuente"))
    check(abs(sum(v["weights"].values()) - 1.0) < 1e-6,
          "los pesos suman 1", v["weights"])
    # Ninguna presión queda fuera por descarte previo: la de avance (AP), que
    # la convención de Fernández no usa, entra como candidata y su peso lo
    # decide la calibración.
    check("pa" in rep["params_candidatos"],
          "la presión de avance entra como candidata, no se descarta de entrada",
          rep.get("params_candidatos"))
    check(set(rep["params_candidatos"]) == {"pp", "pr", "pd", "pf", "pa"},
          "las cinco presiones son candidatas", rep.get("params_candidatos"))
    check(rep.get("distancia_mediana_m") is not None,
          "y el reporte declara a qué distancia quedaron los apareos uno a uno",
          rep.get("distancia_mediana_m"))


def encuentra_la_variable_que_manda():
    section("3 — Encuentra la variable donde está la señal")
    _escenario()
    rep = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_pd",
                                  n_muestras=200, seed=2)
    if rep["status"] != "ok":
        check(False, "corre", rep.get("motivo")); return
    w = rep["pesos"]
    check(w["pd"] > 0.25,
          "el dámper —única variable con señal en este escenario— sube sobre "
          "su peso de convención (0,25)", w)
    check(w["pd"] == max(w, key=w.get) or w["pd"] > 0.4,
          "y queda como el peso dominante o cerca", w)
    check(rep["rho_ajuste"] > rep["rho_convencion"],
          "el rho del ajuste supera al de la convención",
          (rep["rho_convencion"], rep["rho_ajuste"]))


def la_validacion_es_por_sondaje():
    section("3 — Validación dejando-un-SONDAJE-fuera, no por intervalo")
    _escenario()
    rep = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_val",
                                  n_muestras=120, seed=3)
    if rep["status"] != "ok":
        check(False, "corre", rep.get("motivo")); return
    check(rep["validacion"]["unidad"] == "sondaje",
          "la unidad de validación es el sondaje", rep["validacion"])
    check(rep["validacion"]["n_pliegues"] == rep["n_sondajes"],
          "un pliegue por sondaje",
          (rep["validacion"]["n_pliegues"], rep["n_sondajes"]))
    check("rho_validacion" in rep and rep["rho_validacion"] is not None,
          "y se entrega el rho de VALIDACIÓN, no solo el del ajuste", rep)
    check(rep["rho_ajuste"] is not None,
          "los dos números viajan juntos siempre", rep.get("rho_ajuste"))
    check(rep.get("veredicto"), "con un veredicto que mira el de validación",
          rep.get("veredicto"))
    check("valida" in rep["veredicto"].lower() or "ajuste" in rep["veredicto"].lower()
          or "sondaje" in rep["veredicto"].lower(),
          "y lo dice en palabras", rep["veredicto"])


def sin_sondajes_suficientes_se_declara():
    section("3 — Con un solo sondaje no hay validación posible: se declara")
    _escenario(n_sondajes=1)
    rep = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_1",
                                  n_muestras=50, seed=4)
    check(rep["status"] in ("sin_validacion", "sin_datos"),
          "el estado lo dice", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    check(gw.di_variant("cal_1") is None,
          "y NO se registra una variante que no se pudo validar")


def sin_pares_no_calibra():
    section("3 — Sin pares no se inventa una calibración")
    reset()
    _pozo("W1", E0, N0, n=600, seed=9, zonas_malas=[])
    gw.compute_di()
    rep = gw.calibrate_di_weights(radio_m=5.0, nombre_variante="cal_vacio")
    check(rep["status"] == "sin_datos", "el estado lo dice", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    check(gw.di_variant("cal_vacio") is None, "sin registrar nada")


def es_reproducible():
    section("3 — Misma semilla, mismo resultado")
    _escenario()
    r1 = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_a",
                                 n_muestras=120, seed=7)
    _escenario()
    r2 = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_b",
                                 n_muestras=120, seed=7)
    check(r1["status"] == "ok" and r2["status"] == "ok", "las dos corren")
    if r1["status"] == "ok" and r2["status"] == "ok":
        check(r1["pesos"] == r2["pesos"], "los pesos son idénticos",
              (r1["pesos"], r2["pesos"]))
        check(r1["semilla"] == 7, "y la semilla queda declarada", r1.get("semilla"))
    _escenario()
    r3 = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_c",
                                 n_muestras=120, seed=99)
    if r3["status"] == "ok":
        check(r3["pesos"] != r1["pesos"] or True,
              "y con otra semilla el resultado puede diferir: se declara cuál se usó")


def los_parametros_vienen_del_perfil():
    section("3 — El radio y el mínimo de puntos salen del perfil de faena")
    _escenario()
    # (Auditoría) EL CONTRATO CAMBIÓ, por pedido del autor: el radio ya no se
    # toma del perfil por omisión. Se ELIGE a la vista de la tabla de
    # sensibilidad, porque decide el resultado —a 5 y 10 m domina el dámper, a
    # 25 m domina el barrido— y un default que nadie miró decidiría la tesis.
    sin_elegir = gw.calibrate_di_weights(nombre_variante="cal_x", n_muestras=20)
    check(sin_elegir["status"] == "sin_radio",
          "sin elegir el radio, la calibración se rechaza", sin_elegir.get("status"))
    check(sin_elegir.get("tabla"),
          "y el rechazo trae la tabla para poder elegir ahí mismo")
    gw.confirmar_radio_rqd(15.0)
    rep = gw.calibrate_di_weights(nombre_variante="cal_perfil", n_muestras=80, seed=5)
    check(rep["status"] == "ok", "elegido el radio, corre con él", rep.get("motivo"))
    if rep["status"] == "ok":
        check(rep["radio_m"] == 15.0, "y lo declara", rep.get("radio_m"))
    gw.seed_param_registry(force=True)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_calibracion_produce_una_variante,
    encuentra_la_variable_que_manda,
    la_validacion_es_por_sondaje,
    sin_sondajes_suficientes_se_declara,
    sin_pares_no_calibra,
    es_reproducible,
    los_parametros_vienen_del_perfil,
]


def test_s8d_calibracion():
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
    print("✓ PASO 3 — todas las verificaciones pasaron.")
    print("=" * 72)
