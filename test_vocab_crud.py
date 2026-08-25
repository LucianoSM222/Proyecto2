"""
test_vocab_crud.py — Alta y baja de atributos del vocabulario desde la
aplicación en funcionamiento, sin editar el código fuente.

Motivo (pedido del autor): el registro se siembra con la Tabla 3.2 de
Karzulovic, que caracteriza cinco unidades de Punta del Cobre. Pucobre opera
TRES faenas con litologías distintas, y el mismo MPC ya tiene unidades fuera
de esa tabla (Calizas de la Formación Abundancia; las cuatro mallas de
PCS_1059). Hoy registrar cualquiera de ellas obliga a tocar
seed_attribute_registry() en el fuente — lo que hace la plataforma
intransferible a otra faena sin un programador.

Lo que se prueba:
  · alta con validación: id único, rol de ATTR_ROLES, jerarquía coherente
  · la banda de UCS respeta los límites físicos (T1.6) y no se trunca
  · baja segura: un atributo EN USO no se borra en silencio
  · la baja arrastra sus alias, y lo declara
  · alta y baja sobreviven al round-trip de export/import del vocabulario
  · un atributo creado en caliente etiqueta el entrenamiento igual que uno
    sembrado (es el punto: que sirva de verdad, no solo que exista)
"""

import os, sys, json

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
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.attribute_exclusions.clear(); gw.pending_aliases.clear()
    gw.attribute_meters.clear()


def _raises(fn, exc):
    try:
        fn(); return False
    except exc:
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
def alta_basica():
    section("Alta — crear una litología nueva desde la aplicación")
    reset()
    n_antes = len(gw.attr_registry)
    a = gw.create_attribute(
        "Ka", "Calizas Formación Abundancia", rol="litologia",
        ucs_min=60.0, ucs_max=120.0, ucs_media=90.0, calidad=3,
        fuente="Informe geológico base Pucobre; banda de literatura para calizas.")
    check(a is not None and a.id == "Ka", "devuelve el atributo creado")
    check(len(gw.attr_registry) == n_antes + 1, "queda registrado")
    check(gw.attr_registry["Ka"].nombre_oficial == "Calizas Formación Abundancia",
          "conserva el nombre oficial")
    check(gw.attr_registry["Ka"].rol == "litologia", "conserva el rol")
    check(gw.attr_registry["Ka"].ucs_ancla() == 90.0, "la banda de UCS queda utilizable")
    check(gw.attr_registry["Ka"].entrenable() == (True, ""),
          "un atributo nuevo con banda y calidad es entrenable de inmediato",
          gw.attr_registry["Ka"].entrenable())
    check(not gw.validate_attribute_tree(),
          "el árbol del registro sigue siendo válido", gw.validate_attribute_tree())
    reset()


def alta_validaciones():
    section("Alta — validaciones: nada entra al registro a medias")
    reset()
    check(_raises(lambda: gw.create_attribute("Kfa", "Duplicado"), ValueError),
          "un id ya existente lanza ValueError (no pisa el atributo vigente)")
    check(gw.attr_registry["Kfa"].nombre_oficial == "Albitófiro",
          "y el atributo original queda intacto")

    check(_raises(lambda: gw.create_attribute("", "Sin id"), ValueError),
          "un id vacío lanza ValueError")
    check(_raises(lambda: gw.create_attribute("X1", ""), ValueError),
          "un nombre oficial vacío lanza ValueError")
    check(_raises(lambda: gw.create_attribute("X2", "Rol raro", rol="mineral"), ValueError),
          "un rol fuera de ATTR_ROLES lanza ValueError")

    # (T1.6) Límites físicos de UCS: se rechaza, nunca se trunca en silencio.
    check(_raises(lambda: gw.create_attribute("X3", "Fuera de rango",
                                              ucs_media=999.0), ValueError),
          "un UCS fuera de [0, 450] MPa lanza ValueError en vez de truncarse")
    check("X3" not in gw.attr_registry, "y el atributo rechazado NO queda registrado")

    check(_raises(lambda: gw.create_attribute("X4", "Banda invertida",
                                              ucs_min=200.0, ucs_max=100.0), ValueError),
          "una banda con mín > máx lanza ValueError")

    # Jerarquía: una subunidad necesita un padre existente y de nivel unidad.
    check(_raises(lambda: gw.create_attribute("X5", "Huérfana", nivel="subunidad"), ValueError),
          "una subunidad sin padre lanza ValueError")
    check(_raises(lambda: gw.create_attribute("X6", "Padre fantasma", nivel="subunidad",
                                              padre="NoExiste"), ValueError),
          "una subunidad con padre inexistente lanza ValueError")
    check(_raises(lambda: gw.create_attribute("X7", "Padre subunidad", nivel="subunidad",
                                              padre="Brecha_mixta"), ValueError),
          "una subunidad cuyo padre es otra subunidad lanza ValueError")

    hijo = gw.create_attribute("X8", "Subunidad válida", nivel="subunidad", padre="Kpcs")
    check(hijo.padre == "Kpcs" and "X8" in gw.attribute_children("Kpcs"),
          "una subunidad válida queda colgada de su padre")
    reset()


def baja_segura():
    section("Baja — un atributo EN USO no se borra en silencio")
    reset()
    gw.create_attribute("Tmp", "Temporal", rol="litologia", ucs_media=100.0, calidad=3)

    # En uso por una capa cargada.
    lay = gw.Layer(name="capa_tmp", kind="litologia", triangles=np.zeros((0, 3, 3)),
                   bbox_min=np.zeros(3), bbox_max=np.zeros(3))
    gw.set_layer_attributes(lay, {"litologia": "Tmp"})
    gw.layers["capa_tmp"] = lay
    check(_raises(lambda: gw.delete_attribute("Tmp"), ValueError),
          "borrar un atributo usado por una capa lanza ValueError")
    check("Tmp" in gw.attr_registry, "y el atributo sigue registrado")

    rep = gw.delete_attribute("Tmp", force=True)
    check("Tmp" not in gw.attr_registry, "con force=True sí se borra")
    check(rep["capas"] == ["capa_tmp"],
          "el reporte declara qué capas lo referenciaban", rep)

    # En uso por puntos ya clasificados.
    reset()
    gw.create_attribute("Tmp2", "Temporal 2", rol="litologia", ucs_media=100.0, calidad=3)
    p = gw.MWDPoint(largo=0.0, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1, t=0.0)
    p.atributos = {"litologia": "Tmp2"}
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=[p])
    check(_raises(lambda: gw.delete_attribute("Tmp2"), ValueError),
          "borrar un atributo con puntos clasificados lanza ValueError")
    rep = gw.delete_attribute("Tmp2", force=True)
    check(rep["puntos"] == 1, "el reporte declara cuántos puntos lo usaban", rep)

    # Un padre con subunidades no se borra sin más: dejaría huérfanas.
    reset()
    check(_raises(lambda: gw.delete_attribute("Kpcs"), ValueError),
          "borrar una unidad con subunidades lanza ValueError")
    check(_raises(lambda: gw.delete_attribute("NoExisteNada"), KeyError),
          "borrar un atributo inexistente lanza KeyError")
    reset()


def baja_arrastra_alias():
    section("Baja — los alias del atributo se van con él, y se declara")
    reset()
    gw.create_attribute("Tmp3", "Temporal 3", rol="litologia", ucs_media=100.0, calidad=3)
    gw.register_alias("Caliza gris", "Tmp3", "dxf_layer")
    gw.register_alias("CalizaGris2", "Tmp3", "manual")
    check(gw.resolve_alias("Caliza gris") == {"litologia": "Tmp3"}, "el alias resuelve antes de borrar")

    rep = gw.delete_attribute("Tmp3", force=True)
    check(sorted(rep["alias"]) == ["Caliza gris", "CalizaGris2"],
          "el reporte nombra los alias arrastrados", rep["alias"])
    check(not gw.resolve_alias("Caliza gris"),
          "el alias deja de resolver: no queda apuntando a un id fantasma")
    check(not gw.validate_attribute_tree(),
          "el registro queda consistente tras la baja", gw.validate_attribute_tree())
    reset()


def persistencia_round_trip():
    section("Persistencia — alta y baja sobreviven al export/import")
    reset()
    gw.create_attribute("Ka", "Calizas Formación Abundancia", rol="litologia",
                        ucs_min=60.0, ucs_max=120.0, ucs_media=90.0, calidad=3,
                        fuente="Informe geológico base")
    gw.delete_attribute("DL", force=True)          # código sin identificar
    n_esperado = len(gw.attr_registry)

    blob = gw.export_vocabulary_json()
    gw.attr_registry.clear(); gw.alias_registry.clear()
    res = gw.import_vocabulary(blob, replace=True)
    check(not res["errores"], "la importación no arroja errores", res["errores"])
    check(len(gw.attr_registry) == n_esperado, "el conteo de atributos sobrevive",
          (len(gw.attr_registry), n_esperado))
    check("Ka" in gw.attr_registry, "el atributo creado en caliente sobrevive")
    check(gw.attr_registry["Ka"].ucs_ancla() == 90.0, "con su banda intacta")
    check("DL" not in gw.attr_registry, "el atributo borrado NO reaparece")
    reset()


def atributo_nuevo_etiqueta_de_verdad():
    section("Un atributo creado en caliente etiqueta el entrenamiento")
    reset()
    gw.create_attribute("Ka", "Calizas Formación Abundancia", rol="litologia",
                        ucs_min=60.0, ucs_max=120.0, ucs_media=90.0, calidad=3,
                        fuente="Informe geológico base")
    # Dos dominios con etiquetas distintas: uno sembrado, otro creado en caliente.
    gw.domains["Ka"] = {"ucs_lab": 90.0, "atributo_id": "Ka", "nombre": "Ka"}
    gw.domains["Kfa"] = {"ucs_lab": 289.6, "atributo_id": "Kfa", "nombre": "Kfa"}

    rng = np.random.default_rng(0)
    for wn, dom in (("W_ka", "Ka"), ("W_kfa", "Kfa")):
        pts = []
        for i in range(30):
            p = gw.MWDPoint(largo=i * 0.02, vel=float(rng.uniform(1, 9)),
                            pp=float(rng.uniform(1, 9)), pa=float(rng.uniform(1, 9)),
                            pd=float(rng.uniform(1, 9)), pr=float(rng.uniform(1, 9)),
                            pf=float(rng.uniform(1, 9)), se=float(rng.uniform(1, 9)), t=0.0)
            p.dominio = dom; p.entrenable = True; p.di = 0.5
            pts.append(p)
        gw.wells[wn] = gw.Well(well_name=wn, plan_id="P", hole_id=wn, points=pts)

    X, y, groups, _ = gw._get_train_data(0.0, 450.0)
    check(len(X) == 60, "los puntos de ambos dominios entran al entrenamiento", len(X))
    check(sorted(set(y)) == [90.0, 289.6],
          "la etiqueta del atributo NUEVO aparece junto a la del sembrado", sorted(set(y)))
    check(gw._degenerate_training_check(y) is None,
          "con el atributo nuevo el conjunto deja de ser degenerado")
    reset()


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    alta_basica,
    alta_validaciones,
    baja_segura,
    baja_arrastra_alias,
    persistencia_round_trip,
    atributo_nuevo_etiqueta_de_verdad,
]


def test_vocab_crud():
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
    print("✓ CRUD DE VOCABULARIO — todas las verificaciones pasaron.")
    print("=" * 72)
