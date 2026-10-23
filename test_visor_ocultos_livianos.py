"""
test_visor_ocultos_livianos.py — Ocultar un pozo o una malla en el árbol
ahora sí aligera la figura que viaja al navegador.

LO REPORTADO: «Me sigue corriendo mal el visor» — tras dos rondas previas de
arreglos (recorte a MAX_VIZ_POINTS, recorte a MAX_VIZ_TRIANGULOS_POR_MALLA)
que ya redujeron el peso de CADA elemento visible.

LO QUE FALTABA: los checkboxes del árbol (vis-caseron/vis-layer/vis-well)
marcan un pozo o malla oculto con `visible="legendonly"`, pero antes de este
arreglo eso NO cambiaba el CONTENIDO de la traza — un pozo oculto seguía
mandando su serie de puntos completa (recortada por MAX_VIZ_POINTS, pero
completa dentro de ese recorte) y una malla oculta sus triángulos completos
(recortados por MAX_VIZ_TRIANGULOS_POR_MALLA, pero completos dentro de eso).
"legendonly" le dice a Plotly que no lo DIBUJE, no que no lo ARME ni que no
lo MANDE: ocultar 400 de 463 pozos no ahorraba un byte de JSON.

Medido sobre PCS_1043+PCC_0042 reales (601.324 puntos, 463 pozos, 17 mallas):
con un caserón completo (338 pozos, 4 mallas) apagado, el armado bajó de
1,12 s a 0,87 s y el JSON de 18,30 a 13,65 MB.

LA TRAZA NO SE OMITE — sigue en la figura, en el mismo índice, con el mismo
nombre, visible="legendonly": eso es deliberado. `uirevision="viewport"`
(fijo, en render_viewport) depende de que el número y el orden de trazas no
cambien entre renders para conservar la cámara; omitir la traza reordenaría
los índices cada vez que cambia qué está tildado. Lo único que se recorta es
el CONTENIDO: un pozo oculto manda solo su collar (un punto), una malla
oculta un único triángulo — la traza existe, casi no pesa nada.
"""

import os, sys
import numpy as np

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


def _pozo(wn, n=200):
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=300.0, t=0.0)
        p.este = E0; p.norte = N0 + i * 0.15; p.cota = Z0 - i * 0.12
        p.entrenable = True
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01",
                           hole_id=wn, points=pts)


def _malla(nombre, n_tris):
    rng = np.random.default_rng(hash(nombre) % (2**31))
    tris = np.empty((n_tris, 3, 3), dtype=np.float64)
    for i in range(n_tris):
        cx = E0 + (i % 200) * 0.5
        cy = N0 + (i // 200) * 0.5
        cz = Z0 - rng.uniform(0, 30)
        tris[i, 0] = [cx, cy, cz]
        tris[i, 1] = [cx + 0.4, cy, cz]
        tris[i, 2] = [cx, cy + 0.4, cz]
    layer = gw.Layer(name=nombre, kind="mesh", triangles=tris,
                     bbox_min=tris.reshape(-1, 3).min(axis=0),
                     bbox_max=tris.reshape(-1, 3).max(axis=0))
    gw.layers[nombre] = layer
    return layer


def _escenario():
    reset()
    _pozo("T1"); _pozo("T2")
    _malla("Grande", gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 3)


# ─────────────────────────────────────────────────────────────────────────────
def un_pozo_oculto_manda_un_solo_punto():
    section("Pozo oculto — la traza existe pero solo lleva el collar")
    _escenario()
    fig = gw.build_3d_figure("se", hidden_wells={"T2"})
    por_nombre = {tr.name: tr for tr in fig.data}
    check("T2" in por_nombre,
          "la traza del pozo oculto sigue en la figura (mismo índice, mismo "
          "nombre) para que uirevision no pierda la cámara", sorted(por_nombre))
    check(por_nombre["T2"].visible == "legendonly",
          "queda en legendonly", por_nombre["T2"].visible)
    check(len(por_nombre["T2"].x) == 1,
          "pero su serie se recortó a UN solo punto —el collar—, no a los "
          "200 recortados-por-presupuesto de antes", len(por_nombre["T2"].x))
    check(por_nombre["T1"].visible is True and len(por_nombre["T1"].x) > 1,
          "el pozo visible sigue con su serie completa (o recortada por "
          "presupuesto, nunca a un punto)", len(por_nombre["T1"].x))


def una_malla_oculta_manda_un_solo_triangulo():
    section("Malla oculta — la traza existe pero con un único triángulo")
    _escenario()
    fig = gw.build_3d_figure("se", hidden_layers={"Grande"})
    por_nombre = {tr.name: tr for tr in fig.data}
    check("Grande" in por_nombre,
          "la traza de la malla oculta sigue en la figura", sorted(por_nombre))
    check(por_nombre["Grande"].visible == "legendonly",
          "queda en legendonly", por_nombre["Grande"].visible)
    n_tris_traza = len(por_nombre["Grande"].x) // 3
    check(n_tris_traza == 1,
          "pero manda un único triángulo, no los "
          f"{gw.MAX_VIZ_TRIANGULOS_POR_MALLA} recortados-por-tope de una "
          "malla grande visible", n_tris_traza)
    check(gw.layers["Grande"].triangles.shape[0] == gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 3,
          "layer.triangles —la malla REAL— nunca se toca", None)


def ocultar_no_cambia_el_indice_ni_el_orden_de_las_trazas():
    section("Estabilidad — el índice y el orden de trazas no cambian al ocultar")
    _escenario()
    fig_todo = gw.build_3d_figure("se")
    fig_oculto = gw.build_3d_figure("se", hidden_wells={"T2"}, hidden_layers={"Grande"})
    nombres_todo = [tr.name for tr in fig_todo.data]
    nombres_oculto = [tr.name for tr in fig_oculto.data]
    check(nombres_todo == nombres_oculto,
          "mismo número y mismo orden de trazas con o sin ocultos: "
          "uirevision necesita esto para conservar la cámara entre renders",
          (nombres_todo, nombres_oculto))


def ocultar_reduce_el_peso_real_del_json():
    section("Peso — ocultar de verdad reduce lo que viaja al navegador")
    _escenario()
    fig_todo = gw.build_3d_figure("se")
    fig_oculto = gw.build_3d_figure("se", hidden_wells={"T2"}, hidden_layers={"Grande"})
    peso_todo = len(fig_todo.to_json())
    peso_oculto = len(fig_oculto.to_json())
    check(peso_oculto < peso_todo * 0.5,
          "con el pozo grande y la malla grande ocultos, el JSON baja a menos "
          "de la mitad: antes de este arreglo quedaba prácticamente igual",
          (peso_todo, peso_oculto))


def el_presupuesto_de_puntos_se_reparte_solo_entre_los_visibles():
    section("Presupuesto — un pozo oculto no le quita puntos a los visibles")
    reset()
    _pozo("Chico", n=50)
    _pozo("Grande", n=gw.MAX_VIZ_POINTS * 2)
    # Con el pozo grande OCULTO, el chico debería quedarse con TODOS sus
    # puntos: ya no compite por presupuesto contra algo que no se dibuja.
    fig = gw.build_3d_figure("se", hidden_wells={"Grande"})
    por_nombre = {tr.name: tr for tr in fig.data}
    check(len(por_nombre["Chico"].x) == 50,
          "el pozo visible conserva TODOS sus puntos: el presupuesto ya no "
          "se reparte contra el total del proyecto, solo contra lo visible",
          len(por_nombre["Chico"].x))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    un_pozo_oculto_manda_un_solo_punto,
    una_malla_oculta_manda_un_solo_triangulo,
    ocultar_no_cambia_el_indice_ni_el_orden_de_las_trazas,
    ocultar_reduce_el_peso_real_del_json,
    el_presupuesto_de_puntos_se_reparte_solo_entre_los_visibles,
]


def test_visor_ocultos_livianos():
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
    print("✓ VISOR — ocultos livianos — todas las verificaciones pasaron.")
    print("=" * 72)
