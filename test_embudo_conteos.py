"""
test_embudo_conteos.py — El embudo cuenta sin armar la matriz de entrenamiento.

LO PEDIDO, en palabras del autor: «en general el programa es lento».

Medido a escala real —1.050.000 puntos en 600 pozos, que es el orden de los
cuatro caserones— abrir el Paso 4 tardaba 9,4 s. De esos, 5,4 s eran
`training_composition_report()`, que llama al embudo, y el embudo ARMABA LA
MATRIZ DE ENTRENAMIENTO ENTERA —X, y, groups, un millón de filas— para que la
tarjeta mostrara nueve números. Otros 1,4 s eran un `list(all_points())` que
nadie leía.

Lo que este test fija:

  1. Los conteos con y sin matriz son EXACTAMENTE los mismos. La bandera es
     una optimización, no otra manera de contar: si cambiara un solo número,
     la tarjeta y el entrenamiento estarían contando cosas distintas y el
     embudo dejaría de explicar el N del modelo.

  2. LA PROCEDENCIA NO SE BORRA. El pase de conteos limpiaba `_prov_capas` y
     no la volvía a llenar, así que abrir el Paso 4 dejaba a la guardia de
     circularidad sin saber de qué mallas salieron las etiquetas —y esa
     guardia calla cuando no sabe—. Habría desarmado en silencio la
     protección, que es justo lo que este proyecto prohíbe.
"""

import os, sys, time

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
    gw._prov_capas.clear(); gw._prov_caserones.clear(); gw._prov_ucs.clear()


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _escenario(n_pozos=6, n_pts=150, seed=0):
    """Pozos con puntos que caen a distintas alturas del embudo."""
    reset()
    rng = np.random.default_rng(seed)
    for k in range(n_pozos):
        pts = []
        for i in range(n_pts):
            p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                            pr=45.0, pf=8.0, se=340.0, t=0.0)
            p.este = E0 + k * 2.0
            p.norte = N0 + i * 0.15
            p.cota = Z0 - i * 0.12
            # Un reparto que hace perder puntos en varias etapas distintas,
            # que es donde una optimización mal hecha se notaría.
            p.entrenable = (i % 10) != 0
            p.dominio = p.lito = ("Bht" if i % 3 else ("Kpcli" if i % 7 else None))
            p.capa_lito = f"malla_{p.dominio}" if p.dominio else None
            p.ambiguo = (i % 23 == 0)
            p.di = 2.4 if i % 17 == 0 else 0.4
            pts.append(p)
        w = gw.Well(well_name=f"T{k}", plan_id="CAS_PR01_TH_P01", hole_id=f"{k}",
                    points=pts)
        w.caseron = "CAS_A"
        gw.wells[f"T{k}"] = w
    for lito, ucs in (("Bht", 128.1), ("Kpcli", 180.0)):
        gw.domains[lito] = {"count": 1, "ucs_lab": ucs, "atributo_id": lito,
                            "alteracion_id": None, "estructura_id": None,
                            "pi_factor": None, "calidad": 1,
                            "fuente_ucs": "prueba", "modo_ucs": "central"}


# ─────────────────────────────────────────────────────────────────────────────
def los_conteos_son_identicos():
    section("Embudo — contar sin la matriz da EXACTAMENTE lo mismo")
    _escenario()
    lo, hi = gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"]
    X, y, g, n_excl, f_completo = gw._training_funnel(lo, hi)
    Xc, yc, gc, n_excl_c, f_conteos = gw._training_funnel(lo, hi, solo_conteos=True)

    check(len(f_completo) == len(f_conteos), "el embudo tiene las mismas etapas",
          (len(f_completo), len(f_conteos)))
    for a, b in zip(f_completo, f_conteos):
        check(a["etapa"] == b["etapa"] and a["quedan"] == b["quedan"]
              and a["perdidos"] == b["perdidos"],
              f'la etapa «{a["etapa"]}» cuenta igual',
              (a["quedan"], b["quedan"]))
    check(n_excl == n_excl_c, "y los excluidos por DI también", (n_excl, n_excl_c))
    check(f_completo[-1]["quedan"] == len(X),
          "el último escalón del embudo es exactamente el N del entrenamiento: "
          "si no, la tarjeta no estaría explicando el número del modelo",
          (f_completo[-1]["quedan"], len(X)))
    check(len(Xc) == 0 and len(yc) == 0 and len(gc) == 0,
          "en modo conteos la matriz viene vacía, que es todo el punto",
          (len(Xc), len(yc), len(gc)))


def la_procedencia_no_se_borra():
    section("Embudo — contar NO desarma la guardia de circularidad")
    _escenario()
    lo, hi = gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"]
    gw._training_funnel(lo, hi)                       # pase completo: la llena
    capas = set(gw._prov_capas)
    caserones = set(gw._prov_caserones)
    ucs = set(gw._prov_ucs)
    check(capas, "el pase completo registra de qué mallas salieron las etiquetas",
          sorted(capas))
    check(caserones, "y de qué caserones", sorted(caserones))

    gw.training_composition_report()                  # el que abre el Paso 4
    check(set(gw._prov_capas) == capas,
          "abrir la tarjeta del embudo NO borra las mallas de procedencia: si "
          "las borrara, la guardia de circularidad se quedaría sin saber y las "
          "guardias que no saben, callan", sorted(gw._prov_capas))
    check(set(gw._prov_caserones) == caserones,
          "ni los caserones", sorted(gw._prov_caserones))
    check(set(gw._prov_ucs) == ucs, "ni las etiquetas de UCS", sorted(gw._prov_ucs))


def el_reporte_sigue_diciendo_lo_mismo():
    section("Embudo — el reporte que ve el usuario no cambió")
    _escenario()
    rep = gw.training_composition_report()
    check(rep["funnel"], "el reporte trae el embudo", len(rep["funnel"]))
    check(rep["n_total"] == sum(len(w.points) for w in gw.wells.values()),
          "el total es el total de puntos MWD", rep["n_total"])
    check(rep["n_final"] == rep["funnel"][-1]["quedan"],
          "y el final es el último escalón", (rep["n_final"],))
    check(all(st.get("label") for st in rep["funnel"]),
          "cada etapa dice POR QUÉ se perdieron puntos, no solo cuántos")
    tarjeta = gw._training_composition_card()
    check(tarjeta is not None, "y la tarjeta se arma")


def abrir_el_paso4_no_recorre_el_millon_dos_veces():
    section("Embudo — el Paso 4 dejó de materializar puntos que no usa")
    _escenario(n_pozos=40, n_pts=900)
    n = sum(len(w.points) for w in gw.wells.values())
    t = time.time()
    gw._step4()
    dt_step4 = time.time() - t
    t = time.time()
    gw.training_composition_report()
    dt_rep = time.time() - t
    print(f"      ({n:,} puntos · _step4 {dt_step4*1000:.0f} ms · "
          f"embudo {dt_rep*1000:.0f} ms)".replace(",", "."))
    # El Paso 4 no puede costar mucho más que su propio embudo: lo que sobraba
    # era un list(all_points()) que nadie leía.
    check(dt_step4 < dt_rep * 2.5 + 0.25,
          "abrir el Paso 4 cuesta lo que cuesta su embudo, no el doble por "
          "materializar una lista que se tira",
          f"step4 {dt_step4:.3f}s vs embudo {dt_rep:.3f}s")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    los_conteos_son_identicos,
    la_procedencia_no_se_borra,
    el_reporte_sigue_diciendo_lo_mismo,
    abrir_el_paso4_no_recorre_el_millon_dos_veces,
]


def test_embudo_conteos():
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
    print("✓ EMBUDO DE ENTRENAMIENTO — todas las verificaciones pasaron.")
    print("=" * 72)
