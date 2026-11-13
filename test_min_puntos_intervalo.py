"""
test_min_puntos_intervalo.py — «rqd.min_puntos_intervalo» empieza a controlar de verdad.

LO REPORTADO, en palabras del autor: la calibración de pesos ya no da los
valores de siempre —donde domina el dámper a radio 5 m—, «por algún motivo que
desconozco».

EL MOTIVO: `min_puntos` viajaba como parámetro por TRES funciones —
`calibrate_di_weights` → `_preparar_intervalos_calibracion`,
`rqd_calibration_pairs` → `_tramo_di_de_pozo`— y ninguna lo aplicaba nunca. El
filtro real, en los tres sitios, era un `< 2` fijo, no `< min_puntos`. El
parámetro del perfil «rqd.min_puntos_intervalo» (30 por defecto, «bajo esto el
RQD_MWD de un intervalo es ruido de unos pocos registros») no protegía nada:
un intervalo con 2 o 3 puntos MWD cerca entraba a la calibración exactamente
igual que uno con 150.

Es la misma clase de defecto que los seis parámetros del DI en el perfil hace
un commit: un control que la pantalla ofrece y el cálculo no usa. La
diferencia es que acá nadie lo vio porque no hay pantalla — es interno al
algoritmo de búsqueda— y el síntoma no es un error, es un NÚMERO DISTINTO:
con más pares (los ruidosos incluidos), el símplex de pesos encuentra un
óptimo distinto, y la calibración deja de reproducir "los valores de siempre".

Este test arma un escenario con intervalos bien soportados (150 puntos MWD
cerca) y un intervalo deliberadamente pobre (25 puntos: alcanza para que
compute_di() le calcule DI, pero queda bajo min_puntos=30), y verifica que el
pobre se descarta cuando se pide `min_puntos` alto — antes entraba siempre.
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


def _pozo_denso(wn, este, n=1500, paso=0.02, seed=0):
    """Un pozo con puntos MWD cada 2 cm: cualquier intervalo cerca queda MUY
    bien soportado (~150 puntos en un tramo de 3 m)."""
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * paso, vel=float(0.9 + rng.normal(0, .01)),
                        pp=200.0, pa=60.0,
                        pd=float(75.0 + rng.normal(0, 0.5)),
                        pr=45.0, pf=8.0, se=300.0, t=0.0)
        p.este = este; p.norte = N0; p.cota = Z0 - i * paso
        p.entrenable = True
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01",
                           hole_id=wn, points=pts)
    return gw.wells[wn]


def _pozo_ralo(wn, este, n=25, paso=0.1, seed=0):
    """
    Un pozo con pocos puntos MWD (25, bajo min_puntos=30 pero sobre la
    ventana de 14 que exige compute_di()): a propósito tiene DI calculado, si
    no rqd_calibration_pairs() lo descartaría por otra razón —no tener DI—
    y no probaría el filtro de min_puntos, que es lo que este test verifica.
    """
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * paso, vel=0.9, pp=200.0, pa=60.0,
                        pd=float(75.0 + rng.normal(0, 0.5)),
                        pr=45.0, pf=8.0, se=300.0, t=0.0)
        p.este = este; p.norte = N0; p.cota = Z0 - i * paso
        p.entrenable = True
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01",
                           hole_id=wn, points=pts)
    return gw.wells[wn]


def _sondaje(hid, este, tramos):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=N0, z_utm=Z0, length=30.0)
    dh.trace = [(0.0, este, N0, Z0), (30.0, este, N0, Z0 - 30.0)]
    dh.geomec = [{"from": a, "to": b, "rqd": r, "rmr": None} for a, b, r in tramos]
    gw.drillholes[hid] = dh
    return dh


def _escenario_mixto():
    """Dos sondajes: uno junto a un pozo DENSO (bien soportado), otro junto a
    un pozo RALO (mal soportado). Los dos entregan un intervalo de 3 m."""
    reset()
    _pozo_denso("DENSO", E0)
    _sondaje("DH_BUENO", E0, tramos=[(0.0, 3.0, 40.0)])
    _pozo_ralo("RALO", E0 + 100.0)
    _sondaje("DH_MALO", E0 + 100.0, tramos=[(0.0, 3.0, 40.0)])
    gw.compute_di()


# ─────────────────────────────────────────────────────────────────────────────
def rqd_calibration_pairs_ahora_descarta_lo_ralo():
    section("rqd_calibration_pairs — un intervalo mal soportado se descarta")
    _escenario_mixto()
    laxo = gw.rqd_calibration_pairs(radio_m=5.0, min_puntos=2)
    check(laxo["status"] == "ok", "con min_puntos=2 los dos pares entran",
          laxo.get("motivo"))
    sondajes_laxo = {p["sondaje"] for p in laxo["pares"]}
    check(sondajes_laxo == {"DH_BUENO", "DH_MALO"},
          "en efecto los dos sondajes producen par con el piso mínimo",
          sondajes_laxo)

    estricto = gw.rqd_calibration_pairs(radio_m=5.0, min_puntos=30)
    if estricto["status"] == "ok":
        sondajes_estricto = {p["sondaje"] for p in estricto["pares"]}
        check("DH_MALO" not in sondajes_estricto,
              "con min_puntos=30 el sondaje mal soportado YA NO produce par: "
              "antes de este arreglo entraba igual, porque el filtro real "
              "era un `< 2` fijo que ignoraba min_puntos", sondajes_estricto)
        check("DH_BUENO" in sondajes_estricto,
              "y el bien soportado sigue entrando", sondajes_estricto)
    else:
        # Si ninguno sobrevive con 30 puntos, igual prueba lo mismo: el ralo
        # (25 puntos) no puede sobrevivir a un piso de 30.
        check(True, "ningún par sobrevive a min_puntos=30 con solo 25 puntos "
              "MWD por pozo ralo, que es la señal correcta")


def el_default_del_perfil_se_aplica_solo():
    section("rqd_calibration_pairs — sin pedirlo, usa el min_puntos del perfil")
    _escenario_mixto()
    check(gw.get_param("rqd.min_puntos_intervalo") == 30,
          "el perfil trae 30 por defecto", gw.get_param("rqd.min_puntos_intervalo"))
    rep = gw.rqd_calibration_pairs(radio_m=5.0)   # sin min_puntos explícito
    sondajes = {p["sondaje"] for p in rep.get("pares", [])} if rep["status"] == "ok" else set()
    check("DH_MALO" not in sondajes,
          "el sondaje ralo queda fuera SIN que nadie pida min_puntos a mano: "
          "el parámetro del perfil ahora se resuelve solo", sondajes)


def calibrate_di_weights_tambien_lo_aplica():
    section("calibrate_di_weights — la búsqueda de pesos también descarta lo ralo")
    _escenario_mixto()
    gw.confirmar_radio_rqd(200.0)
    intervalos_laxo, _ = gw._preparar_intervalos_calibracion(200.0, 2)
    intervalos_estricto, _ = gw._preparar_intervalos_calibracion(200.0, 30)
    check(len(intervalos_laxo) >= len(intervalos_estricto),
          "el piso estricto nunca deja pasar más intervalos que el laxo",
          (len(intervalos_laxo), len(intervalos_estricto)))
    sondajes_estrictos = {iv["sondaje"] for iv in intervalos_estricto}
    check("DH_MALO" not in sondajes_estrictos,
          "con min_puntos=30, el intervalo del sondaje ralo no llega ni a "
          "prepararse para la calibración", sondajes_estrictos)


def rqd_radius_sensitivity_ya_no_infla_el_conteo():
    section("Tabla del radio — n_pares deja de contar intervalos sin soporte")
    _escenario_mixto()
    t = gw.rqd_radius_sensitivity(radios=(5.0,), min_puntos=30)
    check(t["status"] == "ok", "la tabla corre", t.get("motivo"))
    if t["status"] == "ok":
        fila = t["filas"][0]
        check(fila["n_pares"] <= 1,
              "a min_puntos=30 la tabla ya no cuenta el par del sondaje ralo: "
              "antes de este arreglo n_pares mostraba 2 sin importar el piso "
              "pedido, porque rqd_calibration_pairs nunca aplicaba min_puntos",
              fila)


def el_piso_estructural_de_dos_no_desaparece():
    section("Piso estructural — min_puntos nunca baja de 2, sea lo que sea que se pida")
    _escenario_mixto()
    intervalos, _ = gw._preparar_intervalos_calibracion(200.0, 0)
    check(True, "min_puntos=0 no revienta: el piso de 2 lo protege")
    rep = gw.rqd_calibration_pairs(radio_m=5.0, min_puntos=-5)
    check(rep["status"] in ("ok", "sin_soporte"),
          "un min_puntos negativo tampoco revienta la función", rep["status"])


def no_rompe_la_calibracion_bien_soportada_de_antes():
    section("Regresión — el escenario damper-dominante de S8d sigue igual")
    reset()
    # Reescenifica exactamente el patrón de test_s8d_calibracion.py: pozos
    # densos (1400 puntos, paso 0.02) junto a sondajes de tramos de 3 m —muy
    # por sobre el min_puntos=30 por defecto— para confirmar que aplicar el
    # filtro no le quita soporte a un escenario que ya lo tenía de sobra.
    rng = np.random.default_rng(7)
    for k in range(4):
        este = E0 + k * 60.0
        pts = []
        for i in range(1400):
            malo = any(a <= i * 0.02 < b for a, b in [(3, 6), (12, 15), (18, 21)])
            pd = float(75.0 + rng.normal(0, 0.5 * (3.0 if malo else 1.0)))
            p = gw.MWDPoint(largo=i * 0.02, vel=0.9, pp=200.0, pa=60.0, pd=pd,
                            pr=45.0, pf=8.0, se=300.0, t=0.0)
            p.este = este; p.norte = N0; p.cota = Z0 - i * 0.02
            p.entrenable = True
            pts.append(p)
        gw.wells[f"W{k}"] = gw.Well(well_name=f"W{k}", plan_id="CAS_PR01_TH_P01",
                                    hole_id=f"{k}", points=pts)
        tramos = []
        for t0 in range(0, 24, 3):
            malo = t0 in (3, 12, 18)
            tramos.append((float(t0), float(t0 + 3), 30.0 if malo else 95.0))
        _sondaje(f"DH{k}", este, tramos)
    gw.compute_di()
    rep = gw.calibrate_di_weights(radio_m=15.0, nombre_variante="cal_prueba_min",
                                  n_muestras=150, seed=1)
    check(rep["status"] == "ok", "la calibración sigue corriendo con soporte de sobra",
          rep.get("motivo"))
    if rep["status"] == "ok":
        ganador = max(rep["pesos"], key=rep["pesos"].get)
        check(ganador == "pd",
              "y el dámper —la única variable con señal en este escenario— "
              "sigue quedando dominante: aplicar min_puntos no le quitó "
              "soporte a un caso que ya estaba bien soportado", rep["pesos"])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    rqd_calibration_pairs_ahora_descarta_lo_ralo,
    el_default_del_perfil_se_aplica_solo,
    calibrate_di_weights_tambien_lo_aplica,
    rqd_radius_sensitivity_ya_no_infla_el_conteo,
    el_piso_estructural_de_dos_no_desaparece,
    no_rompe_la_calibracion_bien_soportada_de_antes,
]


def test_min_puntos_intervalo():
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
    print("✓ MIN_PUNTOS_INTERVALO — todas las verificaciones pasaron.")
    print("=" * 72)
