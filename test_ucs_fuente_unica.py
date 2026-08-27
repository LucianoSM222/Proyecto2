"""
test_ucs_fuente_unica.py — Una sola fuente de UCS, y elegir qué estadística
alimenta el modelo.

EL PROBLEMA: había TRES fuentes de UCS compitiendo. El registro de atributos
con su estadística, el campo manual de la ventana de capas, y las bandas del
Excel geomecánico. Tres verdades para el mismo número, y la que ganaba
dependía del orden en que se cargaran las cosas.

AHORA: el registro de atributos es la única fuente. Y como una banda de UCS no
es un número sino una estadística, hay que ELEGIR cuál se usa como etiqueta:

  · central      el valor documentado como central (σci de Hoek-Brown, por
                 ejemplo). Es lo que se venía usando.
  · media        la media de las probetas.
  · mediana      la mediana, cuando la faena la tiene documentada.
  · rango_medio  el punto medio de la banda min-max.
  · rango_vs_se  el rango de UCS proyectado sobre el rango de SE observado en
                 los pozos de esa litología. NO es una etiqueta constante:
                 cada punto recibe la suya.

La última merece una advertencia que el programa NO se puede callar: si la
etiqueta se construye desde SE y SE es predictora, el modelo aprende la
proyección y no la roca. Por eso ese modo excluye SE de las predictoras y lo
declara.

La elección vive en el perfil de faena, no en el código: otra faena con otra
estadística documentada elige la suya.
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


def _attr():
    gw.create_attribute(attr_id="Roca", nombre_oficial="Roca de prueba",
                        rol="litologia", ucs_min=100.0, ucs_max=200.0,
                        ucs_media=140.0, ucs_central=155.0, ucs_mediana=135.0,
                        calidad=1, fuente="ensayo del sitio")


def _pozo(wn, n=200, se_desde=200.0, se_hasta=400.0):
    pts = []
    for i in range(n):
        se = se_desde + (se_hasta - se_desde) * i / max(n - 1, 1)
        p = gw.MWDPoint(largo=i * 0.02, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=se, t=0.0)
        p.este = E0; p.norte = N0; p.cota = Z0 - i * 0.02
        p.entrenable = True; p.dominio = "Roca"; p.lito = "Roca"
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


# ─────────────────────────────────────────────────────────────────────────────
def la_estadistica_se_elige_desde_el_perfil():
    section("Una fuente — qué estadística alimenta el ML se elige, no se asume")
    reset()
    check("ucs.estadistica_ml" in gw.param_registry,
          "el modo es un parámetro del perfil de faena")
    p = gw.param_registry["ucs.estadistica_ml"]
    check(p["valor"] == "auto",
          "por defecto es la cadena histórica: un modo estricto dejaría sin "
          "etiqueta a los atributos que no documentan esa estadística, y esos "
          "puntos saldrían del entrenamiento sin que nada lo delate", p["valor"])
    check(set(p.get("opciones") or []) >=
          {"auto", "central", "media", "mediana", "rango_medio", "rango_vs_se"},
          "y declara sus opciones", p.get("opciones"))
    try:
        gw.set_param("ucs.estadistica_ml", "no_existe")
        check(False, "un modo inventado tiene que fallar")
    except ValueError:
        check(True, "un modo fuera de la lista se rechaza")
    check(gw.get_param("ucs.estadistica_ml") == "auto",
          "y el perfil queda en su valor anterior")


def cada_modo_da_su_numero():
    section("Una fuente — cada modo entrega la estadística que promete")
    reset(); _attr()
    a = gw.attr_registry["Roca"]
    esperado = {"central": 155.0, "media": 140.0, "mediana": 135.0,
                "rango_medio": 150.0}
    for modo, v in esperado.items():
        got = a.ucs_ancla(modo=modo)
        check(got == v, f"modo «{modo}» da {v}", got)
    # Un modo sin dato documentado NO cae en silencio a otro: devuelve None.
    gw.create_attribute(attr_id="Pobre", nombre_oficial="Sin mediana",
                        rol="litologia", ucs_min=80.0, ucs_max=120.0, calidad=4,
                        fuente="literatura")
    b = gw.attr_registry["Pobre"]
    check(b.ucs_ancla(modo="mediana") is None,
          "sin mediana documentada el modo devuelve None, no otro valor",
          b.ucs_ancla(modo="mediana"))
    check(b.ucs_ancla(modo="rango_medio") == 100.0,
          "pero el punto medio del rango sí se puede calcular",
          b.ucs_ancla(modo="rango_medio"))


def el_modo_llega_a_los_dominios():
    section("Una fuente — cambiar el modo cambia la etiqueta de los dominios")
    reset(); _attr(); _pozo("W1")
    gw.build_domain_index()
    check(gw.domains["Roca"]["ucs_lab"] == 155.0,
          "con 'auto' gana el valor central: 155", gw.domains["Roca"]["ucs_lab"])
    # Y un atributo que solo documenta media NO se queda sin etiqueta.
    gw.create_attribute(attr_id="SoloMedia", nombre_oficial="Solo media",
                        rol="litologia", ucs_media=90.0, calidad=2,
                        fuente="componente RMR local")
    check(gw.attr_registry["SoloMedia"].ucs_ancla(modo="auto") == 90.0,
          "y un atributo que solo trae media conserva su etiqueta con 'auto'",
          gw.attr_registry["SoloMedia"].ucs_ancla(modo="auto"))
    check(gw.attr_registry["SoloMedia"].ucs_ancla(modo="central") is None,
          "mientras que el modo estricto la deja sin etiqueta, y por eso no es "
          "el defecto")
    gw.set_param("ucs.estadistica_ml", "media")
    gw.build_domain_index()
    check(gw.domains["Roca"]["ucs_lab"] == 140.0,
          "con 'media' pasa a 140", gw.domains["Roca"]["ucs_lab"])
    check("media" in (gw.domains["Roca"].get("modo_ucs") or ""),
          "y el dominio declara con qué modo se etiquetó",
          gw.domains["Roca"].get("modo_ucs"))
    gw.seed_param_registry(force=True)


def rango_vs_se_reparte_dentro_de_la_litologia():
    section("Una fuente — «rango_vs_se» da una etiqueta POR PUNTO, no una sola")
    reset(); _attr()
    _pozo("W1", n=200, se_desde=200.0, se_hasta=400.0)
    gw.set_param("ucs.estadistica_ml", "rango_vs_se")
    rep = gw.aplicar_ucs_por_se()
    check(rep["status"] == "ok", "el reparto corre", rep.get("motivo"))
    if rep["status"] != "ok":
        gw.seed_param_registry(force=True); return
    vals = sorted({round(p.ucs_por_se, 1) for p in gw.wells["W1"].points
                   if p.ucs_por_se is not None})
    check(len(vals) > 10,
          "la litología deja de tener UNA etiqueta y pasa a tener muchas",
          len(vals))
    check(abs(min(vals) - 100.0) < 1.0 and abs(max(vals) - 200.0) < 1.0,
          "que recorren la banda min-max del atributo", (min(vals), max(vals)))
    # Mayor SE -> mayor UCS: la proyección respeta el orden.
    pts = sorted(gw.wells["W1"].points, key=lambda p: p.se)
    check(pts[0].ucs_por_se < pts[-1].ucs_por_se,
          "y más energía específica se proyecta a más UCS",
          (pts[0].ucs_por_se, pts[-1].ucs_por_se))
    check(rep.get("advertencia_circularidad"),
          "el reporte NO se calla la circularidad con SE",
          rep.get("advertencia_circularidad"))
    check("se" in (rep.get("predictoras_excluidas") or []),
          "y declara que SE queda fuera de las predictoras",
          rep.get("predictoras_excluidas"))
    gw.seed_param_registry(force=True)


def rango_vs_se_sin_banda_no_inventa():
    section("Una fuente — sin banda min-max no hay proyección que hacer")
    reset()
    gw.create_attribute(attr_id="SinBanda", nombre_oficial="Sin banda",
                        rol="litologia", ucs_central=120.0, calidad=3,
                        fuente="análogo")
    w = _pozo("W1")
    for p in w.points:
        p.dominio = p.lito = "SinBanda"
    gw.set_param("ucs.estadistica_ml", "rango_vs_se")
    rep = gw.aplicar_ucs_por_se()
    check(rep["status"] in ("ok", "sin_datos"), "declara su estado", rep.get("status"))
    check(all(p.ucs_por_se is None for p in w.points),
          "ningún punto recibe un UCS proyectado desde una banda que no existe")
    check(rep.get("sin_banda"), "y se declara qué litologías quedaron fuera",
          rep.get("sin_banda"))
    gw.seed_param_registry(force=True)


def la_capa_ya_no_pide_ucs():
    section("Una fuente — la ventana de capas ya no pide UCS")
    reset(); _attr()
    lay = gw.Layer(name="Roca.dxf", kind="litologia",
                   triangles=np.zeros((0, 3, 3)),
                   bbox_min=np.zeros(3), bbox_max=np.zeros(3))
    check(not hasattr(lay, "ucs_lab") or lay.ucs_lab is None,
          "una capa nueva no trae UCS propio", getattr(lay, "ucs_lab", "sin campo"))
    check(not hasattr(gw, "_manual_ucs_for"),
          "y desapareció la sobrescritura manual por capa: era la segunda "
          "verdad para el mismo número")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    la_estadistica_se_elige_desde_el_perfil,
    cada_modo_da_su_numero,
    el_modo_llega_a_los_dominios,
    rango_vs_se_reparte_dentro_de_la_litologia,
    rango_vs_se_sin_banda_no_inventa,
    la_capa_ya_no_pide_ucs,
]


def test_ucs_fuente_unica():
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
    print("✓ UCS FUENTE ÚNICA — todas las verificaciones pasaron.")
    print("=" * 72)
