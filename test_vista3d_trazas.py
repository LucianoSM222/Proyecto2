"""
test_vista3d_trazas.py — La vista 3D deja de dibujar 600 barras de color.

LO PEDIDO, en palabras del autor: «en general el programa es lento».

La vista 3D se redibuja en cada refresco, así que lo que cueste se paga en
cada acción de la interfaz. Cronometrada con 600 pozos —el orden de los cuatro
caserones— tardaba 1.157 ms, y el perfilador mostró de dónde salía: no del
dato, sino de construir objetos de Plotly.

  · CADA POZO DECLARABA SU PROPIA BARRA DE COLOR, con `showscale=True` y un
    dict de colorbar completo. Con 600 pozos, Plotly construía 600 barras
    idénticas apiladas en la misma x. Es un defecto de dibujo además de uno de
    velocidad: la escala es UNA, no una por tiro.

  · CADA COLLAR ERA UNA TRAZA. Un objeto Scatter3d por pozo para pintar un
    punto negro: 600 objetos para 600 puntos.

Quedó en 713 ms. Este test fija las dos cosas y —lo que importa— fija que
NINGUNA de las dos cambió lo que se ve: los mismos pozos, los mismos collares,
la misma escala, y el poder apagar un pozo suelto intacto.
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


def _pozos(n_pozos=12, n_pts=40):
    reset()
    for k in range(n_pozos):
        pts = []
        for i in range(n_pts):
            p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                            pr=45.0, pf=8.0, se=300.0 + i, t=0.0)
            p.este = E0 + k * 2.0
            p.norte = N0 + i * 0.15
            p.cota = Z0 - i * 0.12
            p.entrenable = True
            p.dominio = p.lito = "Bht"
            p.di = 0.5
            pts.append(p)
        gw.wells[f"T{k}"] = gw.Well(well_name=f"T{k}",
                                    plan_id="CAS_PR01_TH_P01", hole_id=str(k),
                                    points=pts)


def _con_barra(fig):
    """Trazas que declaran barra de color."""
    out = []
    for tr in fig.data:
        m = getattr(tr, "marker", None)
        if m is not None and getattr(m, "showscale", None):
            out.append(getattr(tr, "name", None))
    return out


# ─────────────────────────────────────────────────────────────────────────────
def una_sola_barra_de_color():
    section("Vista 3D — la escala es UNA, no una por pozo")
    _pozos(n_pozos=12)
    fig = gw.build_3d_figure("se")
    con_barra = _con_barra(fig)
    check(len(con_barra) == 1,
          "exactamente una traza lleva la barra de color, con 12 pozos "
          "dibujados", con_barra)
    # Y la que la lleva tiene que traer el rótulo: una barra sin título no
    # dice qué está midiendo.
    barra = None
    for tr in fig.data:
        m = getattr(tr, "marker", None)
        if m is not None and getattr(m, "showscale", None):
            barra = getattr(m, "colorbar", None)
    check(barra is not None, "y trae su colorbar")
    titulo = str(getattr(getattr(barra, "title", None), "text", "") or "")
    check(titulo, "con el rótulo de qué variable se está viendo", titulo)
    esperado = gw.COLOR_FIELDS["se"][0]
    check(titulo == esperado, "que es el de la variable elegida",
          (titulo, esperado))


def la_escala_no_se_recorta_al_juntarla():
    section("Vista 3D — juntar la barra no cambió los límites de la escala")
    _pozos(n_pozos=12)
    fig = gw.build_3d_figure("se")
    _, cmin, cmax, _, _ = gw.COLOR_FIELDS["se"]
    marcadores = [getattr(tr, "marker", None) for tr in fig.data]
    escalas = [(m.cmin, m.cmax) for m in marcadores
               if m is not None and getattr(m, "cmin", None) is not None]
    check(escalas, "hay trazas con escala continua", len(escalas))
    check(all(e == (cmin, cmax) for e in escalas),
          "TODAS comparten los mismos límites: si cada pozo se autoescalara, "
          "dos pozos con el mismo valor se verían de colores distintos",
          set(escalas))


def los_collares_siguen_estando_todos():
    section("Vista 3D — un solo objeto para los collares, los mismos collares")
    _pozos(n_pozos=12)
    fig = gw.build_3d_figure("se")
    collares = [tr for tr in fig.data if getattr(tr, "name", None) == "collares"]
    check(len(collares) == 1, "los collares van en UNA traza", len(collares))
    if not collares:
        return
    c = collares[0]
    check(len(c.x) == len(gw.wells),
          "con un punto por pozo: ninguno se perdió al juntarlos",
          (len(c.x), len(gw.wells)))
    check(len(c.hovertext) == len(c.x),
          "y cada uno conserva su hover, que dice de qué pozo es",
          (len(c.hovertext), len(c.x)))
    esperados = {f"Collar T{k}" for k in range(len(gw.wells))}
    vistos = {t.split(":")[0] for t in c.hovertext}
    check(vistos == esperados, "y son los pozos que hay", sorted(vistos - esperados))


def apagar_un_pozo_sigue_funcionando():
    section("Vista 3D — apagar un pozo suelto no se rompió")
    _pozos(n_pozos=12)
    fig = gw.build_3d_figure("se", hidden_wells={"T3"})
    por_nombre = {getattr(tr, "name", None): tr for tr in fig.data}
    check("T3" in por_nombre, "la traza del pozo apagado SIGUE en la figura: "
          "se oculta, no se omite, para que el índice de trazas no se corra y "
          "uirevision conserve la cámara")
    check(por_nombre["T3"].visible == "legendonly",
          "y queda en legendonly", por_nombre["T3"].visible)
    check(por_nombre["T0"].visible is True, "los demás siguen visibles",
          por_nombre["T0"].visible)
    # Un pozo apagado no aporta su collar al montón.
    collares = [tr for tr in fig.data if getattr(tr, "name", None) == "collares"]
    if collares:
        vistos = {t.split(":")[0] for t in collares[0].hovertext}
        check("Collar T3" not in vistos,
              "y su collar tampoco se dibuja: antes cada collar era su propia "
              "traza y podía apagarse solo; ahora van juntos, así que el "
              "apagado se resuelve al armarlos", sorted(vistos)[:4])


def el_conteo_de_trazas_es_el_esperado():
    section("Vista 3D — una traza por pozo más una de collares, y nada más")
    _pozos(n_pozos=12)
    fig = gw.build_3d_figure("se")
    n = len(fig.data)
    # 12 pozos + 1 traza de collares. Sin mallas ni sondajes cargados.
    check(n == len(gw.wells) + 1,
          "12 pozos → 13 trazas. Antes eran 24: una de collar y una de datos "
          "por pozo", n)


def los_collares_cuentan_contra_el_tope():
    section("Vista 3D — los collares también son marcadores y cuentan")
    reset()
    # Bastante más que MAX_VIZ_POINTS, repartido en muchos pozos: es el caso
    # donde un marcador extra por pozo se nota.
    n_pozos = 40
    _pozos(n_pozos=n_pozos, n_pts=400)
    total_real = sum(len(w.points) for w in gw.wells.values())
    check(total_real > gw.MAX_VIZ_POINTS,
          "el escenario supera el tope, si no el test no prueba nada", total_real)
    fig = gw.build_3d_figure("se")
    dibujados = sum(len(tr.x) for tr in fig.data
                    if tr.type == "scatter3d" and tr.mode and "markers" in tr.mode)
    check(dibujados <= gw.MAX_VIZ_POINTS,
          "TODOS los marcadores, collares incluidos, caben en el tope. Antes "
          "los collares iban en trazas de un punto y el conteo los pasaba por "
          "alto: la vista dibujaba el tope MÁS un marcador por pozo",
          (dibujados, gw.MAX_VIZ_POINTS))
    check(dibujados > gw.MAX_VIZ_POINTS * 0.8,
          "y el tope se aprovecha, no se recorta de más por reservar",
          dibujados)


def modo_categorico_no_pide_barra():
    section("Vista 3D — el coloreo por categoría no arrastra barra continua")
    _pozos(n_pozos=6)
    for w in gw.wells.values():
        for p in w.points:
            p.lito = "Bht"
    fig = gw.build_3d_figure("lito")
    check(not _con_barra(fig),
          "coloreando por litología no hay barra continua: son categorías, "
          "no un rango", _con_barra(fig))
    check(len(fig.data) == len(gw.wells) + 1,
          "y el conteo de trazas es el mismo", len(fig.data))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    una_sola_barra_de_color,
    la_escala_no_se_recorta_al_juntarla,
    los_collares_siguen_estando_todos,
    apagar_un_pozo_sigue_funcionando,
    el_conteo_de_trazas_es_el_esperado,
    los_collares_cuentan_contra_el_tope,
    modo_categorico_no_pide_barra,
]


def test_vista3d_trazas():
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
    print("✓ VISTA 3D — todas las verificaciones pasaron.")
    print("=" * 72)
