"""
test_perfil_geometria.py — La pestaña Geometría deja de verse rota.

LO REPORTADO: «El cuadro de Geometría de configuración perfil, sigue roto, al
apretarlo no puedo ingresar.»

DOS DEFECTOS, y los dos apuntan a la misma pestaña.

  · «Geometría» era la ÚNICA clave de MENUS_PERFIL con una letra acentuada
    (Datos, Roca, Fracturamiento, Modelo son ASCII puro). Su botón usaba esa
    palabra COMPLETA como id de un componente pattern-matching. No hay
    evidencia de que Dash la maneje mal, pero tampoco había motivo para
    arriesgarlo en el único id que la llevaba: ahora el id es un slug ASCII
    («Geometria») y el nombre con tilde queda solo para mostrarlo en el botón
    y para toda la lógica interna (secciones, `_perfil_menu_activo`).

  · De sus tres secciones —Validación de mallas, Plano del abanico, Modelo
    de bloques—, las DOS PRIMERAS no tienen NINGÚN campo básico. Con
    «avanzados» apagado (el estado por defecto al abrir el perfil), esas dos
    secciones desaparecían COMPLETAS: ni el título quedaba. Quien entraba a
    Geometría buscando, por ejemplo, el offset máximo de validación de mallas
    no encontraba ni rastro de que ese campo existiera — desde afuera, eso es
    indistinguible de "el cuadro está roto". Ahora toda sección se muestra,
    con sus campos o con un aviso de cuántos quedan detrás de «avanzados».
"""

import os, sys

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
    gw._perfil_menu_activo["menu"] = None
    gw._perfil_menu_activo["avanzados"] = False


def _ids(x, out=None):
    out = [] if out is None else out
    if isinstance(x, (list, tuple)):
        for y in x: _ids(y, out)
        return out
    i = getattr(x, "id", None)
    if i is not None: out.append(i)
    for a in ("children",):
        v = getattr(x, a, None)
        if v is not None: _ids(v, out)
    return out


def _textos(x, out=None):
    out = [] if out is None else out
    if isinstance(x, str):
        out.append(x); return out
    if isinstance(x, (list, tuple)):
        for y in x: _textos(y, out)
        return out
    for a in ("children",):
        v = getattr(x, a, None)
        if v is not None: _textos(v, out)
    return out


class _CtxClickMenu:
    def __init__(self, slug):
        self.triggered_id = {"type": "perfil-menu", "index": slug}
        self.triggered = [{"value": 1}]


# ─────────────────────────────────────────────────────────────────────────────
def geometria_es_la_unica_con_tilde():
    section("Slug — Geometría era la única clave acentuada de MENUS_PERFIL")
    con_tilde = [m for m in gw.MENUS_PERFIL if m != gw._menu_slug(m)]
    check(con_tilde == ["Geometría"],
          "confirmado: es la única que necesitaba un slug distinto", con_tilde)


def el_id_del_boton_es_ascii():
    section("Slug — el botón de Geometría usa un id sin tilde")
    reset()
    body = gw._perfil_panel_body("Datos", False)
    ids = _ids(body)
    slugs_botones = [i["index"] for i in ids
                     if isinstance(i, dict) and i.get("type") == "perfil-menu"]
    check("Geometria" in slugs_botones,
          "el slug ASCII está entre los botones", slugs_botones)
    check("Geometría" not in slugs_botones,
          "y la forma con tilde ya NO es el id de ningún componente",
          slugs_botones)
    check(all(s.isascii() for s in slugs_botones),
          "todos los ids de pestaña son ASCII puro", slugs_botones)


def clickear_geometria_con_su_slug_cambia_de_pestana():
    section("Slug — clickear el botón (con su slug real) sí cambia de pestaña")
    reset()
    gw.callback_context = _CtxClickMenu("Geometria")
    body = gw.on_perfil_menu([1, None, None, None, None], [])
    check(gw._perfil_menu_activo["menu"] == "Geometría",
          "el estado interno guarda el nombre CON tilde, para el resto de "
          "la lógica (secciones, PARAMS_BASICOS)", gw._perfil_menu_activo)
    txt = " ".join(_textos(body))
    check("Validación de mallas" in txt or "Modelo de bloques" in txt,
          "y el cuerpo que vuelve es el de Geometría", txt[:200])


def un_slug_desconocido_no_revienta_ni_cambia_de_pestana():
    section("Slug — un índice que no mapea a ningún menú no rompe nada")
    reset()
    gw.callback_context = _CtxClickMenu("no-existe")
    try:
        body = gw.on_perfil_menu([1, None, None, None, None], [])
    except Exception as e:
        check(False, "no revienta con un slug desconocido",
              f"{type(e).__name__}: {e}")
        return
    check(gw._perfil_menu_activo["menu"] is None,
          "y simplemente no cambia el menú activo", gw._perfil_menu_activo)


def ninguna_seccion_desaparece_sin_avanzados():
    section("Secciones — Validación de mallas y Plano del abanico ya no se esfuman")
    reset()
    body = gw._perfil_panel_body("Geometría", False)
    txt = " ".join(_textos(body))
    for sec in ("Validación de mallas", "Plano del abanico", "Modelo de bloques"):
        check(sec in txt,
              f"la sección «{sec}» aparece aunque no tenga campos básicos "
              "visibles: antes de este arreglo, sin campos básicos la "
              "sección entera desaparecía, título incluido", txt[:300])


def la_seccion_vacia_explica_donde_estan_sus_campos():
    section("Secciones — una sección sin básicos dice cuántos hay detrás de avanzados")
    reset()
    body = gw._perfil_panel_body("Geometría", False)
    txt = " ".join(_textos(body))
    check("detrás de «avanzados»" in txt or "detrás de avanzados" in txt,
          "hay al menos un aviso de campos ocultos: antes esas secciones no "
          "dejaban ni rastro de que existían", txt[:400])
    n_mallas = len([p for p in gw.param_registry.values()
                   if p.get("seccion") == "Validación de mallas"])
    check(str(n_mallas) in txt,
          "con la cantidad real de parámetros de esa sección", (n_mallas, txt[:400]))


def con_avanzados_todos_los_campos_aparecen():
    section("Secciones — con avanzados encendido, se ve todo lo que antes faltaba")
    reset()
    body = gw._perfil_panel_body("Geometría", True)
    ids = _ids(body)
    params = {i["param"] for i in ids
             if isinstance(i, dict) and i.get("type") == "perfil-param"}
    esperados = {p["id"] for p in gw.param_registry.values()
                if p.get("menu") == "Geometría" and p["id"] not in gw.PARAMS_OCULTOS}
    check(esperados <= params,
          "todos los parámetros de Geometría tienen su campo, incluidos los "
          "de Validación de mallas y Plano del abanico",
          sorted(esperados - params))


def las_otras_pestanas_no_cambiaron_de_comportamiento():
    section("Regresión — Datos, Roca, Fracturamiento y Modelo siguen igual")
    reset()
    for m in gw.MENUS_PERFIL:
        gw.callback_context = _CtxClickMenu(gw._menu_slug(m))
        gw.on_perfil_menu([1] * len(gw.MENUS_PERFIL), [])
        check(gw._perfil_menu_activo["menu"] == m,
              f"clickear la pestaña «{m}» activa exactamente «{m}»",
              gw._perfil_menu_activo["menu"])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    geometria_es_la_unica_con_tilde,
    el_id_del_boton_es_ascii,
    clickear_geometria_con_su_slug_cambia_de_pestana,
    un_slug_desconocido_no_revienta_ni_cambia_de_pestana,
    ninguna_seccion_desaparece_sin_avanzados,
    la_seccion_vacia_explica_donde_estan_sus_campos,
    con_avanzados_todos_los_campos_aparecen,
    las_otras_pestanas_no_cambiaron_de_comportamiento,
]


def test_perfil_geometria():
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
    print("✓ PERFIL — PESTAÑA GEOMETRÍA — todas las verificaciones pasaron.")
    print("=" * 72)
