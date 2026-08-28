"""
test_golpe_de_barra.py — El "golpe de barra" deja de ensuciar el DI y el ML.

LO REPORTADO: «vi que en el PP hay caídas rápidas y luego vuelve, esa corta
bajada igual hay que eliminarla pues cuando el equipo agrega otra barra al
empezar hace 1 primer golpe (o sea 1 sola medición) de ajuste y vuelve, pero
en la predicción ML hace una caída que nos dispersa y nos baja la
confiabilidad […] y creo que vi en la configuración una parte que era para
descartar tramos donde la PP tiene variación, como podría configurarla si es
que existe.»

LA PARTE QUE EL USUARIO RECORDABA es `clean_filters` (Paso 2): existía, pero
sus cuatro métodos son percentiles GLOBALES sobre toda la distribución de una
variable — exactamente lo que CLAUDE.md prohíbe usar como criterio de
etiquetado ("Filtrado por percentiles prohibido. Solo límites físicos y
criterios trazables"). Un percentil global no sirve para esto: o no llega a
marcar el golpe (si no es extremo frente a TODA la distribución) o se lleva
por delante PP bajo legítimo de otro sector del pozo.

LO NUEVO es `detectar_golpes_de_barra`: un criterio LOCAL y trazable, no un
percentil. Para cada muestra interior de un pozo (ordenado por profundidad)
mira sus dos vecinas inmediatas. La marca solo si (a) la muestra cae bajo una
fracción del promedio de sus vecinas — `pp.golpe_barra_caida_rel`, parámetro
del perfil, nunca un default silencioso — Y (b) esas dos vecinas son
parecidas ENTRE SÍ, la firma de "cae y se recupera". Una caída sostenida de
varias muestras, o una vecina que no vuelve al nivel anterior, es información
real de la roca y no cumple (b): no se marca. Se integra al MISMO listado de
`clean_filters` que el usuario ya conocía —mismo botón de quitar, mismo
`recompute_filters()`— como un método más del selector, «Golpe de barra».
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
    gw.clean_filters.clear()
    gw.inicio_cut_m = 2.0


def _mk_point(largo, pp):
    return gw.MWDPoint(largo=largo, vel=1.0, pp=pp, pa=60.0, pd=75.0, pr=40.0,
                       pf=8.0, se=(pp+40.0+60.0)/1.0, t=0.0)


def _mk_well(name, pps, largo0=5.0, paso=0.02):
    pts = [_mk_point(largo0 + i*paso, pp) for i, pp in enumerate(pps)]
    w = gw.Well(well_name=name, plan_id=f"CAS_PR01_TH_{name}", hole_id=name, points=pts)
    w.caseron = "CAS_A"
    gw.wells[name] = w
    return w


# ─────────────────────────────────────────────────────────────────────────────
def marca_la_caida_de_una_sola_muestra_que_se_recupera():
    section("Detector — cae y se recupera en la muestra siguiente: SÍ se marca")
    reset()
    # 150 estable, un golpe de barra a 90 (40% de caída), vuelve a 150.
    pps = [150.0]*5 + [90.0] + [150.0]*5
    idxs = gw.detectar_golpes_de_barra(_mk_well("W1", pps).points, caida_rel=0.30)
    check(idxs == [5],
          "el único índice marcado es la muestra hundida (posición 5)", idxs)


def no_marca_una_caida_sostenida():
    section("Detector — una caída sostenida de varias muestras: NO se marca")
    reset()
    # Tres muestras bajas seguidas: es roca más blanda, no un golpe de barra.
    pps = [150.0]*5 + [90.0, 88.0, 91.0] + [150.0]*5
    idxs = gw.detectar_golpes_de_barra(_mk_well("W2", pps).points, caida_rel=0.30)
    check(idxs == [],
          "ninguna muestra se marca: las vecinas de cada punto bajo no son "
          "parecidas entre sí (una es baja, no hay recuperación de un solo "
          "punto)", idxs)


def no_marca_una_vecina_que_no_se_recupera():
    section("Detector — la vecina siguiente NO vuelve al nivel anterior: NO se marca")
    reset()
    # Cae y se queda abajo: es un cambio de régimen real, no un golpe de barra.
    pps = [150.0]*5 + [90.0] + [95.0]*5
    idxs = gw.detectar_golpes_de_barra(_mk_well("W3", pps).points, caida_rel=0.30)
    check(idxs == [],
          "sin recuperación al nivel previo, la vecina derecha no se parece "
          "a la izquierda y el punto no se marca", idxs)


def respeta_el_umbral_del_perfil():
    section("Detector — el umbral es el parámetro del perfil, no un número fijo")
    reset()
    # Caída del 20%: por debajo del 30% de convención, pero por sobre un
    # 15% configurado a mano.
    pps = [150.0]*5 + [120.0] + [150.0]*5
    holgado = gw.detectar_golpes_de_barra(_mk_well("W4a", pps).points, caida_rel=0.30)
    check(holgado == [], "con el umbral de convención (30%) no se marca", holgado)
    estricto = gw.detectar_golpes_de_barra(_mk_well("W4b", pps).points, caida_rel=0.15)
    check(estricto == [5], "con un umbral más sensible (15%) sí se marca", estricto)


# ─────────────────────────────────────────────────────────────────────────────
def el_filtro_se_integra_a_clean_filters():
    section("Integración — «golpe_barra» vive en la misma lista que los demás filtros")
    reset()
    _mk_well("W5", [150.0]*5 + [90.0] + [150.0]*5)
    _mk_well("W6", [150.0]*8)  # pozo sin golpes, de control
    filt = gw.add_norm_filter("pp", "golpe_barra")
    check(filt is not None, "add_norm_filter reconoce el método", filt)
    check(filt["removed"] == 1,
          "se marcó exactamente la muestra del golpe de barra", filt)
    check(filt["lo"] is None and filt["hi"] is None,
          "no es un filtro de rango: lo/hi quedan en None, no en un número "
          "inventado", filt)
    check(gw.clean_filters and gw.clean_filters[-1] is filt,
          "el filtro queda registrado en clean_filters", gw.clean_filters)
    w5 = gw.wells["W5"]
    marcado = [p for p in w5.points if not p.entrenable]
    check(len(marcado) == 1 and abs(marcado[0].pp - 90.0) < 1e-9,
          "el punto marcado es justo el de PP=90, no otro", [p.pp for p in marcado])
    check(all(p.entrenable for p in gw.wells["W6"].points),
          "el pozo sin golpe de barra queda intacto", None)


def quitar_el_filtro_lo_revierte():
    section("Integración — remove_filter() también deshace el golpe de barra")
    reset()
    _mk_well("W7", [150.0]*5 + [90.0] + [150.0]*5)
    gw.add_norm_filter("pp", "golpe_barra")
    check(any(not p.entrenable for p in gw.wells["W7"].points),
          "antes de quitar el filtro, el punto está marcado", None)
    ok = gw.remove_filter(0)
    check(ok, "remove_filter acepta el índice del filtro de golpe de barra", ok)
    check(all(p.entrenable for p in gw.wells["W7"].points),
          "recompute_filters() lo revierte igual que a cualquier otro filtro",
          [p.entrenable for p in gw.wells["W7"].points])


def sobrevive_al_corte_de_emboquillado():
    section("Integración — recompute_filters() reaplica el golpe de barra tras un corte")
    reset()
    _mk_well("W8", [150.0]*5 + [90.0] + [150.0]*5, largo0=5.0)
    gw.add_norm_filter("pp", "golpe_barra")
    # recompute_filters() es el camino real que usa la UI al cambiar el corte
    # de emboquillado: limpia todo, reaplica el corte y reaplica cada filtro
    # de clean_filters en orden, golpe de barra incluido.
    gw.recompute_filters(cut_m=3.0)
    marcado = [p for p in gw.wells["W8"].points if not p.entrenable and p.largo >= 3.0]
    check(len(marcado) == 1 and abs(marcado[0].pp - 90.0) < 1e-9,
          "tras recompute_filters(), el golpe de barra sigue marcado", None)


def el_parametro_del_perfil_cambia_la_sensibilidad():
    section("Perfil — pp.golpe_barra_caida_rel es el umbral, sin default oculto")
    reset()
    check("pp.golpe_barra_caida_rel" in gw.param_registry,
          "el parámetro está en el registro del perfil", sorted(gw.param_registry)[:5])
    p = gw.param_registry["pp.golpe_barra_caida_rel"]
    check(p["seccion"] == "Percusión (PP)",
          "vive en la sección de Percusión (PP), junto a los otros de PP", p["seccion"])
    check(p["id"] not in gw.PARAMS_BASICOS,
          "no es un básico: es una afinación fina, detrás de «avanzados»", p)
    check(p["global"] == "PP_GOLPE_BARRA_CAIDA_REL",
          "sincroniza el global que usa el detector", p["global"])
    _mk_well("W9", [150.0]*5 + [120.0] + [150.0]*5)
    gw.set_param("pp.golpe_barra_caida_rel", 0.15)
    check(abs(gw.PP_GOLPE_BARRA_CAIDA_REL - 0.15) < 1e-9,
          "set_param sincroniza el global inmediatamente", gw.PP_GOLPE_BARRA_CAIDA_REL)
    filt = gw.add_norm_filter("pp", "golpe_barra")
    check(filt["removed"] == 1,
          "con el umbral más sensible del perfil, ahora sí se marca la caída "
          "del 20%", filt)
    gw.reset_param("pp.golpe_barra_caida_rel")
    check(abs(gw.PP_GOLPE_BARRA_CAIDA_REL - 0.30) < 1e-9,
          "reset_param vuelve al 30% de convención", gw.PP_GOLPE_BARRA_CAIDA_REL)


# ─────────────────────────────────────────────────────────────────────────────
def el_paso_2_ofrece_el_metodo_y_no_revienta_sin_rango():
    section("Paso 2 — el selector ofrece «Golpe de barra» y el listado no revienta")
    reset()
    _mk_well("W10", [150.0]*5 + [90.0] + [150.0]*5)
    gw.add_norm_filter("pp", "golpe_barra")
    body = gw._step2()

    def _textos(x, out=None):
        out = [] if out is None else out
        if isinstance(x, str):
            out.append(x); return out
        if isinstance(x, (list, tuple)):
            for y in x: _textos(y, out)
            return out
        v = getattr(x, "children", None)
        if v is not None: _textos(v, out)
        return out

    txt = " ".join(_textos(body))
    check("Golpe de barra" in txt,
          "el filtro activo aparece en el listado del Paso 2 sin reventar "
          "por lo/hi en None", txt[:400])

    def _opciones_metodo(x):
        if getattr(x, "id", None) == "sel-norm-method":
            return [o["value"] for o in x.options]
        for a in ("children",):
            v = getattr(x, a, None)
            if isinstance(v, (list, tuple)):
                for y in v:
                    r = _opciones_metodo(y)
                    if r is not None: return r
            elif v is not None:
                r = _opciones_metodo(v)
                if r is not None: return r
        return None

    opciones = _opciones_metodo(body)
    check(opciones is not None and "golpe_barra" in opciones,
          "«golpe_barra» está entre las opciones del dropdown de método",
          opciones)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    marca_la_caida_de_una_sola_muestra_que_se_recupera,
    no_marca_una_caida_sostenida,
    no_marca_una_vecina_que_no_se_recupera,
    respeta_el_umbral_del_perfil,
    el_filtro_se_integra_a_clean_filters,
    quitar_el_filtro_lo_revierte,
    sobrevive_al_corte_de_emboquillado,
    el_parametro_del_perfil_cambia_la_sensibilidad,
    el_paso_2_ofrece_el_metodo_y_no_revienta_sin_rango,
]


def test_golpe_de_barra():
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
    print("✓ GOLPE DE BARRA — todas las verificaciones pasaron.")
    print("=" * 72)
