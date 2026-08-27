"""
test_di_activo.py — La convención del DI no se puede pisar por la puerta de atrás.

EL DEFECTO QUE ESTE TEST EXISTE PARA IMPEDIR: el panel del DI escribía directo
sobre di_config y di_threshold, que son la convención de Fernández. Las dos
protecciones construidas —el parámetro protegido del perfil y la variante de
solo lectura— las esquivaba por completo, así que eran decorativas:

    di_config["weights"] = {...}      # la convención, sobrescrita
    di_threshold = 2.5

Después de eso el DI corría con 2,5 mientras el parámetro protegido y la
variante de convención seguían diciendo 1,5. Dos fuentes de verdad mintiendo, y
todo reporte citando a Fernández con pesos que no eran los suyos.

LA SALIDA: hay un DI ACTIVO. Por defecto es la convención. Cambiar parámetros
crea o actualiza una VARIANTE y la activa; la convención nunca se toca, y el
programa declara siempre con cuál está corriendo.
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


def _pozo(wn="W1", n=400, seed=0):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * 0.02,
                        vel=float(0.9 + rng.normal(0, 0.01)),
                        pp=float(200.0 + rng.normal(0, 1.5)),
                        pa=float(60.0 + rng.normal(0, 0.8)),
                        pd=float(75.0 + rng.normal(0, 0.8)),
                        pr=float(45.0 + rng.normal(0, 0.6)),
                        pf=float(8.0 + rng.normal(0, 0.1)),
                        se=340.0, t=0.0)
        p.este = 376700.0; p.norte = 6959000.0; p.cota = 300.0 - i * 0.02
        p.entrenable = True; p.dominio = p.lito = "Bht"
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


# ─────────────────────────────────────────────────────────────────────────────
def por_defecto_corre_la_convencion():
    section("DI activo — al arrancar corre la convención")
    reset()
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "el DI activo es el de convención", gw.di_activo())
    check(gw.di_config_is_default(), "y la configuración es la suya",
          gw.di_config_summary())
    check(gw.DI_VARIANTE_CONVENCION in gw.di_config_summary(),
          "el resumen declara con cuál se está corriendo",
          gw.di_config_summary())


def cambiar_parametros_crea_una_variante():
    section("DI activo — cambiar parámetros crea una VARIANTE, no pisa la convención")
    reset()
    nombre = gw.aplicar_di_config(window=20, threshold=2.5,
                                  weights={"pp": 0.9, "pd": 0.1, "pf": 0.0, "pr": 0.0})
    check(nombre and nombre != gw.DI_VARIANTE_CONVENCION,
          "la operación devuelve el nombre de la variante creada", nombre)
    conv = gw.di_variant(gw.DI_VARIANTE_CONVENCION)
    check(conv["threshold"] == 1.5 and conv["window"] == 14,
          "la convención queda INTACTA", (conv["window"], conv["threshold"]))
    check(conv["weights"] == {"pp": 0.35, "pr": 0.20, "pd": 0.25, "pf": 0.20},
          "con sus pesos de Fernández", conv["weights"])
    check(gw.di_activo() == nombre, "y el DI activo pasa a ser la variante",
          gw.di_activo())
    check(gw.di_threshold == 2.5 and gw.di_config["window"] == 20,
          "que es la que efectivamente corre",
          (gw.di_config["window"], gw.di_threshold))
    check(not gw.di_config_is_default(),
          "di_config_is_default() dice que NO se está en convención")
    check(nombre in gw.di_config_summary(),
          "y el resumen nombra la variante activa", gw.di_config_summary())


def volver_a_la_convencion():
    section("DI activo — se puede volver a la convención")
    reset()
    gw.aplicar_di_config(window=20, threshold=2.5,
                         weights={"pp": 1.0, "pd": 0.0, "pf": 0.0, "pr": 0.0})
    gw.activar_di(gw.DI_VARIANTE_CONVENCION)
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION, "vuelve", gw.di_activo())
    check(gw.di_config_is_default(),
          "y la configuración vigente es exactamente la de convención",
          gw.di_config_summary())
    check(gw.di_threshold == 1.5 and gw.di_config["window"] == 14,
          "ventana 14 y umbral 1,5", (gw.di_config["window"], gw.di_threshold))


def activar_una_variante_inexistente_falla():
    section("DI activo — activar algo que no existe se rechaza")
    reset()
    try:
        gw.activar_di("no_existe")
        check(False, "tenía que fallar")
    except KeyError:
        check(True, "se rechaza con KeyError")
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "y el activo no cambia", gw.di_activo())


def la_variante_calibrada_se_puede_activar():
    section("DI activo — una variante calibrada se activa como cualquier otra")
    reset()
    gw.create_di_variant("calibrada", weights={"pd": 0.8, "pp": 0.2},
                         window=14, threshold=1.2, fuente="calibración de prueba")
    gw.activar_di("calibrada")
    check(gw.di_activo() == "calibrada", "queda activa", gw.di_activo())
    check(gw.di_threshold == 1.2, "con su umbral", gw.di_threshold)
    check(set(gw.di_config["params"]) == {"pd", "pp"},
          "y con sus parámetros, no los de la convención", gw.di_config["params"])
    # Y el DI que se calcula es el de ESA variante.
    _pozo()
    gw.compute_di()
    di_var = [p.di for p in gw.wells["W1"].points]
    gw.activar_di(gw.DI_VARIANTE_CONVENCION)
    gw.compute_di()
    di_conv = [p.di for p in gw.wells["W1"].points]
    check(not np.allclose(np.array(di_var), np.array(di_conv)),
          "y da un perfil distinto al de convención")


def borrar_la_variante_activa_devuelve_a_la_convencion():
    section("DI activo — borrar la variante activa no deja el DI en el limbo")
    reset()
    gw.create_di_variant("temporal", weights={"pd": 1.0}, threshold=1.1)
    gw.activar_di("temporal")
    check(gw.di_activo() == "temporal", "activa")
    gw.delete_di_variant("temporal")
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "al borrarla, el DI vuelve a la convención en vez de quedar apuntando "
          "a algo que ya no existe", gw.di_activo())
    check(gw.di_threshold == 1.5, "con su umbral restituido", gw.di_threshold)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    por_defecto_corre_la_convencion,
    cambiar_parametros_crea_una_variante,
    volver_a_la_convencion,
    activar_una_variante_inexistente_falla,
    la_variante_calibrada_se_puede_activar,
    borrar_la_variante_activa_devuelve_a_la_convencion,
]


def test_di_activo():
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
    print("✓ DI ACTIVO — todas las verificaciones pasaron.")
    print("=" * 72)
