"""
test_arbol_carpetas.py — Árbol de capas ordenado por caserón.

LO PEDIDO: carpetas principales por CASERÓN que se puedan prender y apagar, y
al desplegar una, carpetas de tiros, litología, estructuras y sondajes. Los
tiros agrupados por ABANICO, automáticamente.

El árbol plano de antes listaba 619 pozos y 23 mallas de tres caserones en una
sola lista: encontrar un abanico ahí es imposible, y apagar un caserón entero
para mirar otro, también.

La agrupación por abanico es AUTOMÁTICA: sale del plan_id del DQ, que es
justamente lo que identifica el abanico perforado. No hay que etiquetar nada
a mano.

Un caserón apagado apaga todo lo suyo —mallas, tiros y sondajes— sin que haya
que destildar cada uno.
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
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _malla(nombre, kind, caseron):
    tri = np.zeros((1, 3, 3))
    lay = gw.Layer(name=nombre, kind=kind, triangles=tri,
                   bbox_min=np.zeros(3), bbox_max=np.ones(3))
    lay.caseron = caseron
    gw.layers[nombre] = lay
    return lay


def _pozo(wn, plan, caseron):
    pts = [gw.MWDPoint(largo=i * 0.5, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                       pr=45.0, pf=8.0, se=340.0, t=0.0) for i in range(6)]
    for i, p in enumerate(pts):
        p.este = E0; p.norte = N0; p.cota = Z0 - i * 0.5
        p.entrenable = True
    w = gw.Well(well_name=wn, plan_id=plan, hole_id=wn, points=pts)
    w.caseron = caseron
    gw.wells[wn] = w
    return w


def _sondaje(hid, este):
    dh = gw.DrillHole(holeid=hid, x_utm=este, y_utm=N0, z_utm=Z0, length=20.0)
    dh.trace = [(0.0, este, N0, Z0), (20.0, este, N0, Z0 - 20.0)]
    gw.drillholes[hid] = dh
    return dh


def _escenario():
    reset()
    _malla("Bht.dxf", "litologia", "PCS_1043")
    _malla("FM1.dxf", "estructura", "PCS_1043")
    _malla("Kpcli.dxf", "litologia", "PCC_0042")
    for h in range(3):
        _pozo(f"A1_H{h}", "PCS_1043_PR01_TH_P01", "PCS_1043")
    for h in range(2):
        _pozo(f"A2_H{h}", "PCS_1043_PR01_TH_P02", "PCS_1043")
    _pozo("B1_H1", "PCC_0042_PR01_TH_P10", "PCC_0042")
    _sondaje("DDH-1", E0 + 5.0)


def _textos(nodo):
    """Todo el texto de un árbol de componentes Dash, aplanado."""
    out = []
    def rec(x):
        if isinstance(x, str):
            out.append(x); return
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        for attr in ("children", "title", "label"):
            v = getattr(x, attr, None)
            if v is not None: rec(v)
    rec(nodo)
    return out


def _ids(nodo):
    """Todos los ids de un árbol de componentes Dash."""
    out = []
    def rec(x):
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        i = getattr(x, "id", None)
        if i is not None: out.append(i)
        for attr in ("children", "title"):
            v = getattr(x, attr, None)
            if v is not None: rec(v)
    rec(nodo)
    return out


# ─────────────────────────────────────────────────────────────────────────────
def hay_una_carpeta_por_caseron():
    section("Árbol — una carpeta principal por caserón")
    _escenario()
    arbol = gw._layer_tree()
    txt = " | ".join(_textos(arbol))
    check("PCS_1043" in txt, "aparece PCS_1043", txt[:200])
    check("PCC_0042" in txt, "aparece PCC_0042", txt[:200])
    ids = _ids(arbol)
    cas_ids = [i["index"] for i in ids
               if isinstance(i, dict) and i.get("type") == "vis-caseron"]
    check({"PCS_1043", "PCC_0042"} <= set(cas_ids),
          "cada caserón trae su interruptor para prenderlo y apagarlo entero",
          cas_ids)
    # El sondaje del escenario todavía no cruzó ninguna malla, así que no
    # tiene caserón: va a su propia carpeta en vez de colarse en uno ajeno.
    check(gw.SIN_CASERON in cas_ids,
          "y lo que no tiene caserón asignado tiene la suya, no se cuela en otro",
          cas_ids)


def dentro_van_las_cuatro_carpetas():
    section("Árbol — dentro de un caserón: tiros, litología, estructuras, sondajes")
    _escenario()
    txt = " | ".join(_textos(gw._layer_tree())).lower()
    for palabra in ("tiros", "litolog", "estructura", "sondaje"):
        check(palabra in txt, f"hay carpeta de {palabra}", txt[:300])


def los_tiros_se_agrupan_por_abanico():
    section("Árbol — los tiros se agrupan por ABANICO, automáticamente")
    _escenario()
    txt = " | ".join(_textos(gw._layer_tree()))
    check("PR01_TH_P01" in txt or "P01" in txt, "aparece el abanico P01", txt[:300])
    check("PR01_TH_P02" in txt or "P02" in txt, "y el abanico P02", txt[:300])
    # Tres tiros en el primero, dos en el segundo: el conteo tiene que verse.
    check("(3)" in txt and "(2)" in txt,
          "con cuántos tiros tiene cada uno", [t for t in _textos(gw._layer_tree())
                                               if "(" in t][:6])


def cada_pozo_sigue_teniendo_su_control():
    section("Árbol — agrupar no quita el control individual")
    _escenario()
    ids = gw._ids_arbol() if hasattr(gw, "_ids_arbol") else _ids(gw._layer_tree())
    vis_well = [i for i in ids if isinstance(i, dict) and i.get("type") == "vis-well"]
    vis_layer = [i for i in ids if isinstance(i, dict) and i.get("type") == "vis-layer"]
    vis_dh = [i for i in ids if isinstance(i, dict) and i.get("type") == "vis-dh"]
    check(len(vis_well) == 6, "los seis pozos conservan su casilla", len(vis_well))
    check(len(vis_layer) == 3, "las tres mallas también", len(vis_layer))
    check(len(vis_dh) == 1, "y el sondaje tiene la suya", len(vis_dh))


def apagar_un_caseron_apaga_lo_suyo():
    section("Árbol — apagar un caserón apaga sus mallas, tiros y sondajes")
    _escenario()
    ocultos_l, ocultos_w = gw.resolver_ocultos(
        caserones_apagados={"PCS_1043"}, mallas_apagadas=set(), pozos_apagados=set(),
        sondajes_apagados=set())
    check("Bht.dxf" in ocultos_l and "FM1.dxf" in ocultos_l,
          "las mallas del caserón quedan ocultas", sorted(ocultos_l))
    check("Kpcli.dxf" not in ocultos_l,
          "y las del otro caserón NO", sorted(ocultos_l))
    check({"A1_H0", "A1_H1", "A1_H2", "A2_H0", "A2_H1"} <= ocultos_w,
          "los cinco tiros del caserón quedan ocultos", sorted(ocultos_w))
    check("B1_H1" not in ocultos_w, "y el del otro caserón no", sorted(ocultos_w))


def el_control_individual_manda_igual():
    section("Árbol — con el caserón encendido, la casilla individual sigue mandando")
    _escenario()
    ocultos_l, ocultos_w = gw.resolver_ocultos(
        caserones_apagados=set(), mallas_apagadas={"Bht.dxf"},
        pozos_apagados={"A1_H0"}, sondajes_apagados={"DDH-1"})
    check(ocultos_l == {"Bht.dxf"}, "solo la malla destildada", ocultos_l)
    check("A1_H0" in ocultos_w, "solo el tiro destildado", sorted(ocultos_w))
    check("DH::DDH-1" in ocultos_w,
          "y el sondaje destildado, con su prefijo para no chocar con un pozo",
          sorted(ocultos_w))


def sin_caseron_asignado_tiene_su_carpeta():
    section("Árbol — lo que no tiene caserón no desaparece: va a su propia carpeta")
    reset()
    _malla("suelta.dxf", "litologia", None)
    _pozo("X_H1", "PLAN_X", None)
    txt = " | ".join(_textos(gw._layer_tree()))
    check("suelta.dxf" in txt, "la malla sin caserón se sigue viendo", txt[:200])
    check("X_H1" in txt, "y el pozo también", txt[:200])
    check("sin caserón" in txt.lower() or "sin caseron" in txt.lower(),
          "en una carpeta que dice qué son", txt[:200])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    hay_una_carpeta_por_caseron,
    dentro_van_las_cuatro_carpetas,
    los_tiros_se_agrupan_por_abanico,
    cada_pozo_sigue_teniendo_su_control,
    apagar_un_caseron_apaga_lo_suyo,
    el_control_individual_manda_igual,
    sin_caseron_asignado_tiene_su_carpeta,
]


def test_arbol_carpetas():
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
    print("✓ ÁRBOL DE CARPETAS — todas las verificaciones pasaron.")
    print("=" * 72)
