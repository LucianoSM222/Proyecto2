"""
test_vista3d_mallas.py — El visor deja de colgarse con mallas DXF reales.

LO REPORTADO: «Hay que mejorar el visor, pues se bloquea».

Medido sobre PCS_1043 real —el caserón más chico de los cuatro que entrenan—
un solo caserón trae 316.880 triángulos en sus 13 mallas —83.460 solo en
«Lavas»— y `build_3d_figure()` producía una figura de 52 MB de JSON, con
139 trazas. Subir eso a WebGL en un navegador, más aún dentro de un iframe de
Colab, es lo que colgaba el visor. Con los cuatro caserones del proyecto
cargados a la vez —el uso real de la plataforma— el problema se multiplica.

DOS DEFECTOS, uno de geometría y uno de texto repetido:

  · CADA MALLA SE DIBUJABA ENTERA, sin ningún tope. Los puntos MWD ya tenían
    MAX_VIZ_POINTS desde la sesión E.4; las mallas DXF no tenían nada
    equivalente. MAX_VIZ_TRIANGULOS_POR_MALLA aplica el MISMO submuestreo
    espaciado —determinista, nunca al azar, para no perder la forma general
    del sólido— que ya usan los pozos.

  · EL HOVER DE CADA MALLA REPETÍA EL MISMO TEXTO UNA VEZ POR TRIÁNGULO:
    `text=[...]*len(ii)` con 83.460 triángulos es 83.460 copias idénticas de
    la misma cadena, todas serializadas al JSON. Con un `text` como cadena
    única en vez de lista, Plotly lo aplica igual a toda la traza.

    Sobre PCS_1043, los dos arreglos juntos bajaron la figura de 52,2 MB a
    13,3 MB (−74%) y el tiempo de construcción de 3,35 s a 1,08 s.

`layer.triangles` —la malla REAL, la que usan los cálculos de traslape y
ray casting— nunca se toca: el recorte vive solo en lo que esta función
dibuja, igual que well.points para los puntos MWD.
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


def _malla_sintetica(nombre, n_tris, este0=0.0):
    """
    Un `Layer` con `n_tris` triángulos reales, dispuestos en una grilla
    simple. No es geología —es puro volumen de geometría—, que es justo lo
    que este test necesita: probar el RECORTE, no la forma.
    """
    rng = np.random.default_rng(hash(nombre) % (2**31))
    tris = np.empty((n_tris, 3, 3), dtype=np.float64)
    for i in range(n_tris):
        cx = este0 + (i % 200) * 0.5
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


def _pozo(wn, n=30):
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=300.0, t=0.0)
        p.este = E0; p.norte = N0 + i * 0.15; p.cota = Z0 - i * 0.12
        p.entrenable = True
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01",
                           hole_id=wn, points=pts)


# ─────────────────────────────────────────────────────────────────────────────
def una_malla_grande_se_recorta_en_la_vista():
    section("Vista 3D — una malla sobre el tope se dibuja recortada")
    reset()
    _pozo("T1")
    n_real = gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 3
    _malla_sintetica("Grande", n_real)
    fig = gw.build_3d_figure("se")
    trazas = [tr for tr in fig.data if getattr(tr, "name", None) == "Grande"]
    check(len(trazas) == 1, "la malla produce una sola traza", len(trazas))
    if not trazas:
        return
    tr = trazas[0]
    n_dibujados = len(tr.x) // 3
    check(n_dibujados == gw.MAX_VIZ_TRIANGULOS_POR_MALLA,
          "se dibujan exactamente MAX_VIZ_TRIANGULOS_POR_MALLA triángulos, "
          "no los reales", (n_dibujados, gw.MAX_VIZ_TRIANGULOS_POR_MALLA))
    check(gw.layers["Grande"].triangles.shape[0] == n_real,
          "y layer.triangles —la malla REAL, la que usan los cálculos de "
          "traslape— sigue teniendo todos los triángulos: el recorte es "
          "solo de lo que se dibuja", gw.layers["Grande"].triangles.shape[0])


def una_malla_chica_se_dibuja_entera():
    section("Vista 3D — una malla bajo el tope no pierde ni un triángulo")
    reset()
    _pozo("T1")
    n_real = 500
    _malla_sintetica("Chica", n_real)
    fig = gw.build_3d_figure("se")
    tr = next(tr for tr in fig.data if getattr(tr, "name", None) == "Chica")
    check(len(tr.x) // 3 == n_real,
          "bajo el tope se dibuja el 100%, sin recortar de más", len(tr.x) // 3)


def el_texto_del_hover_es_una_cadena_no_una_lista():
    section("Vista 3D — el hover ya no repite el texto por triángulo")
    reset()
    _pozo("T1")
    _malla_sintetica("Cualquiera", 2000)
    fig = gw.build_3d_figure("se")
    tr = next(tr for tr in fig.data if getattr(tr, "name", None) == "Cualquiera")
    check(isinstance(tr.text, str),
          "`text` es una cadena única, no una lista de miles de copias "
          "idénticas: eso solo era peso muerto en el JSON de la figura",
          type(tr.text).__name__)
    check("Cualquiera" in tr.text, "y trae el nombre de la malla", tr.text)


def la_declaracion_de_recorte_aparece_en_el_hover():
    section("Vista 3D — una malla recortada lo declara, no lo esconde")
    reset()
    _pozo("T1")
    n_real = gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 4
    _malla_sintetica("Recortada", n_real)
    fig = gw.build_3d_figure("se")
    tr = next(tr for tr in fig.data if getattr(tr, "name", None) == "Recortada")
    check("mostrando" in tr.text.lower(),
          "el hover dice que se está mostrando un recorte, no el total real",
          tr.text)
    check(f"{gw.MAX_VIZ_TRIANGULOS_POR_MALLA:,}".replace(",", ".") in tr.text,
          "con cuántos se dibujan", tr.text)
    check(f"{n_real:,}".replace(",", ".") in tr.text,
          "y cuántos hay en realidad: quien mira el visor tiene que poder "
          "saber que no está viendo el sólido completo", tr.text)


def el_peso_de_la_figura_baja_de_verdad():
    section("Vista 3D — el JSON de la figura no crece con la malla real")
    reset()
    _pozo("T1")
    n_real = gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 8
    _malla_sintetica("Pesada", n_real)
    fig = gw.build_3d_figure("se")
    peso_mb = len(fig.to_json()) / 1e6
    print(f"      ({n_real:,} triángulos reales · figura {peso_mb:.2f} MB)"
          .replace(",", "."))
    # Sin el tope, 8x MAX_VIZ_TRIANGULOS_POR_MALLA en una sola malla pesaría
    # varios múltiplos de esto. El límite no es exacto —depende del resto de
    # la escena— pero tiene que quedar muy por debajo de escalar 1:1 con
    # n_real.
    check(peso_mb < 15.0,
          "la figura queda acotada por el tope, no por el tamaño real de la "
          "malla", peso_mb)


def apagar_una_malla_grande_sigue_funcionando():
    section("Vista 3D — ocultar una malla recortada no se rompió")
    reset()
    _pozo("T1")
    _malla_sintetica("Grande", gw.MAX_VIZ_TRIANGULOS_POR_MALLA * 2)
    fig = gw.build_3d_figure("se", hidden_layers={"Grande"})
    tr = next(tr for tr in fig.data if getattr(tr, "name", None) == "Grande")
    check(tr.visible == "legendonly",
          "sigue en legendonly, como antes del recorte", tr.visible)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    una_malla_grande_se_recorta_en_la_vista,
    una_malla_chica_se_dibuja_entera,
    el_texto_del_hover_es_una_cadena_no_una_lista,
    la_declaracion_de_recorte_aparece_en_el_hover,
    el_peso_de_la_figura_baja_de_verdad,
    apagar_una_malla_grande_sigue_funcionando,
]


def test_vista3d_mallas():
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
    print("✓ VISTA 3D — MALLAS — todas las verificaciones pasaron.")
    print("=" * 72)
