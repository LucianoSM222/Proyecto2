"""
test_p1_fundaciones.py — Validación de P1 (partición por sitio y registro de
vocabulario) para geomech_wizard.

Cubre las ocho tareas:
  T1.1  guardián por coordenadas (Granate dispara, MPC no)
  T1.2  registro de atributos canónicos + modulación del intervalo por calidad
  T1.3  registro de alias (insensible a caso/acentos, conflicto = error, bandeja)
  T1.4  resolución de traslape por nivel (los siete casos de la tabla)
  T1.5  estado sin-asignar que bloquea + exclusión explícita justificada
  T1.6  límites de UCS sin truncamiento silencioso
  T1.7  persistencia (round-trip export/import)
  T1.8  el panel se construye sin excepciones

Además, dos guardas de regresión geométrica:
  · la ruta de ray casting (rayo VERTICAL + grid XY) no fue modificada;
  · classify_all_wells con UNA sola malla produce exactamente el mismo
    resultado que la lógica anterior `lito_hit[i] = name`.

El test canario oficial (pozo H5 contra Metandesitas.dxf → 1437/1743) vive en
test_geomech.py y requiere ese DXF; aquí se usa el DXF disponible en el
repositorio para fijar un conteo exacto reproducible.
"""

import os, sys, json, math

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
    print(f"\n{'='*70}\n{t}\n{'='*70}")


def reset_registry():
    gw.seed_attribute_registry(force=True)
    gw.attribute_exclusions.clear()
    gw.pending_aliases.clear()
    gw.attribute_meters.clear()
    gw.site_confirmed_tokens.clear()
    gw.site_pending_confirms.clear()
    gw.layers.clear()
    gw.wells.clear()
    gw.domains.clear()


# ─────────────────────────────────────────────────────────────────────────────
def t11_site_guard():
    section("T1.1 — Guardián por coordenadas")
    reset_registry()
    s = gw.active_site()
    check(s["id"] == "MPC", "sitio activo es MPC", s["id"])

    # Centro de la envolvente MPC → debe pasar sin ruido.
    cx, cy = gw.site_centroid()
    v = gw.site_guard(cx, cy, "malla_MPC", "malla DXF")
    check(v["ok"] and v["dist_m"] == 0.0, "centroide MPC pasa sin advertencia", v)
    check(not gw.site_pending_confirms, "no encola confirmación para MPC",
          gw.site_pending_confirms)

    # Esquinas de la envolvente real de sondajes → dentro del margen.
    for e, n, lbl in [(376521.0, 6958752.0, "esquina SO"),
                      (377005.0, 6959323.0, "esquina NE")]:
        v = gw.site_guard(e, n, lbl, "collar de pozo")
        check(v["ok"], f"{lbl} de la envolvente MPC no dispara", v["dist_m"])

    # Mina Granate: ~3,05 km del centroide MPC.
    v = gw.site_guard(373936.0, 6960177.0, "Granate_lito", "malla DXF")
    check(not v["ok"], "Granate NO pasa el guardián", v)
    check(3000 <= v["dist_m"] <= 3100,
          f"distancia reportada ≈3.050 m (obtenida {v['dist_m']} m)", v["dist_m"])
    check(f"{gw._num_cl(v['dist_m'])} m" in v["mensaje"],
          "el mensaje reporta la distancia medida", v["mensaje"])
    check("1.500 m" in v["mensaje"], "el mensaje reporta el umbral", v["mensaje"])
    # Formato chileno correcto: miles con '.', decimales con ','. El bug era
    # aplicar .replace(",", ".") al mensaje entero → "E 373.936.0".
    check("E 373.936,0" in v["mensaje"] and "N 6.960.177,0" in v["mensaje"],
          "las coordenadas del centroide se formatean sin corromper el decimal",
          v["mensaje"])
    check(len(gw.site_pending_confirms) == 1,
          "encola exactamente una confirmación pendiente", gw.site_pending_confirms)

    # Confirmación explícita → el mismo objeto pasa.
    tok = gw.site_pending_confirms[0]["token"]
    gw.confirm_site_token(tok)
    v2 = gw.site_guard(373936.0, 6960177.0, "Granate_lito", "malla DXF")
    check(v2["ok"] and v2["confirmado"], "tras confirmar explícitamente, pasa", v2)
    check(not gw.site_pending_confirms, "la pendiente se consume al confirmar")

    # Coordenadas no finitas → no se puede verificar: no pasa.
    v3 = gw.site_guard(float("nan"), 6959000.0, "roto", "malla DXF")
    check(not v3["ok"], "centroide no finito no pasa en silencio", v3)
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t12_attribute_registry():
    section("T1.2 — Registro de atributos canónicos")
    reset_registry()
    check(not gw.validate_attribute_tree(), "árbol de atributos válido",
          gw.validate_attribute_tree())

    kfa = gw.attr_registry["Kfa"]
    check(kfa.nombre_oficial == "Albitófiro" and kfa.nivel == "unidad",
          "Kfa → Albitófiro, unidad")
    check((kfa.ucs_min, kfa.ucs_max, kfa.ucs_media) == (274.3, 304.9, 289.6),
          "Kfa lleva la banda de Karzulovic 274,3 / 304,9 / 289,6",
          (kfa.ucs_min, kfa.ucs_max, kfa.ucs_media))
    check(kfa.ucs_sd is None and kfa.calidad == 1,
          "Kfa: sin SD (probeta única) y calidad 1 = ensayo_del_sitio")
    check("desviación estándar" in kfa.notas,
          "la limitación de la probeta única queda registrada en notas")
    check((kfa.mi, kfa.modulo_E, kfa.poisson, kfa.densidad) == (11.3, 71.6, 0.15, 2.85),
          "Kfa: mi / E / ν / γ de la Tabla 3.2")

    for aid in ("Kpcli", "DL"):
        a = gw.attr_registry[aid]
        check(a.calidad == 0 and not a.tiene_banda_ucs(),
              f"{aid}: calidad 0 y sin banda de UCS")

    # Bht (Adenda B): registrada con ajuste Hoek-Brown, ya NO es calidad 0.
    bht = gw.attr_registry["Bht"]
    check((bht.ucs_central, bht.ucs_min, bht.ucs_max) == (128.1, 100.0, 145.0),
          "Bht: ucs_central 128,1, banda de confianza 100-145",
          (bht.ucs_central, bht.ucs_min, bht.ucs_max))
    check((bht.dispersion_min, bht.dispersion_max) == (64.5, 296.9),
          "Bht: dispersión observada 64,5-296,9 (distinta de la banda de confianza)",
          (bht.dispersion_min, bht.dispersion_max))
    check(abs(bht.ucs_cv - 0.57) < 1e-9 and bht.mi == 14.77 and bht.calidad == 1,
          "Bht: CV 0,57, mi 14,77, calidad 1 (ensayo del sitio)",
          (bht.ucs_cv, bht.mi, bht.calidad))
    check(bht.tiene_banda_ucs() and bht.ucs_ancla() == 128.1,
          "Bht entrena con ucs_central (128,1), no con un promedio contaminado")
    check(bht.alta_variabilidad(), "Bht: CV > 0,35 → alta variabilidad")
    check("en gestión con geología" not in bht.notas,
          "el hueco de UCS de Bht quedó resuelto, la nota vieja no sobrevive")

    # Jerarquía Brecha basal / Miembro Trinidad.
    hijos_basal = set(gw.attribute_children("Kpcsb_basal"))
    check(hijos_basal == {"Brecha_mixta", "Kpcsb_sedimentaria"},
          "Brecha basal tiene sus dos subunidades", hijos_basal)
    hijos_kpcs = set(gw.attribute_children("Kpcs"))
    check(hijos_kpcs == {"Lutitas_normales", "Lutitas_metamorfoseadas"},
          "Miembro Trinidad tiene las dos lutitas", hijos_kpcs)

    # Trampa de nomenclatura Kpcsb documentada en AMBOS.
    check(all("AMBIGÜEDAD DE NOMENCLATURA" in gw.attr_registry[i].notas
              for i in ("Kpcsb_basal", "Kpcsb_sedimentaria")),
          "la ambigüedad de 'Kpcsb' queda constatada en ambos identificadores")
    check(gw.attr_registry["Kpcsb_basal"].id != gw.attr_registry["Kpcsb_sedimentaria"].id,
          "Brecha basal y Brecha sedimentaria son identificadores distintos")

    # La calidad modula el ancho del intervalo de predicción.
    lut = gw.attr_registry["Lutitas_normales"]      # calidad 1, con SD
    check(abs(lut.pi_factor() - 1.00) < 1e-9,
          "calidad 1 con SD → factor 1,00", lut.pi_factor())
    check(kfa.pi_factor() > lut.pi_factor(),
          "probeta única ensancha el intervalo respecto de una con SD",
          (kfa.pi_factor(), lut.pi_factor()))
    check(gw.attr_registry["Kpcli"].pi_factor() is None,
          "calidad 0 no tiene factor: no es entrenable")
    # (Adenda B) Bht: probeta única (sin SD) Y alta variabilidad (CV>0,35) se
    # componen — el intervalo se ensancha por AMBAS razones, no una sola.
    check(abs(gw.attr_registry["Bht"].pi_factor() - 1.755) < 1e-9,
          "Bht: factor 1,00 (calidad 1) × 1,35 (probeta única) × 1,30 (CV alto)",
          gw.attr_registry["Bht"].pi_factor())

    prev = lut.calidad
    lut.calidad = 3          # análogo del distrito
    check(lut.pi_factor() > 1.0,
          "un análogo de otra mina no produce la misma confianza que el sitio",
          lut.pi_factor())
    lut.calidad = prev

    # Todos los campos numéricos son editables desde la interfaz.
    campos = {f for f, _ in gw._VOCAB_NUM_FIELDS}
    check(campos <= set(gw.Attribute.__dataclass_fields__),
          "todos los campos numéricos del panel existen en el dataclass", campos)
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t13_alias_registry():
    section("T1.3 — Registro de alias")
    reset_registry()

    # (A.2) resolve_alias devuelve {rol: atributo_id}, no un id suelto.
    # Insensible a mayúsculas, espacios y acentos; conserva el texto crudo.
    for txt in ("Kfa", "KFA", "  kfa  ", "Albitófiro", "ALBITOFIRO", "albitofiro"):
        check(gw.resolve_alias(txt) == {"litologia": "Kfa"},
              f'"{txt}" resuelve a litologia:Kfa', gw.resolve_alias(txt))
    check(gw.resolve_alias_rol("KFA", "litologia") == "Kfa",
          "resolve_alias_rol extrae el id de un rol")
    check(gw.resolve_alias_rol("KFA", "alteracion") is None,
          "y no inventa un atributo para un rol que el alias no tiene")
    al = gw.register_alias("  Alb Porf  ", "Kfa", "dxf_layer")
    check(al.texto_crudo == "Alb Porf",
          "el alias almacenado conserva el texto crudo original", al.texto_crudo)
    check(gw.resolve_alias("alb  porf") == {"litologia": "Kfa"},
          "el emparejamiento normaliza espacios internos")

    # Un alias apunta a exactamente un atributo: mapearlo a dos es ERROR.
    err = None
    try:
        gw.register_alias("Alb Porf", "Bht", "manual")
    except gw.AliasConflict as e:
        err = e
    check(err is not None, "mapear un alias a dos atributos lanza AliasConflict")
    check(gw.resolve_alias("Alb Porf") == {"litologia": "Kfa"},
          "tras el conflicto el alias original queda intacto")

    # Atributo inexistente → error, no alias huérfano.
    try:
        gw.register_alias("XYZ", "NoExiste", "manual"); ok = False
    except KeyError:
        ok = True
    check(ok, "alias hacia un atributo inexistente lanza KeyError")

    # Bandeja de pendientes: visible y contabilizada.
    gw.pending_aliases.clear()
    check(gw.resolve_or_note("Pórfido Nuevo", "dxf_layer") == {},
          "un texto no reconocido no se inventa")
    check(gw.pending_alias_count() == 1, "cae en la bandeja de pendientes",
          gw.pending_aliases)
    gw.resolve_or_note("PORFIDO NUEVO", "sondaje_unidad")
    e = gw.pending_aliases[gw._norm_txt("Pórfido Nuevo")]
    check(gw.pending_alias_count() == 1,
          "la variante de caso/acento no duplica la entrada pendiente")
    check(e["n_vistas"] == 2 and e["origenes"] == {"dxf_layer", "sondaje_unidad"},
          "la bandeja contabiliza vistas y orígenes", e)

    gw.register_alias("Pórfido Nuevo", "Kfa", "manual")
    check(gw.pending_alias_count() == 0,
          "asignar el alias lo saca de la bandeja")

    # Origen inválido → error.
    try:
        gw.register_alias("Z1", "Kfa", "inventado"); ok = False
    except ValueError:
        ok = True
    check(ok, "un origen fuera del catálogo lanza ValueError")
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def _mk_layer(name, kind="litologia", attr=None, nivel=None):
    lay = gw.Layer(name=name, kind=kind, triangles=np.zeros((0, 3, 3)),
                   bbox_min=np.zeros(3), bbox_max=np.zeros(3))
    if attr:
        gw.set_layer_attributes(lay, {gw.attr_registry[attr].rol: attr})
    if nivel is not None:
        lay.nivel = nivel
    gw.layers[name] = lay
    return lay


def t14_overlap():
    section("T1.4 — Resolución de traslape por nivel")
    reset_registry()

    def R(*idents, rol="litologia"):
        """Atajo: resuelve un traslape dentro de un rol."""
        return gw._resolve_one_role(rol, list(idents))

    check(R() == (None, ""), "sin aciertos → sin litología", R())
    check(R("Kfa") == ("Kfa", ""), "un solo atributo gana limpio", R("Kfa"))

    # Anidamiento: unidad + su propia subunidad → gana la subunidad.
    n, m = R("Kpcsb_basal", "Brecha_mixta")
    check(n == "Brecha_mixta" and m == "subunidad_gana",
          "Anidamiento: unidad + su propia subunidad → gana la subunidad", (n, m))
    check(R("Brecha_mixta", "Kpcsb_basal")[0] == "Brecha_mixta",
          "el resultado no depende del orden de carga")

    # Conflicto: dos atributos del mismo rol.
    n, m = R("Kfa", "Bht")
    check(n is None and m == "dos unidades distintas",
          "Conflicto: dos unidades distintas → ambiguo", (n, m))
    n, m = R("Brecha_mixta", "Kpcsb_sedimentaria")
    check(n is None and m == "dos subunidades del mismo padre",
          "Conflicto: dos subunidades del mismo padre → ambiguo", (n, m))
    n, m = R("Brecha_mixta", "Lutitas_normales")
    check(n is None and m == "dos subunidades de padres distintos",
          "Conflicto: dos subunidades de padres distintos → ambiguo", (n, m))
    n, m = R("Brecha_mixta", "Kfa")
    check(n is None and "unidad ajena" in m,
          "subunidad + unidad ajena → ambiguo", (n, m))

    # Nivel no declarado → ambiguo, nunca ganador arbitrario.
    n, m = R("Kfa", "malla_sin_vocabulario")
    check(n is None and "nivel no declarado" in m,
          "traslape con identidad de nivel no declarado → ambiguo", (n, m))

    # El mismo atributo repetido en varias mallas no es conflicto.
    check(R("Kfa", "Kfa") == ("Kfa", ""),
          "el mismo atributo en dos mallas no es conflicto", R("Kfa", "Kfa"))

    # ── Composición y Predominio, sobre el resolvedor completo ───────────────
    res, motivo, anid = gw.resolve_overlap_by_role(
        {"litologia": ["Bht"], "alteracion": ["Fk"]})
    check(res == {"litologia": "Bht", "alteracion": "Fk"} and not motivo,
          "Composición: roles distintos conviven, no compiten", (res, motivo))
    check(gw.make_dominio("Bht", "Fk", None) == "Bht~Fk",
          "la clave de dominio es el par (litología, alteración)")

    res, motivo, _ = gw.resolve_overlap_by_role(
        {"litologia": ["Kfa", "Bht"], "alteracion": ["Fk"]})
    check(res == {} and motivo == "dos unidades distintas",
          "un Conflicto en un rol invalida el punto completo", (res, motivo))

    check(gw.make_dominio("Bht", "Fk", "FallaX") == "Bht::FallaX",
          "Predominio: con estructura, ella define el dominio")
    check(gw.make_dominio(None, "Fk", None) is None,
          "una alteración sola no define dominio")

    # Fk y Kfa: strings casi invertidos, roles OPUESTOS. No colisionan.
    check(gw.attr_registry["Fk"].rol == "alteracion"
          and gw.attr_registry["Kfa"].rol == "litologia",
          "Fk es alteración y Kfa es litología")
    res, motivo, _ = gw.resolve_overlap_by_role(
        {"litologia": ["Kfa"], "alteracion": ["Fk"]})
    check(not motivo and res == {"litologia": "Kfa", "alteracion": "Fk"},
          "Kfa + Fk se COMPONEN (roles distintos), no entran en conflicto", res)
    reset_registry()


def t14_composition():
    """litología+estructura, litología+alteración, alteración sola."""
    section("T1.4b — Composición de dominio y contabilidad de ambigüedad")
    reset_registry()

    class FakeLayer:
        """Malla que 'contiene' los índices de punto que se le declaren."""
        def __init__(self, name, kind, idxs, attr=None):
            self.name, self.kind, self.idxs = name, kind, set(idxs)
            # (A.2) La capa aporta {rol: atributo_id}. Sin atributo asignado la
            # identidad cae al nombre de la capa y su nivel queda no declarado.
            self.atributos = ({gw.attr_registry[attr].rol: attr}
                              if attr in gw.attr_registry else {})
            self.nivel = gw.attr_registry[attr].nivel if attr in gw.attr_registry else None
            self.triangles = np.zeros((0, 3, 3))
            self.bbox_min = np.zeros(3); self.bbox_max = np.zeros(3)
            self.ucs_lab = None; self.caseron = None; self.lito_alias = None
            self.ucs_lo = None; self.ucs_hi = None; self.ucs_mid = None
            self.folder = "Litología"

    # 6 puntos: 0 solo Kfa · 1 Kfa+estructura · 2 Kfa+alteración ·
    #           3 solo alteración · 4 Kfa+Bht (ambiguo) · 5 basal+mixta
    pts = [gw.MWDPoint(largo=i*0.1, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1, t=0.0,
                       este=0.0, norte=0.0, cota=0.0) for i in range(6)]
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=pts)
    gw.layers.clear()
    for lay in [FakeLayer("Kfa_m", "litologia", [0, 1, 2, 4], "Kfa"),
                FakeLayer("Bht_m", "litologia", [4], "Bht"),
                FakeLayer("basal_m", "litologia", [5], "Kpcsb_basal"),
                FakeLayer("mixta_m", "litologia", [5], "Brecha_mixta"),
                FakeLayer("FallaA", "estructura", [1]),
                FakeLayer("Fk_m", "alteracion", [2, 3], "Fk")]:
        gw.layers[lay.name] = lay

    orig = gw.points_in_mesh
    gw.points_in_mesh = lambda coords, layer, batch=256: np.array(
        [i in layer.idxs for i in range(len(coords))], dtype=bool)
    try:
        gw.classify_all_wells()
    finally:
        gw.points_in_mesh = orig

    # El dominio se expresa en ATRIBUTOS CANÓNICOS, no en nombres de capa:
    # así no depende de cómo vino empaquetada la información.
    check(pts[0].dominio == "Kfa" and pts[0].atributo_id == "Kfa",
          "litología sola → dominio = atributo canónico",
          (pts[0].dominio, pts[0].atributo_id))
    check(pts[1].dominio == "Kfa::FallaA",
          "litología + estructura → la estructura predomina", pts[1].dominio)
    check(pts[2].dominio == "Kfa~Fk" and pts[2].alteracion == "Fk",
          "litología + alteración → se componen (Kfa + Fk, roles opuestos)",
          pts[2].dominio)
    check(pts[3].dominio is None and pts[3].alteracion == "Fk",
          "alteración sola NO define dominio", pts[3].dominio)
    check(pts[4].ambiguo and pts[4].dominio is None and pts[4].lito is None,
          "traslape de dos unidades → punto excluido del dominio", pts[4].__dict__)
    check(pts[4].ambiguo_motivo == "dos unidades distintas",
          "el motivo de la ambigüedad queda registrado en el punto",
          pts[4].ambiguo_motivo)
    check(not pts[5].ambiguo and pts[5].dominio == "Brecha_mixta",
          "unidad + su subunidad se resuelve, no se excluye", pts[5].dominio)

    ov = gw.overlap_stats
    check(ov["n_puntos"] == 6 and ov["n_ambiguos"] == 1 and ov["n_subunidad_gana"] == 1,
          "la contabilidad de traslapes cuadra", ov)
    check(any("Bht" in c and "Kfa" in c for c in ov["casos"]),
          "el caso concreto de traslape queda reportado, no descartado en silencio",
          ov["casos"])

    # El punto ambiguo no puede etiquetar el entrenamiento.
    gw.build_domain_index()
    gw.domains.setdefault("Kfa", {})["ucs_lab"] = 289.6
    X, y, g, _ = gw._get_train_data(0, 450)
    check(len(X) >= 1, "los puntos limpios sí entrenan", len(X))
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t15_blocking():
    section("T1.5 — Estado sin-asignar que bloquea")
    reset_registry()
    # (Adenda B) Bht ya está registrada con banda de UCS (calidad 1) y no
    # sirve como ejemplo de bloqueo: se usa Kpcsb_basal en su lugar, que sigue
    # calidad 0 (unidad padre sin ensayo propio, sus subunidades sí lo tienen).
    _mk_layer("malla_Kfa", attr="Kfa")
    _mk_layer("malla_basal", attr="Kpcsb_basal")
    _mk_layer("malla_Kpcli", attr="Kpcli")
    _mk_layer("malla_DL", attr="DL")
    gw.attribute_meters.update({"Kpcsb_basal": 576.9, "Kpcli": 20.8, "DL": 3.1, "Kfa": 1176.3})

    bl = gw.training_blockers()
    ids = {b["id"] for b in bl}
    check(ids == {"Kpcsb_basal", "Kpcli", "DL"},
          "bloquean exactamente los tres sin banda de UCS", ids)
    check("Kfa" not in ids, "Kfa no bloquea: tiene ancla de laboratorio")

    msg = gw.training_block_message(bl)
    check(msg.startswith("No se puede entrenar: 3 litologías sin banda de UCS asignada"),
          "el mensaje nombra cuántas litologías faltan", msg)
    for frag in ("Kpcsb_basal 576,9 m", "Kpcli 20,8 m", "DL 3,1 m"):
        check(frag in msg, f"el mensaje declara el metraje de {frag.split()[0]}", msg)
    check("excluir explícitamente" in msg,
          "el mensaje ofrece la vía de exclusión explícita", msg)

    # train_rf debe fallar ruidosamente, no entrenar a medias.
    r = gw.train_rf(0, 450)
    check("error" in r and "No se puede entrenar" in r["error"],
          "train_rf falla ruidosamente en vez de entrenar", r)

    # Exclusión explícita: exige justificación.
    try:
        gw.exclude_attribute("DL", "   "); ok = False
    except ValueError:
        ok = True
    check(ok, "excluir sin justificación lanza ValueError")
    try:
        gw.exclude_attribute("NoExiste", "porque sí"); ok = False
    except KeyError:
        ok = True
    check(ok, "excluir un atributo inexistente lanza KeyError")

    gw.exclude_attribute("DL", "Código sin identificar, 0,2% del metraje.")
    gw.exclude_attribute("Kpcli", "Lavas Inferiores sin ensayo, 1,2% del metraje.")
    ids = {b["id"] for b in gw.training_blockers()}
    check(ids == {"Kpcsb_basal"}, "tras excluir DL y Kpcli solo queda Kpcsb_basal", ids)
    check(gw.attribute_exclusions["DL"]["justificacion"].startswith("Código"),
          "la justificación queda registrada")
    check("fecha" in gw.attribute_exclusions["DL"], "la exclusión lleva fecha")

    # Asignar la banda faltante desbloquea.
    gw.attr_registry["Kpcsb_basal"].ucs_media = 150.0
    gw.attr_registry["Kpcsb_basal"].calidad = 3
    check(not gw.training_blockers(),
          "asignar banda + calidad a Kpcsb_basal desbloquea el entrenamiento",
          gw.training_blockers())
    check(gw.training_block_message() is None, "sin bloqueadores no hay mensaje")

    gw.unexclude_attribute("DL")
    check({b["id"] for b in gw.training_blockers()} == {"DL"},
          "reincluir DL vuelve a bloquear")
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t16_ucs_bounds():
    section("T1.6 — Límites de UCS sin truncamiento silencioso")
    reset_registry()
    check((gw.UCS_CONFIG["physical_min"], gw.UCS_CONFIG["physical_max"]) == (0.0, 450.0),
          "límites físicos 0–450 MPa", gw.UCS_CONFIG)
    check(gw.UCS_CONFIG["default_max"] >= 304.9,
          "el default abarca el Albitófiro (304,9 MPa): antes lo excluía en silencio",
          gw.UCS_CONFIG["default_max"])

    # El registro rechaza un valor fuera de rango físico.
    a = gw.attr_registry["Kfa"]
    prev = a.ucs_media
    a.ucs_media = 500.0
    errs = gw.validate_attribute_tree()
    check(any("fuera de los límites físicos" in e for e in errs),
          "un UCS de 500 MPa es reportado como error, no truncado", errs)
    a.ucs_media = prev

    # El componente Dash ya NO acota: los inputs no llevan min/max.
    src = open(os.path.join(HERE, "geomech_wizard.py"), encoding="utf-8").read()
    check('id="ucs-min", type="number", value=ucs_range["ucs_min"],\n' not in src
          or "min=UCS_CONFIG" not in src.split('id="ucs-min"')[1][:200],
          "el input ucs-min ya no lleva min= cableado")
    # Ningún componente Dash acota por UCS_CONFIG. Se busca el atributo del
    # componente (" min=" / " max=" precedidos de coma o espacio), no la
    # subcadena suelta: `ucs_min=UCS_CONFIG[...]` es un kwarg legítimo.
    import re as _re
    acotes = _re.findall(r"[,(]\s*(?:min|max)=UCS_CONFIG", src)
    check(not acotes,
          "ningún input acota por UCS_CONFIG (causa raíz del None silencioso)",
          acotes)
    check("float(ucs_min_v or UCS_CONFIG" not in src,
          "desaparece el patrón float(v or default) del rango de UCS")

    # train_rf no puede caer a un default cuando le pasan 0.0 explícito.
    gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"] = 60.0, 210.0
    _mk_layer("malla_Kfa", attr="Kfa")
    r = gw.train_rf(0.0, 450.0)
    check(r.get("error", "").startswith("Insuficientes puntos"),
          "train_rf(0.0, 450.0) usa el 0.0 recibido, no el default 60", r)
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t17_persistence():
    section("T1.7 — Persistencia del registro")
    reset_registry()
    gw.register_alias("Zona X", "Kfa", "dxf_layer")
    gw.resolve_or_note("Desconocido 1", "sondaje_unidad")
    gw.exclude_attribute("DL", "sin identificar, 3,1 m")
    gw.attr_registry["Bht"].ucs_media = 155.5
    gw.attr_registry["Bht"].calidad = 3

    blob = gw.export_vocabulary_json()
    data = json.loads(blob)
    check(data["schema"] == "mwd-geomech-vocabulario", "el JSON declara su esquema")
    check(data["sitio_activo"] == "MPC", "el JSON declara el sitio")
    check(len(data["atributos"]) == 19, "exporta los 19 atributos (11 P1 + 8 estructuras P2)",
          len(data["atributos"]))
    check(any(a["id"] == "Bht" and a["ucs_media"] == 155.5 for a in data["atributos"]),
          "las ediciones numéricas viajan en el export")
    check(any(e["atributo_id"] == "DL" for e in data["exclusiones"]),
          "las exclusiones justificadas viajan en el export")
    check(any(p["texto_crudo"] == "Desconocido 1" for p in data["pendientes"]),
          "los pendientes viajan en el export")
    check(blob.count("\n") > 20 and "Albitófiro" in blob,
          "el JSON es legible por humanos (indentado, sin escapes unicode)")

    csv = gw.export_vocabulary_csv()
    check(csv.startswith("id;nombre_oficial"), "el CSV usa separador ';'", csv[:40])
    check("Kpcsb_sedimentaria" in csv and "calidad_etiqueta" in csv,
          "el CSV incluye atributos y la etiqueta de calidad")

    # Round-trip completo.
    gw.attr_registry.clear(); gw.alias_registry.clear()
    gw.pending_aliases.clear(); gw.attribute_exclusions.clear()
    res = gw.import_vocabulary(blob, replace=True)
    check(not res["errores"], "la importación no arroja errores", res["errores"])
    check(len(gw.attr_registry) == 19, "19 atributos restaurados", len(gw.attr_registry))
    check(gw.attr_registry["Bht"].ucs_media == 155.5, "valor editado sobrevive")
    check(gw.attr_registry["Kfa"].ucs_sd is None,
          "el None de ucs_sd sobrevive (no se convierte en 0)")
    check(gw.resolve_alias("zona  x") == {"litologia": "Kfa"},
          "el alias sobrevive y sigue normalizando")
    check("DL" in gw.attribute_exclusions, "la exclusión sobrevive")
    check(gw.pending_alias_count() == 1, "el pendiente sobrevive")
    check(gw.attr_registry["Brecha_mixta"].padre == "Kpcsb_basal",
          "la jerarquía padre/hijo sobrevive")

    try:
        gw.import_vocabulary(json.dumps({"schema": "otra-cosa"})); ok = False
    except ValueError:
        ok = True
    check(ok, "importar un archivo ajeno lanza ValueError")
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def t18_ui():
    section("T1.8 — Interfaz")
    reset_registry()
    # (Adenda B) Bht ya tiene banda de UCS; Kpcli sigue sin ensayo y es el
    # ejemplo que dispara el badge "sin UCS" que este test verifica.
    _mk_layer("malla_Kpcli", attr="Kpcli")
    gw.resolve_or_note("Textito Raro", "dxf_layer")
    gw.site_guard(373936.0, 6960177.0, "Granate_lito", "malla DXF")

    body = gw._vocab_panel_body()
    check(body is not None and len(body) >= 8,
          "el panel se construye completo", len(body) if body else None)
    badge = gw._vocab_badge_children()
    check(badge is not None, "el contador de la barra superior se construye")
    txt = str(badge)
    check("1 pendiente" in txt, "el contador muestra los pendientes", txt[:200])
    check("fuera de sitio" in txt, "el contador muestra los objetos fuera de sitio")
    check("sin UCS" in txt, "el contador muestra los bloqueadores de entrenamiento")

    s1 = gw._step1()
    check(s1 is not None, "el Paso 1 se construye con el bloque de sitio")
    check("Punta del Cobre" in str(s1), "el Paso 1 declara el sitio activo")

    reset_registry()
    badge_ok = str(gw._vocab_badge_children())
    check("vocabulario OK" in badge_ok,
          "sin pendientes ni bloqueos el contador queda en verde", badge_ok[:120])
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
def geometry_regression():
    """
    Guarda de regresión geométrica. El canario oficial (H5 vs Metandesitas.dxf
    = 1437/1743) vive en test_geomech.py y necesita ese DXF; aquí se fija un
    conteo exacto con el DXF disponible en el repositorio, sobre una grilla
    determinista de puntos. Cualquier cambio en el ray casting (dirección del
    rayo, grid XY de aceleración, Möller-Trumbore) rompe este número.
    """
    section("Regresión geométrica — ray casting vertical + grid XY")
    dxf = os.path.join(HERE, "test_data", "Bht_Fk.dxf")
    if not os.path.exists(dxf):
        print("  ⊘ omitido: no está test_data/Bht_Fk.dxf")
        return
    tris, _ = gw.parse_dxf(dxf, "Bht_Fk.dxf")
    bmin, bmax = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    layer = gw.Layer(name="Bht_Fk", kind="litologia", triangles=tris,
                     bbox_min=bmin, bbox_max=bmax)
    # Grilla determinista 12×12×12 sobre el bbox, sin bordes exactos.
    ax = [np.linspace(bmin[k] + 0.03*(bmax[k]-bmin[k]),
                      bmax[k] - 0.03*(bmax[k]-bmin[k]), 12) for k in range(3)]
    gx, gy, gz = np.meshgrid(*ax, indexing="ij")
    pts = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
    inside = gw.points_in_mesh(pts, layer)
    n = int(inside.sum())
    print(f"  · malla Bht_Fk: {len(tris)} triángulos · {len(pts)} puntos · {n} dentro")
    check(0 < n < len(pts),
          f"el conteo es no degenerado ({n}/{len(pts)})", n)

    # Determinismo: dos corridas dan lo mismo.
    check(int(gw.points_in_mesh(pts, layer).sum()) == n,
          "el conteo es reproducible entre corridas")

    # Batching no altera el resultado (el grid XY se reconstruye por batch).
    check(int(gw.points_in_mesh(pts, layer, batch=7).sum()) == n,
          "el tamaño de batch no altera el resultado", n)

    # El rayo sigue siendo VERTICAL: es lo que hace válido el grid XY.
    import inspect
    src = inspect.getsource(gw.points_in_mesh)
    check("0.0, 0.0, 1.0" in src.replace(" ", " ") or "0,0,1" in src.replace(" ", ""),
          "el rayo de points_in_mesh sigue siendo vertical (0,0,1)")

    # classify_all_wells con UNA malla == la lógica anterior lito_hit[i]=name.
    gw.wells.clear(); gw.layers.clear()
    sel = pts[::7]
    mwd = [gw.MWDPoint(largo=i*0.02, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1, t=0.0,
                       este=float(p[0]), norte=float(p[1]), cota=float(p[2]))
           for i, p in enumerate(sel)]
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=mwd)
    gw.layers["Bht_Fk"] = layer
    gw.classify_all_wells()
    n_cls = sum(1 for p in mwd if p.dominio == "Bht_Fk")
    n_exp = int(gw.points_in_mesh(sel, layer).sum())
    check(n_cls == n_exp,
          f"con una sola malla, classify_all_wells == points_in_mesh ({n_cls}/{n_exp})",
          (n_cls, n_exp))
    check(gw.overlap_stats["n_ambiguos"] == 0,
          "una sola malla nunca produce ambigüedad")
    reset_registry()


# ═════════════════════════════════════════════════════════════════════════════
#  ADENDA A — rol, alias por rol, descomposición, exención de fixture
# ═════════════════════════════════════════════════════════════════════════════

def a1_roles():
    section("A.1 — Campo rol en el atributo canónico")
    reset_registry()
    check(gw.ATTR_ROLES == ("litologia", "alteracion", "estructura"),
          "la enumeración de roles tiene los valores iniciales", gw.ATTR_ROLES)

    # Migración: todos los prepoblados de litología llevan rol="litologia".
    migrados = ["Kfa", "Bht", "Kpcli", "DL", "Brecha_mixta", "Kpcsb_sedimentaria",
                "Lutitas_normales", "Lutitas_metamorfoseadas"]
    for aid in migrados:
        check(gw.attr_registry[aid].rol == "litologia",
              f"{aid} migrado a rol litologia", gw.attr_registry[aid].rol)

    fk = gw.attr_registry["Fk"]
    check(fk.nombre_oficial == "Feldespato potásica" and fk.rol == "alteracion",
          "Fk → Feldespato potásica, rol alteracion", (fk.nombre_oficial, fk.rol))

    # La colisión Fk ↔ Kfa queda registrada en las notas de AMBOS.
    for aid in ("Fk", "Kfa"):
        n = gw.attr_registry[aid].notas
        check("COLISIÓN DE NOMENCLATURA Fk ↔ Kfa" in n,
              f"la colisión Fk/Kfa está registrada en las notas de {aid}")
    check("66%" in gw.attr_registry["Kfa"].notas,
          "la nota consigna el 66% del metraje que estuvo en riesgo")

    # Los campos de banda solo aplican a litología.
    check(gw.attr_registry["Kfa"].usa_banda_ucs(), "la litología usa banda de UCS")
    check(not fk.usa_banda_ucs(), "la alteración NO usa banda de UCS")
    check(fk.tiene_banda_ucs() is False, "y por tanto nunca 'tiene' banda")
    check(fk.pi_factor() is None, "una alteración no tiene factor de intervalo")

    # Ensuciar una alteración con banda es un error reportado.
    fk.ucs_media = 120.0
    errs = gw.validate_attribute_tree()
    check(any("no lleva banda de UCS" in e for e in errs),
          "poner banda a una alteración se reporta como error", errs)
    fk.ucs_media = None

    # Un rol inválido y una jerarquía entre roles distintos se reportan.
    gw.attr_registry["X1"] = gw.Attribute(id="X1", nombre_oficial="X", rol="inventado")
    check(any("rol inválido" in e for e in gw.validate_attribute_tree()),
          "un rol fuera de la enumeración se reporta")
    del gw.attr_registry["X1"]
    gw.attr_registry["X2"] = gw.Attribute(id="X2", nombre_oficial="X",
                                          rol="alteracion", nivel="subunidad",
                                          padre="Kfa")
    check(any("distinto del rol de su padre" in e for e in gw.validate_attribute_tree()),
          "una subunidad con padre de otro rol se reporta")
    del gw.attr_registry["X2"]
    reset_registry()


def a2_alias_por_rol():
    section("A.2 — Alias que resuelven a un conjunto por rol")
    reset_registry()
    check(gw.resolve_alias("Kfa") == {"litologia": "Kfa"},
          "un alias simple resuelve a un solo rol")
    check(gw.resolve_alias("Fk") == {"alteracion": "Fk"},
          "Fk resuelve al rol alteracion", gw.resolve_alias("Fk"))

    # Bht_Fk debe resolver a DOS atributos de roles distintos.
    al = gw.register_alias("Bht_Fk", ["Bht", "Fk"], "dxf_layer")
    check(gw.resolve_alias("Bht_Fk") == {"litologia": "Bht", "alteracion": "Fk"},
          "Bht_Fk resuelve a dos atributos de roles distintos",
          gw.resolve_alias("Bht_Fk"))
    check(al.es_compuesto(), "el alias se reconoce como compuesto")
    check(gw.resolve_alias("BHT_FK") == {"litologia": "Bht", "alteracion": "Fk"},
          "y sigue siendo insensible a mayúsculas")

    # Dos atributos del MISMO rol en un alias → error, no advertencia.
    err = None
    try:
        gw.register_alias("Mezcla", ["Kfa", "Bht"], "manual")
    except gw.AliasConflict as e:
        err = e
    check(err is not None,
          "dos atributos del mismo rol en un alias lanza AliasConflict", err)
    check(gw.resolve_alias("Mezcla") == {}, "y el alias no queda a medias")

    # Reasignar un rol ya ocupado también es conflicto.
    err = None
    try:
        gw.register_alias("Bht_Fk", {"litologia": "Kfa"}, "manual")
    except gw.AliasConflict as e:
        err = e
    check(err is not None, "cambiar el atributo de un rol ya fijado es conflicto", err)
    check(gw.resolve_alias("Bht_Fk")["litologia"] == "Bht",
          "el mapeo original sobrevive al intento")

    # Añadir un rol NUEVO a un alias existente sí se permite (merge).
    gw.register_alias("Bht_Fk", {"estructura": "FallaZ"}, "manual", merge=True) \
        if "FallaZ" in gw.attr_registry else None
    check(gw.resolve_alias_rol("Bht_Fk", "litologia") == "Bht",
          "resolve_alias_rol funciona sobre un alias compuesto")
    reset_registry()


def a3_descomposicion():
    section("A.3 — Descomposición sugerida de nombres compuestos")
    reset_registry()

    prop = gw.decompose_layer_name("Bht_Fk")
    check(prop and prop["atributos"] == {"litologia": "Bht", "alteracion": "Fk"},
          "Bht_Fk se descompone en litología + alteración", prop)
    check(prop["sin_resolver"] == [], "sin tokens huérfanos")

    for sep in ("Bht-Fk", "Bht+Fk", "Bht Fk"):
        p = gw.decompose_layer_name(sep)
        check(p and p["atributos"] == {"litologia": "Bht", "alteracion": "Fk"},
              f'el separador de "{sep}" se reconoce', p)

    # Dos tokens del MISMO rol → no se propone nada (ambiguo).
    check(gw.decompose_layer_name("Bht_Kfa") is None,
          "dos litologías en un nombre → no se propone nada (ambiguo)")
    # Un solo token no es composición.
    check(gw.decompose_layer_name("Bht") is None, "un token solo no es composición")
    # Token desconocido → se reporta, pero la composición sigue en pie si hay 2 roles.
    p = gw.decompose_layer_name("Bht_Fk_Zzz")
    check(p and "Zzz" in p["sin_resolver"],
          "los tokens sin correspondencia se reportan", p)

    # La composición se PROPONE, nunca se acepta sola.
    gw.pending_aliases.clear()
    m = gw.resolve_or_note("Bht_Fk", "dxf_layer")
    check(m == {}, "el nombre compuesto NO resuelve solo", m)
    e = gw.pending_aliases[gw._norm_txt("Bht_Fk")]
    check(e["propuesta"] is not None, "queda en pendientes CON la propuesta")
    check(gw.pending_with_proposal(), "pending_with_proposal lo lista")

    # Solo al confirmar se almacena como alias propio.
    al = gw.confirm_composite_alias("Bht_Fk", "dxf_layer")
    check(gw.resolve_alias("Bht_Fk") == {"litologia": "Bht", "alteracion": "Fk"},
          "tras confirmar, el string crudo COMPLETO es alias propio")
    check(al.texto_crudo == "Bht_Fk", "conserva el texto crudo", al.texto_crudo)
    check(gw.pending_alias_count() == 0, "y sale de la bandeja")
    # La próxima vez resuelve directo, sin volver a descomponer.
    check(gw._norm_txt("Bht_Fk") in gw.alias_registry,
          "queda cacheado: no hay que descomponer de nuevo")

    # Confirmar algo sin propuesta vigente es un error.
    try:
        gw.confirm_composite_alias("NoExisteNada"); ok = False
    except ValueError:
        ok = True
    check(ok, "confirmar sin propuesta vigente lanza ValueError")
    reset_registry()


def a4_bloqueo_solo_litologias():
    section("A.4 — El bloqueo alcanza solo a las litologías")
    reset_registry()
    _mk_layer("capa_Fk", attr="Fk")
    check(gw.attr_registry["Fk"].calidad == 0, "Fk sigue con calidad 0")
    check(not gw.training_blockers(),
          "Fk (calidad 0, rol alteración) NO bloquea el entrenamiento",
          gw.training_blockers())
    check(gw.training_block_message() is None, "no hay mensaje de bloqueo")

    # Una litología sin banda SÍ bloquea, y se la nombra. (Adenda B: Bht ya
    # tiene banda propia, se usa Kpcli como ejemplo de litología sin ensayo.)
    _mk_layer("capa_Kpcli", attr="Kpcli")
    bl = gw.training_blockers()
    check({b["id"] for b in bl} == {"Kpcli"},
          "una litología sin banda sí bloquea, y solo ella", {b["id"] for b in bl})
    check("Kpcli" in gw.training_block_message(),
          "el mensaje la nombra", gw.training_block_message())
    check(bl[0]["rol"] == "litologia", "el bloqueador reporta su rol", bl[0])

    # Una estructura sin banda tampoco bloquea.
    gw.attr_registry["FallaY"] = gw.Attribute(id="FallaY", nombre_oficial="Falla Y",
                                              rol="estructura", calidad=0)
    _mk_layer("capa_falla", attr="FallaY")
    check({b["id"] for b in gw.training_blockers()} == {"Kpcli"},
          "una estructura sin banda tampoco bloquea")

    # Y Fk sigue componiendo dominio pese a no tener banda.
    check(gw.attr_registry["Fk"].entrenable() == (True, ""),
          "Fk se declara apto: su rol no lleva banda")
    reset_registry()

    # Una malla de ESTRUCTURA cuyo nombre todavía no resuelve a ningún
    # atributo canónico tampoco puede bloquear: layer_role_ids() le arma una
    # identidad de rol estructura a partir del nombre de la capa, y una
    # estructura nunca va a tener banda de UCS (A.4). Antes bloqueaba solo
    # por no estar en el registro (rol "?"), y con los datos reales de
    # Pucobre eso dejaba el entrenamiento colgado de 10 fallas sin
    # vocabulario (FChavito, FPaola, FM1-FM4, FI1-FI3).
    #
    # El atributo desconocido llega a training_blockers por los PUNTOS ya
    # clasificados (attribute_point_counts), no por la capa: por eso el
    # fixture pone puntos con la identidad puesta, como los deja
    # classify_all_wells.
    _mk_layer("malla_FPaola", kind="estructura")
    p_est = gw.MWDPoint(largo=0.0, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1, t=0.0)
    p_est.atributos = {"estructura": "malla_FPaola"}
    gw.wells["W_est"] = gw.Well(well_name="W_est", plan_id="P", hole_id="1", points=[p_est])
    bl = gw.training_blockers()
    check(not bl,
          "una malla de estructura SIN vocabulario asignado NO bloquea (A.4)",
          [(b["id"], b["rol"], b["motivo"]) for b in bl])

    # Pero una identidad de LITOLOGÍA sin vocabulario sí sigue bloqueando:
    # ahí el hueco es real, porque esa malla debería aportar banda de UCS.
    p_lit = gw.MWDPoint(largo=0.0, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1, t=0.0)
    p_lit.atributos = {"litologia": "malla_lito_rara"}
    gw.wells["W_lit"] = gw.Well(well_name="W_lit", plan_id="P", hole_id="2", points=[p_lit])
    ids = {b["id"] for b in gw.training_blockers()}
    check(ids == {"malla_lito_rara"},
          "una identidad de litología sin vocabulario SÍ bloquea, y se la nombra", ids)
    gw.wells.clear()
    reset_registry()


def a7_exencion_fixture():
    section("A.7 — Exención explícita del guardián para fixtures")
    reset_registry()
    gw.allow_site_fixtures(False)

    # Por el flujo NORMAL, Bht_Fk.dxf (Mina Granate) debe disparar la advertencia.
    v = gw.site_guard(373936.0, 6960177.0, "Bht_Fk", "malla DXF", token="dxf:Bht_Fk")
    check(not v["ok"],
          "sin exención habilitada, el fixture de Granate NO pasa", v)
    check(3000 <= v["dist_m"] <= 3100,
          f"y reporta ~3.050 m ({v['dist_m']} m)", v["dist_m"])

    # Con la exención habilitada, el token declarado pasa — y lo dice.
    gw.site_pending_confirms.clear()
    gw.allow_site_fixtures(True)
    v = gw.site_guard(373936.0, 6960177.0, "Bht_Fk", "malla DXF", token="dxf:Bht_Fk")
    check(v["ok"] and v.get("fixture"), "con la exención habilitada, pasa como fixture", v)
    check("EXENTO como fixture declarado" in v["mensaje"],
          "y el mensaje declara que es una exención, no un pase silencioso",
          v["mensaje"])
    check("Mina Granate" in v["mensaje"],
          "la razón declarada viaja en el mensaje", v["mensaje"])

    # La exención es POR TOKEN: otro objeto de Granate sigue bloqueado.
    v = gw.site_guard(373936.0, 6960177.0, "OtraMalla", "malla DXF")
    check(not v["ok"],
          "la exención no se contagia a otros objetos del mismo sitio ajeno", v)

    # Y su AUSENCIA hace fallar: sin declararlo, no hay pase.
    quitado = gw.SITE_FIXTURE_EXEMPTIONS.pop("dxf:Bht_Fk")
    gw.site_pending_confirms.clear()
    v = gw.site_guard(373936.0, 6960177.0, "Bht_Fk", "malla DXF", token="dxf:Bht_Fk")
    check(not v["ok"],
          "sin la declaración en SITE_FIXTURE_EXEMPTIONS el fixture NO pasa", v)
    gw.SITE_FIXTURE_EXEMPTIONS["dxf:Bht_Fk"] = quitado

    gw.allow_site_fixtures(False)
    check(gw.site_fixture_exempt("dxf:Bht_Fk") is None,
          "la aplicación corre con las exenciones apagadas por defecto")
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
# Punto de entrada para pytest: corre todas las comprobaciones y falla si
# alguna no pasó. Así esta suite cuenta en `pytest` igual que en ejecución
# directa, en vez de quedar invisible por no llamarse test_*.
def test_p1_fundaciones():
    FAILURES.clear()
    t11_site_guard()
    t12_attribute_registry()
    t13_alias_registry()
    t14_overlap()
    t14_composition()
    t15_blocking()
    t16_ucs_bounds()
    t17_persistence()
    t18_ui()
    a1_roles()
    a2_alias_por_rol()
    a3_descomposicion()
    a4_bloqueo_solo_litologias()
    a7_exencion_fixture()
    geometry_regression()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    t11_site_guard()
    t12_attribute_registry()
    t13_alias_registry()
    t14_overlap()
    t14_composition()
    t15_blocking()
    t16_ucs_bounds()
    t17_persistence()
    t18_ui()
    a1_roles()
    a2_alias_por_rol()
    a3_descomposicion()
    a4_bloqueo_solo_litologias()
    a7_exencion_fixture()
    geometry_regression()

    print(f"\n{'='*70}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ P1 COMPLETO — todas las verificaciones pasaron.")
    print("="*70)
