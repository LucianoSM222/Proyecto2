"""
test_perfil_faena.py — Perfil de faena: los parámetros se configuran, no se
entierran en el código.

EL REQUISITO, en palabras del autor: para que esto sea replicable en otros
yacimientos, las decisiones y los datos tienen que poder configurarse DESDE EL
PROGRAMA y no quedar fijos en el código. Pucobre tiene tres faenas con
litología distinta; el burden, la desviación de perforación, el rango
operacional de PP y hasta los límites físicos de UCS cambian de una a otra.

Un parámetro del perfil declara SIEMPRE cinco cosas: su valor, su valor por
defecto, sus límites, sus unidades y su PROCEDENCIA. Un número sin
procedencia es un número que nadie puede defender en una revisión.

Hay parámetros PROTEGIDOS: los que CLAUDE.md fija como convención inmutable.
Se pueden leer y exportar, nunca escribir. Es la misma regla que protege la
variante de convención del DI.

El perfil se exporta e importa como JSON: es lo que una faena nueva recibe
para arrancar con sus propios números en vez de con los de Punta del Cobre.
"""

import os, sys, json, tempfile

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


# ─────────────────────────────────────────────────────────────────────────────
def el_perfil_esta_declarado():
    section("Perfil — cada parámetro declara valor, defecto, límites y procedencia")
    reset()
    reg = gw.param_registry
    check(len(reg) >= 20, "el perfil registra los parámetros de operación", len(reg))
    faltan = []
    for pid, p in reg.items():
        for k in ("id", "seccion", "etiqueta", "valor", "defecto", "tipo",
                  "unidad", "procedencia"):
            if k not in p:
                faltan.append((pid, k))
    check(not faltan, "todos declaran los ocho campos", faltan[:5])
    sin_proc = [pid for pid, p in reg.items() if not p["procedencia"]]
    check(not sin_proc, "ninguno queda sin procedencia: un número sin fuente no "
          "se puede defender", sin_proc[:5])
    secciones = sorted({p["seccion"] for p in reg.values()})
    check(len(secciones) >= 5, "y se agrupan por sección para la interfaz", secciones)


def los_parametros_que_importan_estan():
    section("Perfil — los parámetros que una faena nueva SÍ tiene que cambiar")
    reset()
    esperados = [
        "bloques.tamano_m", "bloques.holgura_m", "bloques.radio_h_m",
        "bloques.radio_v_m", "bloques.anisotropia_z", "bloques.min_muestras",
        "abanico.eps_m", "abanico.factor_dispersion",
        "disc.ventana_m", "disc.caida_rel", "disc.radio_etiqueta_m",
        "rqd.tramo_min_m", "rqd.radio_max_m",
        "pp.min_bar", "pp.max_bar",
        "rop.min_fisica", "ucs.min_fisico", "ucs.max_fisico",
    ]
    faltan = [e for e in esperados if e not in gw.param_registry]
    check(not faltan, "están todos los que discutimos", faltan)


def leer_y_escribir():
    section("Perfil — se lee y se escribe desde el programa")
    reset()
    v0 = gw.get_param("bloques.tamano_m")
    check(v0 == 2.5, "el bloque arranca en 2,5 m", v0)
    gw.set_param("bloques.tamano_m", 5.0)
    check(gw.get_param("bloques.tamano_m") == 5.0, "se puede cambiar")
    check(gw.BLOQUE_M == 5.0,
          "y el cambio llega al módulo, no se queda en el registro", gw.BLOQUE_M)
    gw.reset_param("bloques.tamano_m")
    check(gw.get_param("bloques.tamano_m") == 2.5, "y se puede volver al defecto")
    check(gw.BLOQUE_M == 2.5, "también en el módulo", gw.BLOQUE_M)


def el_cambio_llega_a_las_funciones():
    section("Perfil — cambiar un parámetro cambia lo que las funciones HACEN")
    reset()
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    import numpy as np
    pts = []
    for i in range(40):
        p = gw.MWDPoint(largo=i * 0.5, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este, p.norte, p.cota = 376700.0, 6959000.0, 300.0 - i * 0.5
        p.ucs_ml = p.ucs_matriz = 120.0; p.di = 0.4
        p.entrenable = True; p.dominio = p.lito = "Bht"
        pts.append(p)
    w = gw.Well(well_name="W1", plan_id="CAS_PR01_TH_W1", hole_id="W1", points=pts)
    w.caseron = "CAS_A"
    gw.wells["W1"] = w

    r1 = gw.interpolate_block_model()
    gw.set_param("bloques.tamano_m", 5.0)
    r2 = gw.interpolate_block_model()
    check(r1["bloque_m"] == 2.5 and r2["bloque_m"] == 5.0,
          "el modelo de bloques toma el tamaño del perfil en cada llamada",
          (r1["bloque_m"], r2["bloque_m"]))
    check(r1["n_bloques"] != r2["n_bloques"],
          "y el resultado cambia de verdad", (r1["n_bloques"], r2["n_bloques"]))
    gw.reset_param("bloques.tamano_m")
    gw.wells.clear()


def los_protegidos_no_se_escriben():
    section("Perfil — los parámetros de convención no se pueden escribir")
    reset()
    protegidos = [pid for pid, p in gw.param_registry.items() if p.get("protegido")]
    check(protegidos, "hay parámetros marcados como protegidos", protegidos)
    for pid in protegidos:
        try:
            gw.set_param(pid, gw.get_param(pid))
            check(False, f"{pid} debería rechazar la escritura")
        except gw.ParametroProtegido:
            pass
    check(True, f"los {len(protegidos)} protegidos rechazan la escritura")
    check(all("claude.md" in (gw.param_registry[p]["procedencia"] or "").lower()
              or "convención" in (gw.param_registry[p]["procedencia"] or "").lower()
              for p in protegidos),
          "declarando que su procedencia es la convención del proyecto",
          [gw.param_registry[p]["procedencia"][:60] for p in protegidos[:2]])


def se_valida_antes_de_escribir():
    section("Perfil — un valor fuera de rango se rechaza, no se acepta a medias")
    reset()
    for pid, malo in (("bloques.tamano_m", -1.0),
                      ("bloques.min_muestras", 0),
                      ("pp.min_bar", "no soy un número")):
        antes = gw.get_param(pid)
        try:
            gw.set_param(pid, malo)
            check(False, f"{pid}={malo!r} debería fallar")
        except (ValueError, TypeError):
            check(gw.get_param(pid) == antes,
                  f"{pid} rechaza {malo!r} y queda en su valor anterior")


def exportar_e_importar():
    section("Perfil — se exporta e importa: es lo que recibe una faena nueva")
    reset()
    gw.set_param("bloques.tamano_m", 5.0)
    gw.set_param("abanico.eps_m", 4.0)
    texto = gw.export_site_profile()
    d = json.loads(texto)
    check("parametros" in d and "sitio" in d, "el JSON trae parámetros y sitio",
          list(d))
    check(d["parametros"]["bloques.tamano_m"] == 5.0,
          "con los valores vigentes", d["parametros"].get("bloques.tamano_m"))
    check("generado" in d and "app_version" in d,
          "y la trazabilidad de cuándo y con qué versión salió", list(d))

    reset()
    check(gw.get_param("bloques.tamano_m") == 2.5, "tras reiniciar vuelve al defecto")
    rep = gw.import_site_profile(texto)
    check(rep["status"] == "ok", "el perfil se importa", rep.get("motivo"))
    check(gw.get_param("bloques.tamano_m") == 5.0 and gw.get_param("abanico.eps_m") == 4.0,
          "y restituye los valores", (gw.get_param("bloques.tamano_m"),
                                      gw.get_param("abanico.eps_m")))
    check(rep["n_aplicados"] >= 2, "declarando cuántos aplicó", rep.get("n_aplicados"))

    # Un perfil con basura no rompe: aplica lo válido y DECLARA lo que no.
    reset()
    malo = json.dumps({"parametros": {"bloques.tamano_m": 7.5,
                                      "no.existe": 1,
                                      "bloques.min_muestras": -3}})
    rep2 = gw.import_site_profile(malo)
    check(gw.get_param("bloques.tamano_m") == 7.5, "aplica lo válido")
    check(len(rep2["rechazados"]) == 2,
          "y declara uno por uno lo que rechazó", rep2.get("rechazados"))
    check(all(r.get("motivo") for r in rep2["rechazados"]),
          "con el motivo de cada rechazo", rep2.get("rechazados"))
    gw.seed_param_registry(force=True)


def el_reporte_del_perfil():
    section("Perfil — el reporte muestra qué se movió respecto del defecto")
    reset()
    gw.set_param("bloques.holgura_m", 20.0)
    rep = gw.site_profile_report()
    check(rep["n_modificados"] == 1, "cuenta los modificados", rep.get("n_modificados"))
    mod = rep["modificados"][0]
    check(mod["id"] == "bloques.holgura_m" and mod["defecto"] == 15.0
          and mod["valor"] == 20.0,
          "diciendo de cuánto a cuánto", mod)
    check(rep["sitio"] == gw.ACTIVE_SITE, "y para qué sitio", rep.get("sitio"))
    gw.seed_param_registry(force=True)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_perfil_esta_declarado,
    los_parametros_que_importan_estan,
    leer_y_escribir,
    el_cambio_llega_a_las_funciones,
    los_protegidos_no_se_escriben,
    se_valida_antes_de_escribir,
    exportar_e_importar,
    el_reporte_del_perfil,
]


def test_perfil_faena():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        gw.seed_param_registry(force=True)
        gw.wells.clear()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        gw.seed_param_registry(force=True)
        gw.wells.clear()
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ PERFIL DE FAENA — todas las verificaciones pasaron.")
    print("=" * 72)
