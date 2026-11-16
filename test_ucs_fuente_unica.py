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
NINGUNA opción construye la etiqueta desde SE. Se probó proyectar la banda
min-max sobre el rango de SE observado —daba una etiqueta por punto y atacaba
el problema de las tres etiquetas para 400.000 registros— y se descartó: SE es
una PREDICTORA y describe la roca. Una caída de SE hace esperar menos
resistencia o más discontinuidades, y eso es justamente lo que se quiere que
el modelo aproveche. Derivar la etiqueta de SE lo obligaría a aprender esa
aritmética en vez de la roca, y a sacar SE de las predictoras. Las dos cosas
son inaceptables.

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
    check(set(p.get("opciones") or []) ==
          {"auto", "central", "media", "mediana", "rango_medio"},
          "y declara sus opciones", p.get("opciones"))
    check(not any("se" == o for o in (p.get("opciones") or [])),
          "ninguna opción construye la etiqueta desde SE: SE es predictora y "
          "describe la roca, derivar la etiqueta de ella la envenenaría",
          p.get("opciones"))
    check("se" in gw.ML_FEATURES,
          "y SE sigue entre las predictoras, sin condiciones", gw.ML_FEATURES)
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
