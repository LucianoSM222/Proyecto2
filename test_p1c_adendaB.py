"""
test_p1c_adendaB.py — Validación de la Adenda B (docs/P1c_adendaB_bht.md):
registro de Brecha Hidrotermal (Bht) tras el ajuste Hoek-Brown.

Cubre los ocho criterios de aceptación consolidados (docs/criterios_aceptacion.md):
  B.1  la trampa del promedio 198,19 y la naturaleza de la hoja RocData quedan
       documentadas como comentario permanente junto al registro
  B.2  Bht registrada con ucs_central 128,1, banda 100-145, dispersión
       64,5-296,9, CV 0,57, mi 14,77, calidad 1
  B.3  esquema del atributo ampliado con ucs_central/dispersion_min/
       dispersion_max/ucs_cv, sin romper el vocabulario prepoblado
  B.4  distinción banda de confianza / dispersión observada explícita en
       código (campos separados) y en documentación (comentario + notas)
  B.5  alerta de variabilidad con ucs_cv > 0,35: badge en la interfaz y
       ensanche del intervalo de predicción
  B.6  (informativo, no automatizable: otros parámetros del mismo libro)
  B.7  matriz de traslape de bandas UCS recalculada y reportada con AMBOS
       criterios — deben dar panoramas distintos
  —    convención de <Val>: 7 campos, excedente reportado una vez (parser)
  —    alteraciones como dimensión OPCIONAL: Fk no bloquea el entrenamiento

No requiere datos reales: opera enteramente sobre el vocabulario prepoblado
por seed_attribute_registry() y sobre fixtures XML sintéticas mínimas.
"""

import os, sys, tempfile

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
    gw.seed_attribute_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.attribute_exclusions.clear(); gw.pending_aliases.clear()
    gw.attribute_meters.clear()


# ─────────────────────────────────────────────────────────────────────────────
def b1_trampa_documentada():
    section("B.1 — La trampa del promedio 198,19 y RocData, documentadas")
    src = open(os.path.join(HERE, "geomech_wizard.py"), encoding="utf-8").read()
    # El bloque vive como comentario PERMANENTE junto a la definición del
    # atributo Bht, no en un docstring de función que alguien podría borrar
    # al refactorizar sin darse cuenta de que ahí vivía la advertencia.
    inicio = src.find('id="Bht"')
    check(inicio > 0, "el atributo Bht está definido en el registro")
    bloque = src[max(0, inicio - 3000):inicio + 200]
    check("198,19" in bloque, "el promedio contaminado 198,19 está documentado", )
    check("TRIAXIALES" in bloque or "triaxiales" in bloque,
          "se explica que son ensayos triaxiales, no UCS directo")
    check("RocData" in bloque, "la naturaleza de la hoja RocData está documentada")
    check("ENTRADA" in bloque or "entrada" in bloque,
          "se aclara que RocData es la ENTRADA del software, no su salida")
    check("σ3" in bloque or "sigma3" in bloque.lower(),
          "se menciona el confinamiento σ3 como la variable que faltaba")


def b2_registro_bht():
    section("B.2 — Bht registrada con los valores del ajuste Hoek-Brown")
    reset()
    a = gw.attr_registry["Bht"]
    check(a.ucs_central == 128.1, "ucs_central = 128,1 MPa (σci)", a.ucs_central)
    check((a.ucs_min, a.ucs_max) == (100.0, 145.0),
          "banda de confianza 100-145", (a.ucs_min, a.ucs_max))
    check((a.dispersion_min, a.dispersion_max) == (64.5, 296.9),
          "dispersión observada 64,5-296,9", (a.dispersion_min, a.dispersion_max))
    check(abs(a.ucs_cv - 0.57) < 1e-9, "CV = 0,57", a.ucs_cv)
    check(a.mi == 14.77, "mi = 14,77", a.mi)
    check(a.calidad == 1, "calidad 1 (ensayo del sitio)", a.calidad)
    check(a.rol == "litologia" and a.nivel == "unidad", "rol litologia, nivel unidad")
    check(bool(a.fuente), "la fuente está documentada, no vacía")
    check("Hoek-Brown" in a.fuente, "la fuente nombra el método de ajuste", a.fuente)


def b3_esquema_ampliado():
    section("B.3 — Esquema ampliado sin romper el vocabulario existente")
    import dataclasses
    campos = {f.name for f in dataclasses.fields(gw.Attribute)}
    for nuevo in ("ucs_central", "dispersion_min", "dispersion_max", "ucs_cv"):
        check(nuevo in campos, f"el esquema tiene el campo {nuevo}")
    reset()
    # Atributos prepoblados ANTES de la adenda no traen los campos nuevos:
    # deben quedar en None, nunca en un default numérico inventado.
    kfa = gw.attr_registry["Kfa"]
    check(kfa.ucs_central is None and kfa.ucs_cv is None,
          "un atributo sin datos de Adenda B queda en None, no en 0 ni heredado",
          (kfa.ucs_central, kfa.ucs_cv))
    check(kfa.ucs_ancla() == 289.6,
          "sin ucs_central, ucs_ancla() sigue usando ucs_media como antes",
          kfa.ucs_ancla())
    check(len(gw.attr_registry) == 25, "el registro sigue completo (25 atributos)",
          len(gw.attr_registry))


def b4_distincion_banda_dispersion():
    section("B.4 — Banda de confianza y dispersión observada, campos separados")
    reset()
    a = gw.attr_registry["Bht"]
    check((a.ucs_min, a.ucs_max) != (a.dispersion_min, a.dispersion_max),
          "banda de confianza y dispersión NO son el mismo rango",
          ((a.ucs_min, a.ucs_max), (a.dispersion_min, a.dispersion_max)))
    check(a.ucs_ancla() == a.ucs_central,
          "el modelo entrena con ucs_central, no con la dispersión")
    cv_confianza = (a.ucs_max - a.ucs_min) / (2 * a.ucs_central)
    check(cv_confianza < 0.20,
          "la banda de confianza por sí sola implicaría una homogeneidad falsa "
          "(CV~0,09) si se confundiera con la dispersión real (CV 0,57)",
          round(cv_confianza, 3))
    # La distinción también debe quedar en el código, no solo en los datos.
    src = open(os.path.join(HERE, "geomech_wizard.py"), encoding="utf-8").read()
    check("banda de confianza" in src.lower() and "dispersi" in src.lower(),
          "la distinción está documentada en el código, no solo implícita en los números")


def b5_alerta_variabilidad():
    section("B.5 — Alerta de variabilidad (CV > 0,35) y ensanche del intervalo")
    reset()
    bht = gw.attr_registry["Bht"]
    check(bht.alta_variabilidad(), "Bht: CV=0,57 > 0,35 → alta variabilidad")
    kfa = gw.attr_registry["Kfa"]
    check(not kfa.alta_variabilidad(), "Kfa sin ucs_cv documentado no dispara la alerta")

    # El intervalo de predicción se ensancha respecto de un CV sin alerta.
    pi_bht = bht.pi_factor()
    referencia = gw.QUALITY_PI_FACTOR[1] * gw.SINGLE_SPECIMEN_PI_FACTOR
    check(pi_bht > referencia,
          "el factor de Bht supera el que tendría solo por probeta única",
          (pi_bht, referencia))
    check(abs(pi_bht - referencia * gw.HIGH_CV_PI_FACTOR) < 1e-9,
          "el ensanche adicional es exactamente HIGH_CV_PI_FACTOR", pi_bht)

    # La interfaz muestra la advertencia JUNTO al atributo, no en un panel aparte.
    row = str(gw._attr_row(bht))
    check("alta variabilidad" in row.lower(), "el badge de alerta aparece en la fila del atributo")
    check("0.57" in row or "0,57" in row, "el badge muestra el CV concreto", row[:300])

    fila_kfa = str(gw._attr_row(kfa))
    check("alta variabilidad" not in fila_kfa.lower(),
          "un atributo sin alta variabilidad no muestra el badge")


def b7_matriz_traslape_ambos_criterios():
    section("B.7 — Matriz de traslape de bandas UCS, ambos criterios")
    reset()
    rep = gw.ucs_band_overlap_report()
    check(set(rep) == {"confianza", "dispersion"}, "el reporte trae los dos criterios", set(rep))

    def _par(pares, a, b):
        return any({p["a"], p["b"]} == {a, b} for p in pares)

    # Caso de la especificación: Bht vs. Albitófiro (Kfa, 274,3-304,9).
    check(_par(rep["dispersion"], "Bht", "Kfa"),
          "bajo dispersión observada, Bht se traslapa con el Albitófiro")
    check(not _par(rep["confianza"], "Bht", "Kfa"),
          "bajo banda de confianza, Bht NO se traslapa con el Albitófiro: panorama distinto")

    check(len(rep["dispersion"]) > len(rep["confianza"]),
          "la dispersión observada produce MÁS traslapes que la banda de confianza "
          "(Bht es ancha en dispersión, angosta en confianza)",
          (len(rep["dispersion"]), len(rep["confianza"])))

    # Bht se traslapa con TODAS las demás litologías con banda, bajo dispersión.
    otras = {a.id for a in gw.attr_registry.values()
             if a.usa_banda_ucs() and a.tiene_banda_ucs() and a.id != "Bht"}
    traslapa_con = {p["a"] if p["b"] == "Bht" else p["b"]
                    for p in rep["dispersion"] if "Bht" in (p["a"], p["b"])}
    # Ka_caliza (60 MPa) es la ÚNICA que queda debajo del piso de dispersión de
    # Bht (64,5). Que exista una excepción no cambia el punto —Bht es tan
    # dispersa que se traslapa con casi todo— pero la excepción se nombra en
    # vez de aflojar la comparación.
    otras = otras - {"Ka_caliza"}
    traslapa_con = traslapa_con - {"Ka_caliza"}
    check(traslapa_con == otras,
          "bajo dispersión, Bht se traslapa con TODAS las demás unidades con banda",
          (traslapa_con, otras))

    # Criterio inválido: se rechaza, no se ignora en silencio.
    try:
        gw.ucs_band_overlap_matrix("otro"); ok = False
    except ValueError:
        ok = True
    check(ok, "un criterio desconocido lanza ValueError en vez de devolver vacío")

    # La UI lo muestra en el panel de vocabulario, con ambos criterios visibles.
    body = str(gw._vocab_panel_body())
    check("Matriz de traslape de bandas UCS" in body,
          "el panel de vocabulario incluye la matriz de traslape de bandas")
    check("confianza" in body.lower() and "dispersi" in body.lower(),
          "el panel muestra ambos criterios, no solo uno")


def parser_excedente_reportado_una_vez():
    section("Convención de <Val>: 7 campos, excedente reportado UNA vez")
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<DRMWD xmlns="http://www.iredes.org/xml/DrillRig" xmlns:IR="http://www.iredes.org/xml">
  <IR:PlanIdRef>TEST_PLAN</IR:PlanIdRef>
  <MWDholeId>1</MWDholeId>
  <CompactMWDdata>
    <MWDparams>
      <Parameter Unit="m" Full="LengthTag">LT</Parameter>
      <Parameter Unit="m/min" Full="PenetrRate">PR</Parameter>
      <Parameter Unit="Bar" Full="PercPressure">PP</Parameter>
      <Parameter Unit="Bar" Full="FeedPressure">FP</Parameter>
      <Parameter Unit="Bar" Full="DampPressure">DP</Parameter>
      <Parameter Unit="Bar" Full="RotPressure">RP</Parameter>
      <Parameter Unit="Bar" Full="FlushPressure">FLP</Parameter>
      <Parameter Unit="LogPoint" Full="DRMWDoption">OPT1</Parameter>
    </MWDparams>
    <Sample><TiStamp>2026-01-01T00:00:00</TiStamp>
      <Val>0.020 1.0 150.0 40.0 100.0 55.0 6.0 0 </Val></Sample>
    <Sample><TiStamp>2026-01-01T00:00:02</TiStamp>
      <Val>0.040 1.1 151.0 41.0 101.0 56.0 6.1 0 </Val></Sample>
  </CompactMWDdata>
</DRMWD>
"""
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w", encoding="utf-8")
    tmp.write(xml); tmp.close()
    gw.parse_warnings.clear()
    mw = gw.parse_mw(tmp.name, "TEST_MW.xml")
    os.unlink(tmp.name)

    check(len(mw["puntos"]) == 2, "los 2 puntos se parsean pese al campo excedente")
    p = mw["puntos"][0]
    check((p.largo, p.vel, p.pp, p.pa, p.pd, p.pr, p.pf) ==
          (0.020, 1.0, 150.0, 40.0, 100.0, 55.0, 6.0),
          "los 7 campos se leen en el orden LT|ROP|PP|FP|DP|RP|FLP",
          (p.largo, p.vel, p.pp, p.pa, p.pd, p.pr, p.pf))
    avisos = [w for w in gw.parse_warnings if "excedente" in w]
    check(len(avisos) == 1, "el campo excedente se reporta EXACTAMENTE una vez", avisos)
    check("OPT1" in avisos[0], "el aviso nombra el campo descartado")


def alteraciones_dimension_opcional():
    section("Alteraciones: dimensión OPCIONAL, nunca obligatoria para entrenar")
    reset()
    lay = gw.Layer(name="capa_Fk", kind="litologia", triangles=__import__("numpy").zeros((1, 3, 3)),
                   bbox_min=__import__("numpy").zeros(3), bbox_max=__import__("numpy").zeros(3))
    gw.set_layer_attributes(lay, {"alteracion": "Fk"})
    gw.layers["capa_Fk"] = lay
    check(not gw.training_blockers(),
          "una capa de SOLO alteración no bloquea el entrenamiento",
          gw.training_blockers())
    fk = gw.attr_registry["Fk"]
    check(fk.usa_banda_ucs() is False, "alteración: no usa banda de UCS por rol")
    check(fk.entrenable() == (True, ""), "Fk se declara apto pese a calidad 0")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    b1_trampa_documentada,
    b2_registro_bht,
    b3_esquema_ampliado,
    b4_distincion_banda_dispersion,
    b5_alerta_variabilidad,
    b7_matriz_traslape_ambos_criterios,
    parser_excedente_reportado_una_vez,
    alteraciones_dimension_opcional,
]


def test_p1c_adendaB():
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
    print("✓ ADENDA B COMPLETA — todas las verificaciones pasaron.")
    print("=" * 72)
