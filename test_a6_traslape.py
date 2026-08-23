"""
test_a6_traslape.py — Tests sintéticos de traslape (adenda A.6).

La guarda geométrica de test_p1_fundaciones.py verifica classify_all_wells con
UNA sola malla, y con una sola malla NO EXISTE traslape: las reglas de A.5
nunca se ejecutan. El canario original tampoco cubre esto — H5 contra
Metandesitas.dxf es también un caso de malla única. Estos tests cubren el hueco.

No requieren datos reales: construyen mallas de cajas en memoria (y una malla
compuesta como DXF mínimo en disco, para ejercitar también la ruta de
parse_dxf + resolución de nombre). La geometría es la REAL — ray casting
vertical con el grid XY de aceleración, sin mocks.

Casos (A.6):
  1. Anidamiento              unidad ⊃ subunidad → gana la subunidad, 0 ambiguos
  2. Conflicto de unidades    dos unidades cruzadas → ambiguo, excluido, contado
  3. Conflicto de subunidades dos subunidades del mismo padre → ambiguo
  4. Composición              litología + alteración → dominio compuesto, banda heredada
  5. Predominio               estructura sobre cualquiera → gana la estructura
  6. Equivalencia             caso 4 con dos mallas == con una malla compuesta
  7. Fuera de todo            sin clasificar, contabilizado como tal

Y además: el contador de ambiguos es accesible desde el reporte de composición
del entrenamiento (rf_stats).
"""

import os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import ezdxf
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


# ─────────────────────────────────────────────────────────────────────────────
def box_triangles(x0, y0, z0, x1, y1, z1):
    """Caja cerrada como 12 triángulos (6 caras × 2). Geometría real."""
    v = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    faces = [(0, 1, 2), (0, 2, 3),      # base
             (4, 6, 5), (4, 7, 6),      # techo
             (0, 5, 1), (0, 4, 5),      # y0
             (2, 6, 7), (2, 7, 3),      # y1
             (0, 3, 7), (0, 7, 4),      # x0
             (1, 5, 6), (1, 6, 2)]      # x1
    return np.array([[v[a], v[b], v[c]] for a, b, c in faces], dtype=np.float64)


def mk_layer(name, tris, atributos=None, kind="litologia"):
    """Capa real con triángulos reales; `atributos` es {rol: atributo_id}."""
    lay = gw.Layer(name=name, kind=kind, triangles=tris,
                   bbox_min=tris.reshape(-1, 3).min(0),
                   bbox_max=tris.reshape(-1, 3).max(0))
    if atributos:
        gw.set_layer_attributes(lay, atributos)
    gw.layers[name] = lay
    return lay


def put_points(coords):
    """Crea un pozo con un MWDPoint por coordenada dada."""
    pts = [gw.MWDPoint(largo=i * 0.02, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1,
                       t=0.0, este=float(c[0]), norte=float(c[1]), cota=float(c[2]))
           for i, c in enumerate(coords)]
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=pts)
    return pts


def reset():
    gw.seed_attribute_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.attribute_exclusions.clear(); gw.pending_aliases.clear()
    gw.attribute_meters.clear()


# Coordenadas dentro de la envolvente MPC, para no chocar con el guardián.
E0, N0, Z0 = 376700.0, 6958900.0, 300.0
# OJO con las coordenadas de prueba: cada cara de la caja son DOS triángulos
# que comparten la diagonal y=x. Un punto con offset (d, d) cae exactamente
# sobre esa arista compartida, que es un caso degenerado para cualquier ray
# caster (la intersección se cuenta dos veces o ninguna). No es un defecto del
# algoritmo — es medida nula y los puntos MWD reales nunca caen ahí — pero las
# fixtures deben evitarlo deliberadamente. Por eso los offsets son asimétricos.
DENTRO = (E0 + 6.0, N0 + 9.0, Z0 + 5.0)       # interior común de las cajas
FUERA = (E0 + 500.0, N0 + 500.0, Z0 + 500.0)  # lejos de toda caja

BOX_GRANDE = box_triangles(E0, N0, Z0, E0 + 20, N0 + 20, Z0 + 20)
BOX_CHICA = box_triangles(E0 + 2, N0 + 2, Z0 + 2, E0 + 10, N0 + 10, Z0 + 10)
# Cruzada: se solapa con BOX_GRANDE en la zona de DENTRO, pero no la contiene.
BOX_CRUZADA = box_triangles(E0 + 3, N0 + 3, Z0 + 3, E0 + 30, N0 + 30, Z0 + 30)


def clasificar(coords):
    """Corre la clasificación real y devuelve los puntos."""
    pts = put_points(coords)
    gw.classify_all_wells()
    gw.build_domain_index()
    return pts


# ─────────────────────────────────────────────────────────────────────────────
def caso1_anidamiento():
    section("Caso 1 — Anidamiento: unidad ⊃ subunidad → gana la subunidad")
    reset()
    mk_layer("caja_basal", BOX_GRANDE, {"litologia": "Kpcsb_basal"})
    mk_layer("caja_mixta", BOX_CHICA, {"litologia": "Brecha_mixta"})
    p = clasificar([DENTRO])[0]
    check(p.lito == "Brecha_mixta",
          "el punto interior a ambas resuelve a la SUBUNIDAD", p.lito)
    check(not p.ambiguo, "no se marca ambiguo", p.ambiguo_motivo)
    check(gw.overlap_stats["n_ambiguos"] == 0,
          "contador de ambiguos = 0", gw.overlap_stats["n_ambiguos"])
    check(gw.overlap_stats["n_subunidad_gana"] == 1,
          "el anidamiento queda contabilizado", gw.overlap_stats["n_subunidad_gana"])
    check(p.dominio == "Brecha_mixta", "el dominio es la subunidad", p.dominio)
    check(gw.domains[p.dominio]["ucs_lab"] == 111.5,
          "hereda la banda de la subunidad (Brecha mixta, media 111,5)",
          gw.domains[p.dominio]["ucs_lab"])


def caso2_conflicto_unidades():
    section("Caso 2 — Conflicto: dos unidades de rol litología que se cruzan")
    reset()
    mk_layer("caja_Kfa", BOX_GRANDE, {"litologia": "Kfa"})
    mk_layer("caja_Bht", BOX_CRUZADA, {"litologia": "Bht"})
    p = clasificar([DENTRO])[0]
    check(p.ambiguo, "el punto en la intersección se marca ambiguo", p.__dict__)
    check(p.ambiguo_motivo == "dos unidades distintas",
          "el motivo es 'dos unidades distintas'", p.ambiguo_motivo)
    check(p.dominio is None and p.lito is None,
          "queda excluido del dominio", (p.dominio, p.lito))
    check(gw.overlap_stats["n_ambiguos"] == 1,
          "contador de ambiguos = 1", gw.overlap_stats["n_ambiguos"])
    check(any("Bht" in c and "Kfa" in c for c in gw.overlap_stats["casos"]),
          "el caso concreto queda reportado, no descartado en silencio",
          gw.overlap_stats["casos"])


def caso3_conflicto_subunidades():
    section("Caso 3 — Conflicto: dos subunidades del mismo padre que se cruzan")
    reset()
    mk_layer("caja_mixta", BOX_GRANDE, {"litologia": "Brecha_mixta"})
    mk_layer("caja_sedim", BOX_CRUZADA, {"litologia": "Kpcsb_sedimentaria"})
    p = clasificar([DENTRO])[0]
    check(p.ambiguo, "el punto en la intersección se marca ambiguo")
    check(p.ambiguo_motivo == "dos subunidades del mismo padre",
          "el motivo distingue el caso", p.ambiguo_motivo)
    check(gw.overlap_stats["n_ambiguos"] == 1, "contador de ambiguos = 1")

    # Variante: subunidades de padres distintos.
    reset()
    mk_layer("caja_mixta", BOX_GRANDE, {"litologia": "Brecha_mixta"})
    mk_layer("caja_lutN", BOX_CRUZADA, {"litologia": "Lutitas_normales"})
    p = clasificar([DENTRO])[0]
    check(p.ambiguo and p.ambiguo_motivo == "dos subunidades de padres distintos",
          "subunidades de padres distintos también es Conflicto", p.ambiguo_motivo)


def caso4_composicion():
    section("Caso 4 — Composición: litología + alteración")
    reset()
    mk_layer("caja_Bht", BOX_GRANDE, {"litologia": "Bht"})
    mk_layer("caja_Fk", BOX_CRUZADA, {"alteracion": "Fk"})
    # Bht no trae banda de laboratorio; se le asigna una para verificar herencia.
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    p = clasificar([DENTRO])[0]
    check(not p.ambiguo, "roles distintos NO son conflicto", p.ambiguo_motivo)
    check(gw.overlap_stats["n_ambiguos"] == 0, "contador de ambiguos = 0")
    check((p.lito, p.alteracion) == ("Bht", "Fk"),
          "se componen litología y alteración", (p.lito, p.alteracion))
    check(p.dominio == "Bht~Fk", "el dominio compuesto es (litología, alteración)",
          p.dominio)
    check(gw.overlap_stats["n_compuestos"] == 1, "el compuesto queda contabilizado")
    gw.build_domain_index()
    check(gw.domains["Bht~Fk"]["ucs_lab"] == 150.0,
          "LA BANDA SE HEREDA DE LA LITOLOGÍA", gw.domains["Bht~Fk"]["ucs_lab"])
    check(gw.domains["Bht~Fk"]["atributo_id"] == "Bht",
          "el atributo de banda del dominio es la litología")
    check(gw.domains["Bht~Fk"]["alteracion_id"] == "Fk",
          "la alteración queda registrada en el dominio")

    # Una alteración SOLA no define dominio.
    reset()
    mk_layer("caja_Fk", BOX_GRANDE, {"alteracion": "Fk"})
    p = clasificar([DENTRO])[0]
    check(p.dominio is None and p.alteracion == "Fk",
          "una alteración sola NO define dominio", (p.dominio, p.alteracion))
    check(not p.ambiguo, "y tampoco es ambigua")


def caso5_predominio():
    section("Caso 5 — Predominio: la estructura gana sobre todo lo demás")
    reset()
    gw.attr_registry["FallaX"] = gw.Attribute(
        id="FallaX", nombre_oficial="Falla de prueba", rol="estructura", nivel="unidad")
    mk_layer("caja_Bht", BOX_GRANDE, {"litologia": "Bht"})
    mk_layer("caja_Fk", BOX_GRANDE, {"alteracion": "Fk"})
    mk_layer("caja_falla", BOX_CRUZADA, {"estructura": "FallaX"})
    p = clasificar([DENTRO])[0]
    check(not p.ambiguo, "tres roles distintos no son conflicto", p.ambiguo_motivo)
    check(p.estructura == "FallaX", "la estructura se detecta", p.estructura)
    check(p.dominio == "Bht::FallaX",
          "la estructura predomina y define el dominio", p.dominio)
    check("~" not in p.dominio,
          "con estructura presente, la alteración no compone la clave", p.dominio)

    # Predominio también sobre el anidamiento del caso 1.
    reset()
    gw.attr_registry["FallaX"] = gw.Attribute(
        id="FallaX", nombre_oficial="Falla de prueba", rol="estructura", nivel="unidad")
    mk_layer("caja_basal", BOX_GRANDE, {"litologia": "Kpcsb_basal"})
    mk_layer("caja_mixta", BOX_CHICA, {"litologia": "Brecha_mixta"})
    mk_layer("caja_falla", BOX_CRUZADA, {"estructura": "FallaX"})
    p = clasificar([DENTRO])[0]
    check(p.dominio == "Brecha_mixta::FallaX",
          "predomina la estructura sobre la subunidad ya anidada", p.dominio)


def _dxf_compuesto(path, tris):
    """Escribe una malla como DXF mínimo de 3DFACE (ruta real de parse_dxf)."""
    doc = ezdxf.new()
    msp = doc.modelspace()
    for t in tris:
        msp.add_3dface([tuple(t[0]), tuple(t[1]), tuple(t[2]), tuple(t[2])])
    doc.saveas(path)
    return path


def caso6_equivalencia_empaquetado():
    section("Caso 6 — Equivalencia de empaquetado: dos mallas == una compuesta")

    # (a) Identidad estricta: la MISMA geometría, empaquetada de las dos formas.
    reset()
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    mk_layer("caja_Bht", BOX_GRANDE, {"litologia": "Bht"})
    mk_layer("caja_Fk", BOX_GRANDE, {"alteracion": "Fk"})
    p_sep = clasificar([DENTRO])[0]
    sep = (p_sep.dominio, p_sep.lito, p_sep.alteracion, p_sep.ambiguo,
           gw.domains[p_sep.dominio]["ucs_lab"])
    amb_sep = gw.overlap_stats["n_ambiguos"]

    reset()
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    mk_layer("Bht_Fk", BOX_GRANDE, {"litologia": "Bht", "alteracion": "Fk"})
    p_cmp = clasificar([DENTRO])[0]
    cmp_ = (p_cmp.dominio, p_cmp.lito, p_cmp.alteracion, p_cmp.ambiguo,
            gw.domains[p_cmp.dominio]["ucs_lab"])
    amb_cmp = gw.overlap_stats["n_ambiguos"]

    check(sep == cmp_, "dominio, roles y banda IDÉNTICOS entre empaquetados",
          f"separadas={sep} compuesta={cmp_}")
    check(amb_sep == amb_cmp == 0, "ambos con 0 ambiguos", (amb_sep, amb_cmp))
    check(cmp_[0] == "Bht~Fk", "la malla compuesta produce el dominio compuesto", cmp_)

    # (b) Ruta real de DXF: una malla A_B.dxf cuyo NOMBRE se descompone.
    reset()
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    tmp = os.path.join(tempfile.mkdtemp(), "Bht_Fk.dxf")
    _dxf_compuesto(tmp, BOX_GRANDE)
    tris, _ = gw.parse_dxf(tmp, "Bht_Fk.dxf")
    lay = gw.Layer(name="Bht_Fk", kind=gw.guess_kind("Bht_Fk.dxf"), triangles=tris,
                   bbox_min=tris.reshape(-1, 3).min(0),
                   bbox_max=tris.reshape(-1, 3).max(0))
    # El nombre no está registrado: A.3 debe PROPONER la descomposición.
    m = gw.resolve_or_note("Bht_Fk", "dxf_layer")
    check(not m, "el nombre compuesto no resuelve solo: va a pendientes", m)
    prop = gw.pending_aliases[gw._norm_txt("Bht_Fk")]["propuesta"]
    check(prop and prop["atributos"] == {"litologia": "Bht", "alteracion": "Fk"},
          "A.3 propone la descomposición correcta", prop)
    # Y solo tras CONFIRMAR se aplica.
    al = gw.confirm_composite_alias("Bht_Fk", "dxf_layer")
    gw.set_layer_attributes(lay, al.atributos)
    gw.layers["Bht_Fk"] = lay
    p_dxf = clasificar([DENTRO])[0]
    dxf = (p_dxf.dominio, p_dxf.lito, p_dxf.alteracion, p_dxf.ambiguo,
           gw.domains[p_dxf.dominio]["ucs_lab"])
    check(dxf == sep,
          "la malla compuesta LEÍDA DE DXF da el mismo resultado que dos mallas",
          f"dxf={dxf} separadas={sep}")

    # (c) Traslape parcial: solo la intersección se compone.
    reset()
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    mk_layer("caja_Bht", BOX_GRANDE, {"litologia": "Bht"})
    mk_layer("caja_Fk", BOX_CRUZADA, {"alteracion": "Fk"})
    solo_lito = (E0 + 1.0, N0 + 2.0, Z0 + 1.0)     # dentro de GRANDE, fuera de CRUZADA
    pts = clasificar([DENTRO, solo_lito])
    check(pts[0].dominio == "Bht~Fk", "en la intersección: dominio compuesto",
          pts[0].dominio)
    check(pts[1].dominio == "Bht", "fuera de la alteración: dominio simple",
          pts[1].dominio)
    check(gw.domains["Bht"]["ucs_lab"] == gw.domains["Bht~Fk"]["ucs_lab"] == 150.0,
          "ambos dominios heredan la MISMA banda de la litología",
          (gw.domains["Bht"]["ucs_lab"], gw.domains["Bht~Fk"]["ucs_lab"]))
    check(pts[0].dominio != pts[1].dominio,
          "pero son dominios DISTINTOS: si el MWD los separa, es un hallazgo")


def caso7_fuera_de_todo():
    section("Caso 7 — Punto fuera de todo: sin clasificar, contabilizado")
    reset()
    mk_layer("caja_Bht", BOX_GRANDE, {"litologia": "Bht"})
    pts = clasificar([DENTRO, FUERA])
    check(pts[0].dominio == "Bht", "el interior sí clasifica", pts[0].dominio)
    check(pts[1].dominio is None, "el exterior queda sin dominio", pts[1].dominio)
    check(not pts[1].ambiguo, "sin dominio NO es lo mismo que ambiguo")
    check(gw.overlap_stats["n_sin_lito"] == 1,
          "se contabiliza como sin litología", gw.overlap_stats["n_sin_lito"])
    check(gw.overlap_stats["n_sin_clasificar"] == 1,
          "y como sin clasificar", gw.overlap_stats["n_sin_clasificar"])
    check(gw.overlap_stats["n_puntos"] == 2, "el total cuadra")


def contador_en_reporte():
    section("El contador de ambiguos es accesible desde el reporte de entrenamiento")
    reset()
    gw.attr_registry["Kfa"].ucs_media = 289.6
    gw.attr_registry["Bht"].ucs_media = 150.0
    gw.attr_registry["Bht"].calidad = 3
    mk_layer("caja_Kfa", BOX_GRANDE, {"litologia": "Kfa"})
    mk_layer("caja_Bht", BOX_CRUZADA, {"litologia": "Bht"})
    # Un punto en conflicto + varios limpios dentro de solo una caja.
    limpios = [(E0 + 1.0, N0 + 2.0, Z0 + 1.0 + i * 0.01) for i in range(30)]
    clasificar([DENTRO] + limpios)
    check(gw.overlap_stats["n_ambiguos"] >= 1, "hay al menos un ambiguo",
          gw.overlap_stats["n_ambiguos"])
    st = gw.train_rf(0.0, 450.0)
    check("n_excl_ambiguo" in st,
          "rf_stats expone n_excl_ambiguo", list(st)[:12])
    check(st.get("n_excl_ambiguo") == gw.overlap_stats["n_ambiguos"],
          "y coincide con overlap_stats", (st.get("n_excl_ambiguo"),
                                           gw.overlap_stats["n_ambiguos"]))
    check("overlap_motivos" in st and st["overlap_motivos"],
          "el reporte incluye los motivos de exclusión", st.get("overlap_motivos"))


def banda_excel_sigue_evaluando():
    """
    Desde que el dominio se expresa en atributos canónicos, un punto lleva
    p.lito = "Bht" aunque su capa se llame "Bht_Fk". La verificación de banda
    (T3) empareja contra el Excel geomecánico por texto: sin resolución por
    alias dejaría de evaluar EN SILENCIO al asignar vocabulario a una capa.
    """
    section("Regresión — la banda del Excel sigue evaluando con vocabulario asignado")
    reset()
    gw.index_geomech_bands([{
        "caseron": "MPC_1", "litologia": "Brecha Hidrotermal",
        "ucs_lo": 120.0, "ucs_mid": 150.0, "ucs_hi": 180.0,
        "rmr_raw": None, "rqd_lo": None, "rqd_mid": None, "rqd_hi": None,
        "gsi_raw": None,
    }])
    lay = mk_layer("Bht_Fk", BOX_GRANDE, {"litologia": "Bht", "alteracion": "Fk"})
    lay.caseron = "MPC_1"

    check(gw.lookup_band("MPC_1", "Bht") is not None,
          "el id canónico Bht empareja con la fila «Brecha Hidrotermal» del Excel",
          gw.lookup_band("MPC_1", "Bht"))
    check(gw._resolve_caseron("Bht") == "MPC_1",
          "el caserón se resuelve desde una capa llamada Bht_Fk",
          gw._resolve_caseron("Bht"))

    p = clasificar([DENTRO])[0]
    p.ucs_ml, p.ucs_ml_p10, p.ucs_ml_p90 = 150.0, 140.0, 160.0
    gw.band_consistency()
    check(p.band_check == "compatible",
          "la verificación de banda SIGUE evaluando (no cae a None en silencio)",
          p.band_check)

    # Y un intervalo fuera de la banda se declara incompatible, no ambiguo.
    p.ucs_ml, p.ucs_ml_p10, p.ucs_ml_p90 = 300.0, 290.0, 310.0
    gw.band_consistency()
    check(p.band_check == "incompatible",
          "un intervalo fuera de la banda se declara incompatible", p.band_check)
    gw.index_geomech_bands([])
    reset()


def guardian_sigue_vivo():
    section("A.7 — El guardián de sitio sigue activo para las cajas de test")
    reset()
    gw.allow_site_fixtures(False)
    # Las cajas de estos tests están DENTRO de MPC: no deben disparar nada.
    v = gw.site_guard(E0 + 10, N0 + 10, "caja_test", "malla DXF")
    check(v["ok"], "las cajas sintéticas caen dentro de MPC", v["dist_m"])


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada para pytest: corre todas las comprobaciones y falla si
# alguna no pasó. Así esta suite cuenta en `pytest` igual que en ejecución
# directa, en vez de quedar invisible por no llamarse test_*.
def test_a6_traslape():
    FAILURES.clear()
    caso1_anidamiento()
    caso2_conflicto_unidades()
    caso3_conflicto_subunidades()
    caso4_composicion()
    caso5_predominio()
    caso6_equivalencia_empaquetado()
    caso7_fuera_de_todo()
    contador_en_reporte()
    banda_excel_sigue_evaluando()
    guardian_sigue_vivo()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    caso1_anidamiento()
    caso2_conflicto_unidades()
    caso3_conflicto_subunidades()
    caso4_composicion()
    caso5_predominio()
    caso6_equivalencia_empaquetado()
    caso7_fuera_de_todo()
    contador_en_reporte()
    banda_excel_sigue_evaluando()
    guardian_sigue_vivo()

    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ A.6 COMPLETO — los siete casos de traslape pasan.")
    print("=" * 72)
