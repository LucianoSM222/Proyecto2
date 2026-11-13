"""
test_nombres_definidos.py — Ninguna línea llama a algo que ya no existe.

EL DEFECTO QUE ORIGINA ESTA SUITE, reportado por el autor: «me aparece 1
error, apply_layer_band no está definida en la línea 13552».

Tenía razón, y no era el primero. Al sacar el Excel geomecánico del programa
(commit 16653fa) se borró la función que autocompletaba la banda de UCS de una
capa, pero la línea que la LLAMABA se quedó. El resultado: asignar un caserón
o un alias de litología en el árbol de capas —una acción normal— reventaba con
NameError. Y en el mismo commit se fue `on_xml`, que dejó muerta la carga de
MWD entera. Dos veces la misma forma de fallar.

POR QUÉ LOS TESTS NO LO VIERON. Python resuelve los nombres al EJECUTAR, no al
importar: un archivo con una llamada a una función inexistente importa sin
quejarse, arranca sin quejarse, y solo revienta cuando alguien pasa por esa
línea. Las suites cubren lo que ejercitan, y ninguna hacía clic en ese
dropdown. Con 15.000 líneas y callbacks que solo corren desde la interfaz, eso
no se arregla escribiendo más tests: se arregla mirando el código, que es lo
que hace esta suite.

Este test recorre TODOS los .py del proyecto y falla si alguno usa un nombre
que no está definido en ninguna parte. Es barato, no ejecuta nada, y cubre
justo el hueco que dejan los tests de comportamiento.
"""

import os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from test_support import skip

FAILURES = []


def check(cond, label, detail=""):
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}" + (f"  → {detail}" if detail else ""))
        FAILURES.append(label)


def section(t):
    print(f"\n{'='*72}\n{t}\n{'='*72}")


def _archivos():
    return sorted(f for f in os.listdir(HERE)
                  if f.endswith(".py") and not f.startswith("."))


def _pyflakes(archivos):
    """
    (salida, disponible). pyflakes hace el análisis de alcances bien —
    comprensiones, walrus, nonlocal, alcance de clase, alias de except— y
    reimplementarlo a mano sería cambiar un defecto por otro más difícil de
    ver.
    """
    try:
        r = subprocess.run([sys.executable, "-m", "pyflakes", *archivos],
                           cwd=HERE, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return "", False
    if r.returncode not in (0, 1) and "No module named" in (r.stderr or ""):
        return "", False
    if "No module named pyflakes" in (r.stderr or ""):
        return "", False
    return r.stdout or "", True


# ─────────────────────────────────────────────────────────────────────────────
def ningun_nombre_sin_definir():
    section("Nombres — nada llama a algo que no existe")
    archivos = _archivos()
    check(len(archivos) > 10, "hay archivos que revisar", len(archivos))
    salida, ok = _pyflakes(archivos)
    if not ok:
        skip("pyflakes no está instalado (pip install pyflakes). Sin él este "
             "chequeo no puede correr, y omitirlo es más honesto que pasarlo.")
    indefinidos = [l for l in salida.splitlines() if "undefined name" in l]
    check(not indefinidos,
          "ningún archivo usa un nombre que no está definido: es el defecto "
          "que dejó muerta la carga de MWD y reventaba el árbol de capas, y "
          "Python no lo delata hasta que alguien pasa por esa línea",
          "\n      " + "\n      ".join(indefinidos))


def el_chequeo_detecta_de_verdad():
    """
    Un test que solo mira que no haya hallazgos pasa igual si el chequeo está
    roto y no mira nada. Se le da un archivo con el defecto A PROPÓSITO y se
    verifica que lo encuentre.
    """
    section("Nombres — el chequeo encuentra el defecto cuando está")
    import tempfile
    veneno = ("def f():\n"
              "    return apply_layer_band(1)\n")
    ruta = os.path.join(HERE, "_canario_nombres_tmp.py")
    with open(ruta, "w") as fh:
        fh.write(veneno)
    try:
        salida, ok = _pyflakes([os.path.basename(ruta)])
        if not ok:
            skip("pyflakes no está instalado.")
        check("undefined name" in salida,
              "un archivo con una llamada a una función inexistente SÍ se "
              "detecta: si no, este test estaría pasando por no mirar nada",
              salida.strip()[:120])
        check("apply_layer_band" in salida,
              "y nombra cuál es", salida.strip()[:120])
    finally:
        os.unlink(ruta)


def asignar_caseron_a_una_capa_no_revienta():
    """
    El caso concreto que lo destapó: la línea 13552 llamaba a
    apply_layer_band(), que se fue con el Excel geomecánico. El análisis
    estático ya no encuentra el nombre suelto, pero eso solo prueba que la
    línea no está: acá se ejecuta el callback para probar que además FUNCIONA.
    """
    section("Nombres — asignar caserón desde el árbol de capas corre de verdad")
    import numpy as np
    import geomech_wizard as gw

    gw.layers.clear()
    gw.layers["Bht_malla"] = gw.Layer(
        name="Bht_malla", kind="mesh", triangles=np.zeros((1, 3, 3)),
        bbox_min=np.zeros(3), bbox_max=np.ones(3))

    class _Ctx:
        triggered = [{"prop_id": "caseron-sel", "value": "CAS_A"}]
    ctx_real = gw.callback_context
    gw.callback_context = _Ctx()
    try:
        salida = gw.on_layer_meta(["CAS_A"], ["Bht"],
                                  [{"index": "Bht_malla"}],
                                  [{"index": "Bht_malla"}], 0)
    except NameError as e:
        gw.callback_context = ctx_real
        check(False, "asignar caserón y alias no revienta", f"NameError: {e}")
        gw.layers.clear()
        return
    finally:
        gw.callback_context = ctx_real
    check(len(salida) == 3, "el callback devuelve sus tres salidas", salida)
    check(gw.layers["Bht_malla"].caseron == "CAS_A",
          "y el caserón queda asignado", gw.layers["Bht_malla"].caseron)
    check(gw.layers["Bht_malla"].lito_alias == "Bht",
          "y el alias de litología también", gw.layers["Bht_malla"].lito_alias)
    check("anda" not in str(salida[1]).lower(),
          "el aviso ya no promete una banda autocompletada: la banda es del "
          "ATRIBUTO y este paso no la toca", salida[1])
    gw.layers.clear()


def el_runner_de_cada_suite_nombra_tests_que_existen():
    """
    El bloque `if __name__ == "__main__"` de cada suite lista sus tests por
    nombre. Si uno se borra y la lista no, `python3 test_x.py` revienta —y
    bajo pytest ese bloque no corre, así que la suite sigue verde mintiendo.
    Es exactamente lo que pasaba en test_geomech.py con los tres tests del
    Excel geomecánico.
    """
    section("Nombres — los runners no listan tests borrados")
    salida, ok = _pyflakes(_archivos())
    if not ok:
        skip("pyflakes no está instalado.")
    indefinidos = [l for l in salida.splitlines()
                   if "undefined name" in l and "test_" in l]
    check(not indefinidos,
          "ningún runner nombra un test que ya no existe",
          "\n      " + "\n      ".join(indefinidos))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    ningun_nombre_sin_definir,
    el_chequeo_detecta_de_verdad,
    asignar_caseron_a_una_capa_no_revienta,
    el_runner_de_cada_suite_nombra_tests_que_existen,
]


def test_nombres_definidos():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    for t in ALL_TESTS:
        t()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    for t in ALL_TESTS:
        t()
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ NOMBRES DEFINIDOS — todas las verificaciones pasaron.")
    print("=" * 72)
