"""
test_ucs_matriz_no_se_mezcla.py — La tronadura por UCS de matriz ya no se
completa en silencio con la UCS cruda.

LO PEDIDO por el autor, en sus palabras:

  «Otra cosa, que simplifica lo que tenemos es que el UCS que interesa es el
  de Matriz, pues si mezclas ambas cosas, estaríamos viendo otra variable que
  es calidad de roca en general con otra unidad de medida. Por ende, me
  gustaría usar este ucs matriz de Machine Learning para determinar
  tronadura.»

`tronadura_ucs_fuente()` YA elegía "ucs_matriz" por defecto, y `ucs_matriz`
YA es exclusivamente del modelo ML (`predict_all_wells`, el único que la
escribe): arrastra el último `ucs_ml` estable y queda en None en el tramo de
discontinuidad que todavía no tiene un valor estable que arrastrar — un
"sin dato" deliberado, no un error.

EL DEFECTO estaba en `_muestras_bloques()`: cuando un punto no tenía
`ucs_matriz` (ese None deliberado), caía en silencio a `p.ucs_ml` — la
predicción CRUDA, la que SÍ puede venir hundida por la propia
discontinuidad. Eso es exactamente "mezclar ambas cosas" en la misma serie de
números que se interpola y colorea como si fueran una sola variable, y
contradecía la propia documentación de la función ("los puntos sin UCS no se
rellenan con nada"). El punto ahora queda fuera del modelo de bloques y se
cuenta en `sin_ucs`, igual que cualquier punto sin UCS.
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
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _mk_point(este, norte, cota, ucs_ml, ucs_matriz, di=0.4):
    p = gw.MWDPoint(largo=1.0, vel=0.9, pp=200.0, pa=60.0, pd=75.0, pr=45.0,
                    pf=8.0, se=340.0, t=0.0)
    p.este, p.norte, p.cota = este, norte, cota
    p.entrenable = True
    p.dominio = p.lito = "Bht"
    p.di = di
    p.ucs_ml = ucs_ml
    p.ucs_matriz = ucs_matriz
    p.ucs_modelo = "ml"
    return p


def _escenario():
    """Un pozo con tres puntos: uno con matriz estable, uno en discontinuidad
    con matriz=None (todavía sin un valor estable que arrastrar) y otro
    normal — la misma forma en que predict_all_wells() deja el pozo real."""
    reset()
    pts = [
        _mk_point(E0, N0, Z0, ucs_ml=130.0, ucs_matriz=130.0),          # estable
        _mk_point(E0, N0+1, Z0, ucs_ml=40.0, ucs_matriz=None, di=2.5),  # discontinuidad, SIN matriz
        _mk_point(E0, N0+2, Z0, ucs_ml=125.0, ucs_matriz=125.0),        # estable
    ]
    w = gw.Well(well_name="W1", plan_id="CAS_PR01_TH_P01", hole_id="1", points=pts)
    w.caseron = "CAS_A"
    gw.wells["W1"] = w
    gw.domains["Bht"] = {"count": 3, "ucs_lab": 128.1, "atributo_id": "Bht",
                         "alteracion_id": None, "estructura_id": None,
                         "pi_factor": None, "calidad": 1}


# ─────────────────────────────────────────────────────────────────────────────
def el_punto_sin_matriz_no_se_completa_con_ucs_ml():
    section("_muestras_bloques — un punto sin ucs_matriz queda AFUERA, no se rellena")
    _escenario()
    m = gw._muestras_bloques("ucs_matriz")
    check(m["sin_ucs"] == 1,
          "el punto en discontinuidad (ucs_matriz=None) se cuenta como sin UCS",
          m["sin_ucs"])
    check(sorted(m["ucs"].tolist()) == [125.0, 130.0],
          "solo entran los dos puntos con ucs_matriz real — el ucs_ml=40.0 de "
          "la discontinuidad NO aparece mezclado entre ellos", m["ucs"].tolist())


def la_fuente_ucs_ml_no_se_ve_afectada():
    section("_muestras_bloques — la fuente «ucs_ml» sigue trayendo la predicción cruda")
    _escenario()
    m = gw._muestras_bloques("ucs_ml")
    check(m["sin_ucs"] == 0,
          "con fuente ucs_ml todos los puntos tienen valor: nada queda fuera",
          m["sin_ucs"])
    check(sorted(m["ucs"].tolist()) == [40.0, 125.0, 130.0],
          "los tres valores crudos entran, incluido el de la discontinuidad",
          m["ucs"].tolist())


def tronadura_usa_matriz_por_defecto():
    section("Tronadura — la fuente por defecto sigue siendo la UCS de matriz de ML")
    reset()
    check(gw.tronadura_ucs_fuente() == "ucs_matriz",
          "tronadura_ucs_fuente() por defecto es «ucs_matriz», la salida "
          "exclusiva de predict_all_wells() (ML)", gw.tronadura_ucs_fuente())


def interpolate_block_model_hereda_el_mismo_comportamiento():
    section("interpolate_block_model — el modelo de bloques tampoco mezcla")
    _escenario()
    rep = gw.interpolate_block_model(fuente="ucs_matriz", min_muestras=1, min_pozos=1)
    check(rep.get("status") != "error", "corre sin error", rep.get("status"))
    valores = [b["ucs"] for b in rep.get("bloques", []) if b.get("ucs") is not None]
    check(all(abs(v - 40.0) > 1e-6 for v in valores),
          "ningún bloque queda contaminado por el ucs_ml=40.0 de la "
          "discontinuidad sin matriz", valores)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_punto_sin_matriz_no_se_completa_con_ucs_ml,
    la_fuente_ucs_ml_no_se_ve_afectada,
    tronadura_usa_matriz_por_defecto,
    interpolate_block_model_hereda_el_mismo_comportamiento,
]


def test_ucs_matriz_no_se_mezcla():
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
    print("✓ UCS MATRIZ — no se mezcla con ucs_ml — todas las verificaciones pasaron.")
    print("=" * 72)
