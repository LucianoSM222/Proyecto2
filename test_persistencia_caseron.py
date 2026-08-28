"""
test_persistencia_caseron.py — Guardar y recargar un proyecto ya no borra el
caserón de cada pozo.

LO REPORTADO: «Sigue sin guardar, pero a lo mejor yo lo estoy haciendo mal,
como lo haces tú?» — y, en el mismo mensaje, que el visor «sigue corriendo
mal». Investigando el visor (ocultar un caserón para aligerar la vista, ver
test_visor_ocultos_livianos.py) apareció una causa muy concreta para las dos
quejas a la vez: `save_project()` NUNCA guardaba `well.caseron` ni
`well.asignacion_err_pct` — el dict que arma por pozo tenía well_name,
plan_id, hole_id, collar, final_pt, origin, dq_candidates y points, pero no
esos dos.

El efecto es silencioso porque `caseron_de_pozo()` —la función que usa el
entrenamiento y el LOCO-CV— tiene una heurística de respaldo que deriva el
caserón del `plan_id` cuando el pozo no lo trae declarado, así que el
entrenamiento seguía viendo un caserón razonable y el defecto no saltaba ahí.
Pero el árbol de capas y el visor 3D (`resolver_ocultos`, `_layer_tree`) leen
`w.caseron` DIRECTO, sin ese respaldo: tras recargar un .gwz, TODOS los pozos
caían a "— sin caserón asignado —", la casilla de caserón dejaba de agrupar
nada, y el propio arreglo de rendimiento de esta sesión (ocultar un caserón
para aligerar la vista) quedaba inútil porque ya no había caserones que
ocultar. Es exactamente la clase de "se ve distinto/roto después de
recargar" que alguien describiría como "sigue sin guardar" aunque el archivo
se haya escrito bien.
"""

import os, sys, tempfile, shutil

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


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _escenario():
    reset()
    pts = []
    for i in range(20):
        p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este = E0; p.norte = N0 + i * 0.15; p.cota = Z0 - i * 0.12
        p.entrenable = True
        pts.append(p)
    w = gw.Well(well_name="T1", plan_id="PCS_1043_PR01_TH_P01", hole_id="1", points=pts)
    w.caseron = "PCS_1043"
    w.asignacion_err_pct = 3.4
    gw.wells["T1"] = w


def _roundtrip():
    tmpdir = tempfile.mkdtemp()
    try:
        path = os.path.join(tmpdir, "p.gwz")
        gw.save_project(path)
        gw.wells.clear()
        gw.load_project(path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
def el_caseron_sobrevive_a_guardar_y_recargar():
    section("Persistencia — well.caseron viaja en el .gwz")
    _escenario()
    _roundtrip()
    check("T1" in gw.wells, "el pozo se recargó", sorted(gw.wells))
    check(gw.wells["T1"].caseron == "PCS_1043",
          "y conserva el caserón DECLARADO, no uno derivado del plan_id "
          "recién después de perderlo", gw.wells["T1"].caseron)


def el_error_de_asignacion_sobrevive_tambien():
    section("Persistencia — asignacion_err_pct también viaja")
    _escenario()
    _roundtrip()
    check(gw.wells["T1"].asignacion_err_pct == 3.4,
          "una posición aproximada sigue marcada como tal tras recargar, en "
          "vez de verse igual que una exacta", gw.wells["T1"].asignacion_err_pct)


def el_arbol_de_capas_vuelve_a_agrupar_por_caseron_tras_recargar():
    section("Árbol/visor — resolver_ocultos ya no manda todo a «sin caserón»")
    _escenario()
    _roundtrip()
    ocultos_l, ocultos_w = gw.resolver_ocultos({"PCS_1043"}, set(), set(), set())
    check("T1" in ocultos_w,
          "apagar el caserón PCS_1043 en el árbol SÍ apaga el pozo T1: antes "
          "de este arreglo w.caseron volvía None tras recargar y esta casilla "
          "no encontraba nada que apagar", ocultos_w)


def un_pozo_sin_caseron_declarado_sigue_sin_el() :
    section("Regresión — un pozo que nunca tuvo caserón sigue en None, no se inventa uno")
    reset()
    pts = [gw.MWDPoint(largo=0.0, vel=0.9, pp=200.0, pa=60.0, pd=75.0, pr=45.0,
                       pf=8.0, se=340.0, t=0.0)]
    w = gw.Well(well_name="T2", plan_id="SIN_PATRON", hole_id="1", points=pts)
    gw.wells["T2"] = w
    _roundtrip()
    check(gw.wells["T2"].caseron is None,
          "sigue en None: la persistencia no fabrica un dato que nunca "
          "existió", gw.wells["T2"].caseron)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_caseron_sobrevive_a_guardar_y_recargar,
    el_error_de_asignacion_sobrevive_tambien,
    el_arbol_de_capas_vuelve_a_agrupar_por_caseron_tras_recargar,
    un_pozo_sin_caseron_declarado_sigue_sin_el,
]


def test_persistencia_caseron():
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
    print("✓ PERSISTENCIA — caserón y error de asignación — todas las verificaciones pasaron.")
    print("=" * 72)
