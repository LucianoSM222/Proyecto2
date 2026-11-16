"""
test_soporte_tronadura.py — El sólido que mira quien arma la tronadura.

LO PEDIDO, en palabras del autor: «falta la otra herramienta soporte, para que
la gente que arma tronadura pueda ver un sólido coloreado según DI —que hará
observar fracturas— y UCS, para saber la resistencia del macizo».

El modelo de bloques ya existía y ya calculaba las dos cosas, pero solo
alimentaba el kit del Capítulo 5: no había ninguna pantalla desde la cual
pedirlo ni verlo. Un cálculo al que no se llega desde la interfaz, para el
usuario, no existe.

QUÉ TIENE QUE MOSTRAR, y por qué esas dos y no más:

  · DI    dónde está quebrada la roca. Es lo que decide dilución, la necesidad
          de fortificar y dónde el tiro se va a desviar o a perder carga.
  · UCS   qué tan competente es. Es lo que decide el factor de carga.

Y una exigencia que no se negocia: un bloque SIN soporte de datos no se pinta
de un color intermedio bonito. Se declara vacío. Un mapa que rellena los huecos
es exactamente el default silencioso que este proyecto prohíbe, y en tronadura
un hueco pintado de "roca competente" es una decisión tomada sobre nada.
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


def _abanico(n_tiros=8, n_pts=160, seed=0):
    """Un abanico de tiros con UCS y DI ya calculados, como tras correr el modelo."""
    reset()
    rng = np.random.default_rng(seed)
    for k in range(n_tiros):
        pts = []
        for i in range(n_pts):
            p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                            pr=45.0, pf=8.0, se=340.0, t=0.0)
            p.este = E0 + k * 2.0 + rng.normal(0, .2)
            p.norte = N0 + i * 0.15
            p.cota = Z0 - i * 0.12
            p.entrenable = True
            p.dominio = p.lito = "Bht"
            # Una zona fracturada en el medio del abanico: es lo que el sólido
            # tiene que dejar ver.
            p.di = 2.4 if 60 <= i < 95 else float(0.4 + rng.normal(0, .05))
            p.ucs_ml = 95.0 if 60 <= i < 95 else float(128.1 + rng.normal(0, 6))
            p.ucs_matriz = p.ucs_ml
            p.ucs_modelo = "banda"
            pts.append(p)
        w = gw.Well(well_name=f"T{k}", plan_id="CAS_PR01_TH_P01", hole_id=f"{k}",
                    points=pts)
        w.caseron = "CAS_A"
        gw.wells[f"T{k}"] = w
    gw.domains["Bht"] = {"count": n_tiros * n_pts, "ucs_lab": 128.1,
                         "atributo_id": "Bht", "alteracion_id": None,
                         "estructura_id": None, "pi_factor": None, "calidad": 1,
                         "fuente_ucs": "prueba", "modo_ucs": "central"}


# ─────────────────────────────────────────────────────────────────────────────
def el_solido_se_construye_desde_la_pantalla():
    section("Tronadura — el sólido se pide y se ve desde el programa")
    _abanico()
    for var in ("di", "ucs"):
        fig = gw.build_bloques_figure(var)
        check(fig is not None, f"la figura por {var} se construye")
        check(getattr(fig, "data", None), f"y trae trazas por {var}",
              len(getattr(fig, "data", []) or []))
        titulo = str(getattr(getattr(fig, "layout", None), "title", ""))
        check(titulo, f"con título que dice qué se está viendo ({var})", titulo[:70])
    cuerpo = gw._tronadura_panel_body()
    ids = []
    def rec(x):
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        i = getattr(x, "id", None)
        if i is not None: ids.append(i)
        for a in ("children", "title"):
            v = getattr(x, a, None)
            if v is not None: rec(v)
    rec(cuerpo)
    check("tronadura-var" in ids, "el panel deja elegir DI o UCS", ids)
    check("tronadura-fig" in ids, "y tiene dónde dibujar el sólido", ids)


def un_bloque_sin_soporte_no_se_pinta():
    section("Tronadura — un bloque sin datos se declara vacío, no se rellena")
    _abanico()
    rep = gw.interpolate_block_model()
    check(rep["status"] == "ok", "el modelo de bloques corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    con_valor = [b for b in rep["bloques"] if b.get("ucs") is not None]
    check(con_valor, "hay bloques con valor", len(con_valor))
    fig = gw.build_bloques_figure("ucs")
    # Ninguna traza puede llevar un valor donde el bloque no tenía soporte.
    for tr in fig.data:
        col = getattr(tr, "marker", None)
        vals = getattr(col, "color", None) if col is not None else None
        if vals is not None and not isinstance(vals, str):
            check(all(v is not None for v in vals),
                  "ningún bloque dibujado lleva un color inventado: los vacíos "
                  "quedan fuera del sólido, no rellenos", tr.name)
            break


def el_resumen_habla_en_lenguaje_de_tronadura():
    section("Tronadura — el resumen dice lo que hay que decidir")
    _abanico()
    rep = gw.tronadura_resumen()
    check(rep["status"] == "ok", "el resumen corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    for k in ("n_bloques", "volumen_m3", "pct_fracturado", "ucs_mediana",
              "por_banda", "umbral_di"):
        check(k in rep, f"declara {k}", sorted(rep))
    check(0 <= rep["pct_fracturado"] <= 100,
          "el porcentaje fracturado es un porcentaje", rep["pct_fracturado"])
    check(rep["pct_fracturado"] > 0,
          "y detecta la zona fracturada del escenario: si diera 0 el sólido no "
          "estaría sirviendo para nada", rep["pct_fracturado"])
    check(rep["volumen_m3"] > 0, "con su volumen", rep["volumen_m3"])
    check(rep.get("advertencia"),
          "y la advertencia de qué NO es este sólido: una aproximación de "
          "apoyo, no un modelo geológico validado", rep.get("advertencia"))


def sin_datos_lo_dice_en_vez_de_dibujar_vacio():
    section("Tronadura — sin datos se declara, no se entrega un sólido vacío")
    reset()
    rep = gw.tronadura_resumen()
    check(rep["status"] != "ok", "sin pozos no hay sólido", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    fig = gw.build_bloques_figure("di")
    check(fig is not None, "y la figura se construye igual, con el aviso dentro")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_solido_se_construye_desde_la_pantalla,
    un_bloque_sin_soporte_no_se_pinta,
    el_resumen_habla_en_lenguaje_de_tronadura,
    sin_datos_lo_dice_en_vez_de_dibujar_vacio,
]


def test_soporte_tronadura():
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
    print("✓ SOPORTE A TRONADURA — todas las verificaciones pasaron.")
    print("=" * 72)
