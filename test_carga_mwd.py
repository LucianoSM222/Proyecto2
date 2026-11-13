"""
test_carga_mwd.py — Todo control de carga tiene quien lo escuche.

EL DEFECTO QUE ESTE TEST EXISTE PARA IMPEDIR, y que llegó a producción:

Al sacar los callbacks del Excel calibrador y del Excel geomecánico, el borrado
se llevó por delante 119 líneas de más y desapareció `on_xml` entero — el
callback que recibe los XML IREDES y crea los pozos MWD.

La interfaz quedó intacta a la vista: el `dcc.Upload("up-xml")` seguía en el
layout, el botón seguía abriendo el selector de archivos, el usuario seguía
eligiendo sus XML. Y no pasaba nada. Ni un error, ni un aviso, ni un pozo.

Un dcc.Upload sin callback que lo consuma NO da error en Dash: falla callado.
Es el peor modo de falla que hay en este proyecto —resultado verosímil y
falso— y acá se llevó la función central de la plataforma: cargar MWD.

Este test recorre el layout, junta todos los dcc.Upload y todos los Input de
callback registrados, y falla si alguno queda sin escucha.
"""

import os, sys, base64, glob

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


def _uploads_del_layout():
    """Ids de todos los dcc.Upload que hay en el layout."""
    out = []
    def rec(x):
        if isinstance(x, (list, tuple)):
            for y in x: rec(y)
            return
        if type(x).__name__ == "Upload":
            i = getattr(x, "id", None)
            if i: out.append(i)
        for a in ("children", "title"):
            v = getattr(x, a, None)
            if v is not None: rec(v)
    rec(gw.app.layout)
    return out


def _inputs_registrados():
    """(id, prop) de todo Input de todo callback registrado en la app."""
    pares = set()
    for spec in gw.app.callback_map.values():
        for dep in spec.get("inputs", []):
            cid = dep.get("id")
            if isinstance(cid, dict):
                continue                      # pattern-matching, no aplica acá
            pares.add((cid, dep.get("property")))
    return pares


# ─────────────────────────────────────────────────────────────────────────────
def todo_upload_tiene_callback():
    section("Carga — ningún dcc.Upload queda sin quien lo escuche")
    ups = _uploads_del_layout()
    check(ups, "el layout tiene controles de carga", ups)
    ins = _inputs_registrados()
    huerfanos = [u for u in ups if (u, "contents") not in ins]
    check(not huerfanos,
          "cada control de carga tiene un callback que recibe sus 'contents'. "
          "Un dcc.Upload sin callback no da error: abre el selector, el usuario "
          "elige sus archivos, y no pasa nada", huerfanos)


def el_callback_de_xml_existe():
    section("Carga — el callback de los XML IREDES está y es el correcto")
    check(hasattr(gw, "on_xml"), "on_xml existe")
    ins = _inputs_registrados()
    check(("up-xml", "contents") in ins,
          "y está registrado contra up-xml", sorted(i for i in ins if "xml" in str(i)))


def carga_xml_reales_y_crea_pozos():
    section("Carga — con XML reales se crean pozos de verdad")
    dq = sorted(glob.glob(os.path.join(HERE, "test_data", "DQPC*.xml")))
    mw = sorted(glob.glob(os.path.join(HERE, "test_data", "MWPC*.xml")))
    if not dq or not mw:
        print("  · omitido: faltan XML de MPC en test_data/")
        return
    gw.seed_attribute_registry(force=True)
    gw.seed_param_registry(force=True)
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    contenidos, nombres = [], []
    for p in (dq[:1] + mw[:4]):
        with open(p, "rb") as fh:
            contenidos.append("data:application/xml;base64," +
                              base64.b64encode(fh.read()).decode())
        nombres.append(os.path.basename(p))
    ref, msg, abierto = gw.on_xml(contenidos, nombres, 0)
    check(gw.wells, "se crearon pozos", len(gw.wells))
    check("pozos MWD" in str(msg), "y el mensaje lo declara", str(msg)[:150])
    n_pts = sum(len(w.points) for w in gw.wells.values())
    check(n_pts > 100, "con sus puntos MWD", n_pts)
    check(gw.wz_state["step1"]["xml_loaded"],
          "y el asistente marca el paso 1 como hecho")
    gw.wells.clear()


def el_cache_de_conteos_no_sirve_datos_viejos():
    """
    El badge de vocabulario recorría los 765.848 puntos DOS veces en cada
    acción de la interfaz: 561 ms de espera antes de que pasara nada útil. Se
    cachea, y por eso hay que probar lo contrario de lo habitual: que el caché
    NO entregue un resultado que dejó de ser cierto.
    """
    section("Rendimiento — el caché de conteos por atributo se invalida")
    gw.seed_attribute_registry(force=True)
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    c0 = gw.attribute_point_counts()
    check(c0 == {}, "sin pozos, sin conteos", c0)

    pts = []
    for i in range(40):
        q = gw.MWDPoint(largo=i * 0.5, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        q.atributos = {"litologia": "Bht"}
        pts.append(q)
    gw.wells["W1"] = gw.Well(well_name="W1", plan_id="P", hole_id="1", points=pts)
    c1 = gw.attribute_point_counts()
    check(c1.get("Bht") == 40,
          "agregar un pozo cambia el conteo: el caché no se quedó pegado", c1)

    for q in pts[:10]:
        q.atributos = {"litologia": "Kfa"}
    gw.wells["W2"] = gw.Well(well_name="W2", plan_id="P", hole_id="2",
                             points=list(pts[:5]))
    c2 = gw.attribute_point_counts()
    check(c2.get("Bht", 0) != 40 or c2.get("Kfa"),
          "y cambiar los puntos también", c2)

    # El rol de cada identidad sale de la MISMA pasada: tiene que coincidir.
    counts, roles = gw._agregados_por_atributo()
    check(set(roles) <= set(counts),
          "los roles y los conteos vienen de la misma pasada", (roles, counts))
    check(roles.get("Kfa") == "litologia", "con el rol correcto", roles)
    gw.wells.clear()


def sin_archivos_no_revienta():
    section("Carga — sin archivos no hace nada, sin reventar")
    r = gw.on_xml(None, None, 0)
    check(len(r) == 3, "devuelve la tripleta esperada", r)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    todo_upload_tiene_callback,
    el_callback_de_xml_existe,
    carga_xml_reales_y_crea_pozos,
    el_cache_de_conteos_no_sirve_datos_viejos,
    sin_archivos_no_revienta,
]


def test_carga_mwd():
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
    print("✓ CARGA MWD — todas las verificaciones pasaron.")
    print("=" * 72)
