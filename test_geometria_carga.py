"""
test_geometria_carga.py — Corrección de la geometría de carga de pozos.

TRES DEFECTOS MEDIDOS SOBRE LOS DATOS REALES, no supuestos:

  A. ESTIRAMIENTO. Los puntos se colocaban por parámetro normalizado
     t = largo/largo_max e interpolando entre collar y final. Cuando el MWD
     deja de registrar antes del fondo, los metros medidos se estiran sobre
     todo el tiro. Medido: 20 pozos con más de 1 m de estiramiento, hasta
     1,65 m sobre tiros de 35 m. Con bloques de 2,5 m eso desplaza un punto
     casi un bloque entero. La colocación correcta es a la profundidad
     REALMENTE medida sobre la dirección del tiro.

  B. TRASLAPE. Los pozos sin DQ recibían posición ficticia en el centro
     global. Medido: 16 pozos apilados TODOS sobre la misma vertical
     (E 377.541,6 · N 6.958.022,8). Eso es el traslape que se ve en la vista
     3D. Un pozo sin posición no es un pozo: se descarta y se declara.

  C. POZOS SIN REGISTRO ÚTIL. Medido: cuatro pozos con menos de 1,5 m de
     registro, uno con 3 muestras y 7 cm. Un pozo así, colocado entre collar
     y final, se ve como "el collar y una sola medición a lo lejos".

Y la salida para el caso intermedio: cuando no hay collar exacto pero SÍ hay
candidatos, una sola decisión al cargar —¿asignar el más cercano? ¿hasta qué
error?— y la asignación se hace de menor a mayor error hasta agotar los que
caen dentro de la tolerancia.
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
    gw.global_center = None


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _mw(plan, hole, largo_max, n, paso=None):
    """Resultado de parse_mw sintético: n muestras hasta largo_max."""
    paso = paso if paso is not None else (largo_max / max(n - 1, 1))
    pts = []
    for i in range(n):
        lt = min(i * paso, largo_max)
        p = gw.MWDPoint(largo=lt, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        pts.append(p)
    lm = max(p.largo for p in pts)
    for p in pts:
        p.t = p.largo / lm if lm > 0 else 0.0
    return {"plan_id": plan, "hole_id": hole, "largo_max": lm, "puntos": pts}


def _dq(plan, hole, collar, final):
    lu = lambda e, n, z: {"este": e, "norte": n, "cota": z}
    return {plan: {"tiros": {hole: {"collar": lu(*collar), "final_pt": lu(*final)}}}}


# ─────────────────────────────────────────────────────────────────────────────
def a_no_se_estira_el_registro():
    section("A — Los puntos van a su profundidad REAL, no estirados al tiro")
    reset()
    # El caso REAL medido en PCC_0042_PR03_TH_P56_H11: tiro de 35,16 m y
    # registro que llega a 33,52 m. El error de coherencia es 4,9%, dentro del
    # 5% que exige el match, así que el pozo se carga — y ahí es donde el
    # estiramiento pasaba inadvertido.
    dq = _dq("P01", "1", (E0, N0, Z0), (E0, N0, Z0 - 35.16))
    mw = {"P01_H1": [_mw("P01", "1", largo_max=33.52, n=1677)]}
    gw.match_and_place_wells(dq, mw)
    check("P01_H1" in gw.wells, "el pozo se carga", list(gw.wells))
    if "P01_H1" not in gw.wells:
        return
    w = gw.wells["P01_H1"]
    ultimo = max(w.points, key=lambda p: p.largo)
    prof = Z0 - ultimo.cota
    check(abs(prof - 33.52) < 0.02,
          "el último punto queda a los 33,52 m REALMENTE medidos, no a los 35,16 "
          "del tiro", f"{prof:.3f} m")
    # Y el paso en el espacio coincide con el paso en profundidad.
    ordenados = sorted(w.points, key=lambda p: p.largo)
    d3d = np.linalg.norm(
        np.array([ordenados[1].este - ordenados[0].este,
                  ordenados[1].norte - ordenados[0].norte,
                  ordenados[1].cota - ordenados[0].cota]))
    dlargo = ordenados[1].largo - ordenados[0].largo
    check(abs(d3d - dlargo) < 1e-6,
          "el paso en el espacio es igual al paso en profundidad",
          (d3d, dlargo))


def a_registro_completo_no_cambia():
    section("A — Cuando el registro llega al fondo, nada cambia")
    reset()
    dq = _dq("P01", "1", (E0, N0, Z0), (E0 + 21.0, N0, Z0 - 28.0))   # 35 m
    mw = {"P01_H1": [_mw("P01", "1", largo_max=35.0, n=351)]}
    gw.match_and_place_wells(dq, mw)
    w = gw.wells["P01_H1"]
    ultimo = max(w.points, key=lambda p: p.largo)
    d = np.linalg.norm(np.array([ultimo.este - E0, ultimo.norte - N0,
                                 ultimo.cota - Z0]))
    check(abs(d - 35.0) < 0.02,
          "el último punto cae en el fondo del tiro", f"{d:.3f} m")


def b_sin_posicion_se_descarta():
    section("B — Un pozo sin posición se DESCARTA, no se apila en el centro")
    reset()
    # Dos pozos sin ningún DQ que los explique.
    mw = {"X_H1": [_mw("PX", "1", 30.0, 301)],
          "Y_H1": [_mw("PY", "1", 30.0, 301)]}
    counts = gw.match_and_place_wells({}, mw)
    check(len(gw.wells) == 0,
          "ninguno se carga: sin collar no hay pozo", list(gw.wells))
    check(counts.get("descartados_sin_posicion") == 2,
          "y los dos se cuentan como descartados",
          counts.get("descartados_sin_posicion"))
    check(counts.get("descartados"), "con el detalle de cuáles y por qué",
          counts.get("descartados"))


def b_ambiguo_sin_tolerancia_se_descarta():
    section("B — Ambiguo y sin tolerancia declarada: también se descarta")
    reset()
    # El DQ existe pero su largo no coincide: 35 m de tiro contra 10 m de MWD.
    dq = _dq("P01", "1", (E0, N0, Z0), (E0, N0, Z0 - 35.0))
    mw = {"P01_H1": [_mw("P01", "1", largo_max=10.0, n=101)]}
    counts = gw.match_and_place_wells(dq, mw, asignar_por_tolerancia=False)
    check(len(gw.wells) == 0, "no se carga", list(gw.wells))
    check(counts.get("descartados_sin_posicion") == 1,
          "se cuenta como descartado", counts)


def c_tolerancia_asigna_de_menor_a_mayor_error():
    section("C — Con tolerancia: se asigna de menor a mayor error")
    reset()
    # Tres candidatos con el mismo hole_id y errores crecientes, TODOS por
    # encima del 5% de la coherencia estricta: 8% · 20% · 50%. Así la decisión
    # la toma la tolerancia y no el match exacto.
    lu = lambda e, n, z: {"este": e, "norte": n, "cota": z}
    dq = {
        "PA": {"tiros": {"1": {"collar": lu(E0, N0, Z0),
                               "final_pt": lu(E0, N0, Z0 - 32.4)}}},
        "PB": {"tiros": {"1": {"collar": lu(E0 + 5, N0, Z0),
                               "final_pt": lu(E0 + 5, N0, Z0 - 36.0)}}},
        "PC": {"tiros": {"1": {"collar": lu(E0 + 9, N0, Z0),
                               "final_pt": lu(E0 + 9, N0, Z0 - 45.0)}}},
    }
    mw = {"PZ_H1": [_mw("PZ", "1", largo_max=30.0, n=301)]}
    counts = gw.match_and_place_wells(dq, mw, asignar_por_tolerancia=True,
                                      tolerancia_err_pct=15.0)
    check("PZ_H1" in gw.wells, "con tolerancia 15% el pozo SÍ se carga",
          list(gw.wells))
    if "PZ_H1" in gw.wells:
        w = gw.wells["PZ_H1"]
        check(abs(w.collar["este"] - E0) < 1e-6,
              "y toma el candidato de MENOR error, no el primero de la lista",
              w.collar)
        check(w.origin == "tolerancia",
              "declarando que se asignó por tolerancia", w.origin)
        check(w.asignacion_err_pct is not None and w.asignacion_err_pct < 15.0,
              "con el error de esa asignación registrado", w.asignacion_err_pct)

    # Con una tolerancia bajo el error del mejor candidato, ninguno alcanza.
    reset()
    counts = gw.match_and_place_wells(dq, mw, asignar_por_tolerancia=True,
                                      tolerancia_err_pct=5.5)
    check(len(gw.wells) == 0,
          "y con una tolerancia más apretada que todos los errores, se descarta",
          list(gw.wells))


def d_pozo_sin_registro_util_se_descarta():
    section("D — Un pozo con registro despreciable se descarta")
    reset()
    dq = _dq("P01", "1", (E0, N0, Z0), (E0, N0, Z0 - 35.0))
    # 3 muestras en 7 cm: es lo que se veía como "el collar y un punto lejos".
    mw = {"P01_H1": [_mw("P01", "1", largo_max=0.07, n=3)]}
    counts = gw.match_and_place_wells(dq, mw)
    check(len(gw.wells) == 0, "no se carga", list(gw.wells))
    check(counts.get("descartados_sin_registro") == 1,
          "se cuenta aparte de los que no tienen posición", counts)
    check(gw.get_param("carga.largo_min_m") == 1.0,
          "el mínimo es un parámetro del perfil, no un número enterrado",
          gw.get_param("carga.largo_min_m"))
    # Bajando el mínimo, un pozo corto PERO COHERENTE entra: la decisión es
    # configurable, y sigue exigiendo que el DQ concuerde con el registro.
    reset()
    gw.set_param("carga.largo_min_m", 0.01)
    dq_corto = _dq("P02", "1", (E0, N0, Z0), (E0, N0, Z0 - 0.07))
    mw_corto = {"P02_H1": [_mw("P02", "1", largo_max=0.07, n=3)]}
    gw.match_and_place_wells(dq_corto, mw_corto)
    check(len(gw.wells) == 1, "con el mínimo bajado sí entra", list(gw.wells))
    gw.seed_param_registry(force=True)


def e_todo_descarte_queda_declarado():
    section("E — Nada se descarta en silencio")
    reset()
    dq = _dq("P01", "1", (E0, N0, Z0), (E0, N0, Z0 - 35.0))
    mw = {"P01_H1": [_mw("P01", "1", largo_max=35.0, n=351)],   # bueno
          "P01_H9": [_mw("P01", "9", largo_max=0.05, n=3)],     # sin registro
          "ZZ_H1": [_mw("ZZ", "1", largo_max=30.0, n=301)]}     # sin DQ
    counts = gw.match_and_place_wells(dq, mw)
    check(len(gw.wells) == 1, "solo entra el bueno", list(gw.wells))
    desc = counts.get("descartados") or []
    check(len(desc) == 2, "los dos descartes se listan", desc)
    check(all(d.get("motivo") for d in desc),
          "cada uno con su motivo", desc)
    check({d["pozo"] for d in desc} == {"P01_H9", "ZZ_H1"},
          "y nombrados uno por uno", [d["pozo"] for d in desc])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    a_no_se_estira_el_registro,
    a_registro_completo_no_cambia,
    b_sin_posicion_se_descarta,
    b_ambiguo_sin_tolerancia_se_descarta,
    c_tolerancia_asigna_de_menor_a_mayor_error,
    d_pozo_sin_registro_util_se_descarta,
    e_todo_descarte_queda_declarado,
]


def test_geometria_carga():
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
    print("✓ GEOMETRÍA DE CARGA — todas las verificaciones pasaron.")
    print("=" * 72)
