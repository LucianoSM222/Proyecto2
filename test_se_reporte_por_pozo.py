"""
test_se_reporte_por_pozo.py — La SE del reporte por pozo deja de aplastarse.

LO PEDIDO: «En los gráficos por pozos que están en las layer debemos permitir
ver los gráficos con los filtros aplicados, o al menos que cuando veamos la SE
se corten los datos sobre 1.000 (bar·min/m), pues eso sucede cuando ROP tiende
a 0 porque el equipo rota el bit para hacer lavado, pero no para perforar y eso
ensucia el dato. Esto ocurre siempre, por ello hay que dejar fuera ese dato.»

Se implementa el mínimo pedido explícitamente: SE_MAX_REPORTE=1000 bar·min/m
como techo FÍSICO —no un percentil, CLAUDE.md prohíbe eso— aplicado en los
tres lugares donde el reporte por pozo muestra SE: el perfil vs. profundidad,
el histograma, y la tabla de estadísticas básicas. No toca `p.se`, no toca
`p.entrenable`, no toca el entrenamiento: es una vista, igual que el recorte
P1-P99 que ya existía, pero DESCARTA el punto en vez de solo mover el rango
del eje — porque un SE de 3,5e11 no es un extremo de la distribución real, es
un artefacto de instrumento.
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


def _punto(largo, se, vel=0.9):
    p = gw.MWDPoint(largo=largo, vel=vel, pp=200.0, pa=60.0, pd=75.0, pr=45.0,
                    pf=8.0, se=se, t=0.0)
    p.entrenable = True
    p.di = 0.5
    p.dominio = "Bht"
    return p


def _pozo_con_artefacto(wn="P0"):
    """
    Un pozo normal con UN registro donde el equipo lava el bit (ROP≈0): la
    SE de ESE registro se dispara. Es exactamente el escenario descrito.
    """
    reset()
    pts = [_punto(i * 0.2, se=300.0 + (i % 7) * 5.0) for i in range(40)]
    # A media profundidad, el equipo lava en vez de perforar: ROP≈0, SE se
    # dispara muy por sobre el techo físico.
    pts[20] = _punto(20 * 0.2, se=1_250_000.0, vel=0.0002)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="CAS_PR01_TH_P01",
                           hole_id=wn, points=pts)
    return pts


# ─────────────────────────────────────────────────────────────────────────────
def el_perfil_deja_un_hueco_no_una_aguja():
    section("Perfil SE vs. profundidad — el artefacto se declara ausente, no se dibuja")
    pts = _pozo_con_artefacto()
    fig = gw.build_well_report_figure("P0", hist_vars=["se"], profile_var="se")
    perfil = fig.data[0]
    check(perfil.y[20] is None,
          "el punto con SE disparada queda en None: un hueco a esa "
          "profundidad, no una línea que sube a 1.250.000 y aplasta la "
          "escala del resto del pozo", perfil.y[20])
    check(perfil.x[20] == pts[20].largo,
          "y el hueco queda en la profundidad REAL del punto, no se corre "
          "ni se omite del eje x", (perfil.x[20], pts[20].largo))
    check(all(v is not None for i, v in enumerate(perfil.y) if i != 20),
          "el resto del perfil sigue completo: no es un descarte general de "
          "SE, es específico al punto que rompe el límite físico")
    check(max(v for v in perfil.y if v is not None) <= gw.SE_MAX_REPORTE,
          "ningún valor dibujado en el perfil supera el techo físico",
          max(v for v in perfil.y if v is not None))


def el_titulo_declara_el_techo_fisico():
    section("Perfil SE — el título dice qué se está aplicando")
    _pozo_con_artefacto()
    fig = gw.build_well_report_figure("P0", hist_vars=["se"], profile_var="se")
    titulo = fig.layout.annotations[0].text if fig.layout.annotations else ""
    check(f"{gw.SE_MAX_REPORTE:g}" in titulo,
          "el título del perfil declara el techo físico aplicado", titulo)


def el_histograma_descarta_el_artefacto_de_verdad():
    section("Histograma de SE — el artefacto no entra, ni disfrazado en el eje")
    pts = _pozo_con_artefacto()
    fig = gw.build_well_report_figure("P0", hist_vars=["se"], profile_var="di")
    hist = [t for t in fig.data if t.type == "histogram"][0]
    check(1_250_000.0 not in hist.x,
          "el valor disparado no está en los datos del histograma")
    check(len(hist.x) == len(pts) - 1,
          "el histograma tiene un punto menos que el pozo: exactamente el "
          "que se descartó por el techo físico", (len(hist.x), len(pts) - 1))
    check(max(hist.x) <= gw.SE_MAX_REPORTE,
          "y el máximo de lo que queda respeta el techo", max(hist.x))


def las_estadisticas_basicas_no_se_contaminan():
    section("well_basic_stats — el máximo de SE no es el artefacto")
    _pozo_con_artefacto()
    stats = gw.well_basic_stats("P0")
    check("se" in stats, "hay estadísticas de SE")
    check(stats["se"]["max"] <= gw.SE_MAX_REPORTE,
          "el máximo reportado está bajo el techo físico, no en el millón: "
          "sin este arreglo la media y la desviación también quedaban "
          "arrastradas por ese único registro", stats["se"]["max"])
    check(stats["se"]["n"] == 39,
          "y el conteo de la variable excluye exactamente el artefacto",
          stats["se"]["n"])


def sin_artefacto_no_cambia_nada():
    section("Regresión — un pozo sin artefactos se ve exactamente igual")
    reset()
    pts = [_punto(i * 0.2, se=300.0 + (i % 7) * 5.0) for i in range(40)]
    gw.wells["P0"] = gw.Well(well_name="P0", plan_id="CAS_PR01_TH_P01",
                             hole_id="P0", points=pts)
    fig = gw.build_well_report_figure("P0", hist_vars=["se"], profile_var="se")
    perfil = fig.data[0]
    check(all(v is not None for v in perfil.y),
          "sin ningún valor sobre el techo, el perfil no pierde ni un punto")
    stats = gw.well_basic_stats("P0")
    check(stats["se"]["n"] == 40, "y las estadísticas cuentan los 40",
          stats["se"]["n"])


def otras_variables_no_se_tocan():
    section("Regresión — el techo es de SE, no de todo el reporte")
    _pozo_con_artefacto()
    fig = gw.build_well_report_figure("P0", hist_vars=["pp"], profile_var="pp")
    perfil = fig.data[0]
    check(all(v is not None for v in perfil.y),
          "el perfil de PP no pierde puntos por el techo de SE: el filtro "
          "es específico a la variable que se dispara")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_perfil_deja_un_hueco_no_una_aguja,
    el_titulo_declara_el_techo_fisico,
    el_histograma_descarta_el_artefacto_de_verdad,
    las_estadisticas_basicas_no_se_contaminan,
    sin_artefacto_no_cambia_nada,
    otras_variables_no_se_tocan,
]


def test_se_reporte_por_pozo():
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
    print("✓ SE EN REPORTE POR POZO — todas las verificaciones pasaron.")
    print("=" * 72)
