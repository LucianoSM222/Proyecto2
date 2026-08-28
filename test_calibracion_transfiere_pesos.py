"""
test_calibracion_transfiere_pesos.py — La calibración se ve, se usa, y se ordena antes.

LO PEDIDO, en palabras del autor, en tres partes:

  4.1 «El calibrado de pesos con movvar debe ser antes de la configuración y
      cálculo de DI.» — Antes la calibración aparecía DESPUÉS de la tarjeta
      de sensibilidad y la de RQD, al final del Paso 3. Ahora va justo
      después de la Fórmula y antes de la Configuración: se calibra, y
      LUEGO se mira lo que quedó en las casillas.

  4.2 «Corre, entrega una tabla que después se borra, la idea es que le
      transfiera directo los valores a las casillas de la configuración y
      el cálculo.» — Antes calibrar solo registraba una variante y pintaba
      una tabla en `cal-output`; navegar a otro paso la perdía y nadie
      podía usar el resultado sin copiar los números a mano. Ahora
      `do_calibrar_di` escribe la ventana, el umbral y los cinco pesos
      directo en `di-window`/`di-thresh`/`di-w-*` — las mismas casillas que
      «Calcular DI» lee — sin activar nada por sí sola: aplicar sigue
      siendo un clic aparte, a propósito.

  4.4 «En pesos P3-3.7 ahora no aparece el avance.» — Las casillas de
      Configuración tenían cuatro entradas (PP, DP, FLP, RP); el avance solo
      vivía en la calibración, sin dónde escribirse en el cálculo real. Una
      variante calibrada que le diera peso al avance lo perdía en silencio en
      cuanto alguien volvía a pulsar «Calcular DI», porque `do_di` ni
      siquiera leía esa quinta casilla. Ahora hay una quinta entrada
      (`di-w-pa`) y `do_di` la lee, valida y aplica igual que a las otras
      cuatro.
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


def _sondaje(hid, este, tramos):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=N0, z_utm=Z0, length=30.0)
    dh.trace = [(0.0, este, N0, Z0), (30.0, este, N0, Z0 - 30.0)]
    dh.geomec = [{"from": a, "to": b, "rqd": r, "rmr": None} for a, b, r in tramos]
    gw.drillholes[hid] = dh
    return dh


def _escenario_damper(n_sondajes=4, seed=7):
    """
    Idéntico patrón que S8d: la roca mala se manifiesta SOLO en el dámper.
    Es el escenario donde la calibración conoce la respuesta correcta.
    """
    reset()
    rng = np.random.default_rng(seed)
    zonas = [(3.0, 6.0), (12.0, 15.0), (18.0, 21.0)]
    for k in range(n_sondajes):
        este = E0 + k * 60.0
        pts = []
        for i in range(1400):
            malo = any(a <= i * 0.02 < b for a, b in zonas)
            pd = float(75.0 + rng.normal(0, 0.5 * (3.0 if malo else 1.0)))
            p = gw.MWDPoint(largo=i * 0.02, vel=0.9, pp=200.0, pa=60.0, pd=pd,
                            pr=45.0, pf=8.0, se=300.0, t=0.0)
            p.este = este; p.norte = N0; p.cota = Z0 - i * 0.02
            p.entrenable = True
            pts.append(p)
        gw.wells[f"W{k}"] = gw.Well(well_name=f"W{k}", plan_id="CAS_PR01_TH_P01",
                                    hole_id=str(k), points=pts)
        tramos = []
        for t0 in range(0, 24, 3):
            malo = any(abs(t0 - a) < 1e-9 for a, _ in zonas)
            tramos.append((float(t0), float(t0 + 3), 30.0 if malo else 95.0))
        _sondaje(f"DH{k}", este, tramos)
    gw.compute_di()


def _ids(x, out=None):
    out = [] if out is None else out
    if isinstance(x, (list, tuple)):
        for y in x:
            _ids(y, out)
        return out
    i = getattr(x, "id", None)
    if i is not None:
        out.append(i)
    for a in ("children", "title"):
        v = getattr(x, a, None)
        if v is not None:
            _ids(v, out)
    return out


class _CtxClick:
    def __init__(self, prop_id="x"):
        self.triggered_id = prop_id
        self.triggered = [{"value": 1}]


# ─────────────────────────────────────────────────────────────────────────────
def calibracion_va_antes_que_configuracion():
    section("4.1 — la calibración aparece ANTES de la Configuración en el Paso 3")
    _escenario_damper()
    gw.confirmar_radio_rqd(15.0)
    cuerpo = gw._step3()
    ids = _ids(cuerpo)
    check("btn-calibrar-di" in ids, "el botón de calibrar está en el Paso 3", ids)
    check("btn-di" in ids, "y el botón de calcular DI también", ids)
    pos_cal = ids.index("btn-calibrar-di")
    pos_config = ids.index("di-window")
    check(pos_cal < pos_config,
          "el botón de calibrar aparece ANTES que el primer campo de "
          "Configuración (di-window): el orden en la pantalla es el orden "
          "en que se decide", (pos_cal, pos_config))


def calibrar_escribe_las_casillas_no_solo_la_tabla():
    section("4.2 — calibrar transfiere los números a las casillas")
    _escenario_damper()
    gw.confirmar_radio_rqd(15.0)
    gw.callback_context = _CtxClick("btn-calibrar-di")
    out = gw.do_calibrar_di(1, list(gw.CAL_PARAMS), 150, 1, 0)
    check(len(out) == 9,
          "el callback tiene salida para la tabla, el refresco y las siete "
          "casillas (ventana, umbral, 5 pesos)", len(out))
    salida, refresco, dwin, dthr, dpp, dpd, dpf, dpr, dpa = out
    check(salida is not None, "la tabla se sigue mostrando")
    for nombre, v in (("ventana", dwin), ("umbral", dthr), ("PP", dpp),
                      ("DP", dpd), ("FLP", dpf), ("RP", dpr), ("avance", dpa)):
        check(v is not gw.no_update and v is not None,
              f"la casilla de {nombre} recibe un valor de verdad, no queda "
              f"en no_update: eso es lo que antes hacía que 'la tabla se "
              f"borrara' sin que nadie pudiera usar el resultado", v)
    suma = dpp + dpd + dpf + dpr + dpa
    check(abs(suma - 1.0) < 0.01, "y los cinco pesos escritos suman 1",
          suma)
    # Nada se activó todavía: transferir a las casillas no es aplicar.
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "calibrar por sí solo NO activa la variante: sigue corriendo la "
          "convención hasta que alguien pulse Calcular DI", gw.di_activo())


def lo_transferido_se_aplica_con_calcular_di():
    section("4.2 — lo transferido se usa de verdad al pulsar Calcular DI")
    _escenario_damper()
    gw.confirmar_radio_rqd(15.0)
    gw.callback_context = _CtxClick("btn-calibrar-di")
    _, _, dwin, dthr, dpp, dpd, dpf, dpr, dpa = gw.do_calibrar_di(
        1, list(gw.CAL_PARAMS), 150, 1, 0)
    gw.callback_context = _CtxClick("btn-di")
    out = gw.do_di(1, dwin, dthr, dpp, dpd, dpf, dpr, dpa, 0)
    check(len(out) == 3, "do_di corre con los siete valores calibrados", len(out))
    ref, msg, is_open = out
    check("✅" in msg and "VARIANTE" in msg,
          "y activa la variante calibrada de verdad", msg)
    check(gw.di_activo() != gw.DI_VARIANTE_CONVENCION,
          "la variante activa ya no es la convención", gw.di_activo())
    check(abs(gw.di_config["weights"]["pd"] - dpd) < 1e-9,
          "y el peso del dámper que corre es EXACTAMENTE el que calibró la "
          "búsqueda, no uno reescrito a mano por el camino",
          (gw.di_config["weights"]["pd"], dpd))


def el_avance_participa_del_calculo_real():
    section("4.4 — el avance ya no se pierde al calcular DI")
    _escenario_damper()
    cuerpo = gw._step3()
    ids = _ids(cuerpo)
    check("di-w-pa" in ids,
          "la Configuración tiene una quinta casilla para el avance: antes "
          "solo había cuatro y no había dónde escribirlo", ids)

    # Simular que el usuario escribe un peso de avance A MANO —o que quedó
    # de una calibración anterior— y pulsa Calcular DI.
    gw.callback_context = _CtxClick("btn-di")
    out = gw.do_di(1, 14, 1.5, 0.20, 0.20, 0.10, 0.20, 0.30, 0)
    ref, msg, is_open = out
    check("✅" in msg, "el cálculo con avance≠0 corre", msg)
    check(abs(gw.di_config["weights"].get("pa", 0.0) - 0.30) < 1e-9,
          "y el peso de avance QUEDA en la configuración vigente: antes "
          "do_di ni siquiera leía esa casilla y el valor se perdía en "
          "silencio en cuanto se pulsaba Calcular", gw.di_config["weights"])
    gw.olvidar_radio_rqd()


def restaurar_defecto_tambien_limpia_el_avance():
    section("4.4 — Restaurar valores por defecto también repone el avance a 0")
    reset()
    gw.callback_context = _CtxClick("btn-di")
    gw.do_di(1, 14, 1.5, 0.20, 0.20, 0.10, 0.20, 0.30, 0)
    check(gw.di_config["weights"].get("pa", 0.0) > 0,
          "queda un avance distinto de cero antes de restaurar",
          gw.di_config["weights"])
    gw.callback_context = _CtxClick("btn-di-reset")
    out = gw.do_di_reset(1, 0)
    check(len(out) == 10,
          "do_di_reset repone refresco, las siete casillas y el toast (dos "
          "salidas)", len(out))
    ref, dwin, dthr, dpp, dpd, dpf, dpr, dpa, msg, is_open = out
    check(dpa == 0.0, "y el avance vuelve a 0: la convención de Fernández no "
          "lo usa", dpa)
    check(gw.di_config["weights"].get("pa", 0.0) == 0.0,
          "también en lo que quedó corriendo", gw.di_config["weights"])
    check(gw.di_config_is_default(),
          "y la configuración vuelve a leerse como 'valores por defecto': "
          "una quinta clave 'pa'=0.0 explícita no puede romper esa "
          "comparación", gw.di_config["weights"])


def la_variante_de_convencion_no_se_toco():
    section("Regresión — nada de esto tocó la variante de convención")
    _escenario_damper()
    gw.confirmar_radio_rqd(15.0)
    gw.callback_context = _CtxClick("btn-calibrar-di")
    gw.do_calibrar_di(1, list(gw.CAL_PARAMS), 150, 1, 0)
    conv = gw.di_variantes[gw.DI_VARIANTE_CONVENCION]
    check(conv["weights"] == {"pp": 0.35, "pr": 0.20, "pd": 0.25, "pf": 0.20},
          "los pesos de Fernández siguen intactos", conv["weights"])
    check(conv["solo_lectura"], "y la variante sigue de solo lectura")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    calibracion_va_antes_que_configuracion,
    calibrar_escribe_las_casillas_no_solo_la_tabla,
    lo_transferido_se_aplica_con_calcular_di,
    el_avance_participa_del_calculo_real,
    restaurar_defecto_tambien_limpia_el_avance,
    la_variante_de_convencion_no_se_toco,
]


def test_calibracion_transfiere_pesos():
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
    print("✓ CALIBRACIÓN TRANSFIERE PESOS — todas las verificaciones pasaron.")
    print("=" * 72)
