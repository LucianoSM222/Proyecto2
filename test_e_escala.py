"""
test_e_escala.py — Validación de la Sesión E (docs/E_escala.md), ajustada al
hallazgo real de E.5: el perfilado con archivos reales del repo mostró que el
costo dominante NO es el ray casting (1,6 s para 262.500 puntos contra la
malla más grande del repo, Bht.dxf, 92.918 triángulos) sino PARSEAR el DXF
(12,5 s y +210 MB solo para leer y triangular esa misma malla). El diseño de
caché se reorienta a ese cuello de botella real:

  E.2a  Caché de PARSEO DXF en disco, keyed por el HASH DEL CONTENIDO del
        archivo (la geometría triangulada es una función pura de sus propios
        bytes; no depende del registro de vocabulario). Escritura atómica.
        El aviso de caras omitidas se reemite en un acierto de caché.
  E.2b  Firma de clasificación (vocab_classification_signature): hash
        determinístico de lo que SÍ afecta classify_all_wells() — geometría
        de cada malla cargada + rol/nivel/padre del registro de atributos —
        y NADA de lo que no la afecta (banda de UCS, calidad, exclusiones,
        que son del entrenamiento, no de la clasificación geométrica).
  E.2c  classify_all_wells_cached(): memoiza contra esa firma para que un
        callback que la dispare dos veces sin que nada relevante haya
        cambiado no vuelva a recorrer los puntos ("ningún callback puede
        disparar una reclasificación completa").
  E.3   parse_mw() en streaming (ET.iterparse + elem.clear()) en vez de
        materializar el árbol XML completo antes de procesar: con ~150
        pozos por caserón, tenerlos todos como DOM completo en memoria a
        la vez no es viable en Colab.
  E.4   Submuestreo para la VISTA del visor 3D (build_3d_figure): ningún
        gráfico recibe 262.500 puntos como marcadores. El conteo real
        siempre se declara en el gráfico, se haya recortado o no; los
        CÁLCULOS (entrenamiento, DI, dominios) siguen usando la población
        completa — el recorte es solo del dibujo.

Usa los DXF reales del repo (FM2.dxf, Bht.dxf) para el caso end-to-end; el
resto son fixtures sintéticas mínimas.
"""

import os, sys, glob, shutil, hashlib, time, tempfile

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


TEST_CACHE_DIR = os.path.join(HERE, ".test_geomech_cache")


def reset_cache():
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)
    gw.CACHE_DIR = TEST_CACHE_DIR
    gw.DXF_CACHE_DIR = os.path.join(TEST_CACHE_DIR, "dxf")
    gw._last_classify_signature = None


def reset_registry():
    gw.seed_attribute_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.attribute_exclusions.clear()


FM2_PATH = os.path.join(HERE, "test_data", "FM2.dxf")
BHT_PATH = os.path.join(HERE, "test_data", "Bht.dxf")
_TIENE_DXF_REALES = os.path.exists(FM2_PATH) and os.path.exists(BHT_PATH)


# ─────────────────────────────────────────────────────────────────────────────
def e2a_hash_contenido():
    section("E.2a — Hash de contenido: determinístico, sensible a los bytes")
    a = b"contenido de prueba A" * 100
    b = b"contenido de prueba A" * 100
    c = b"contenido de prueba B" * 100
    check(gw._content_hash(a) == gw._content_hash(b),
          "el mismo contenido produce la misma clave")
    check(gw._content_hash(a) != gw._content_hash(c),
          "contenido distinto produce clave distinta")


def e2a_cache_evita_reparseo():
    section("E.2a — El acierto de caché evita volver a llamar a parse_dxf")
    reset_cache()
    llamadas = []
    orig = gw.parse_dxf
    def espia(path, fname):
        llamadas.append(fname)
        return orig(path, fname)
    gw.parse_dxf = espia
    try:
        raw = b"DXF SINTETICO " * 500  # bytes cualquiera: parse_dxf se reemplaza igual
        # parse_dxf real fallaría con estos bytes; se sustituye por una versión
        # de control que no depende del contenido, para aislar el mecanismo de
        # caché del parser real (ese se prueba aparte, con archivos reales).
        def fake_parse(path, fname):
            llamadas.append(fname)
            return np.zeros((3, 3, 3), dtype=np.float64), 0
        gw.parse_dxf = fake_parse

        tris1, skipped1 = gw.parse_dxf_cached(raw, "prueba.dxf")
        tris2, skipped2 = gw.parse_dxf_cached(raw, "prueba.dxf")
        check(len(llamadas) == 1, "parse_dxf se llamó UNA sola vez para dos pedidos idénticos",
              llamadas)
        check(np.array_equal(tris1, tris2), "el segundo pedido devuelve los MISMOS triángulos")
        check(skipped1 == skipped2 == 0, "el conteo de caras omitidas también se preserva")

        cache_files = glob.glob(os.path.join(gw.DXF_CACHE_DIR, "*.npz"))
        check(len(cache_files) == 1, "queda exactamente un archivo de caché en disco", cache_files)
        tmp_files = glob.glob(os.path.join(gw.DXF_CACHE_DIR, "*.tmp*"))
        check(not tmp_files, "no queda ningún archivo temporal a medio escribir", tmp_files)
    finally:
        gw.parse_dxf = orig
    reset_cache()


def e2a_contenidos_distintos_no_colisionan():
    section("E.2a — Dos archivos con contenido distinto NO comparten caché")
    reset_cache()
    llamadas = []
    orig = gw.parse_dxf
    def fake_parse(path, fname):
        llamadas.append(fname)
        return np.zeros((1, 3, 3), dtype=np.float64), 0
    gw.parse_dxf = fake_parse
    try:
        gw.parse_dxf_cached(b"contenido X", "x.dxf")
        gw.parse_dxf_cached(b"contenido Y", "y.dxf")
        check(len(llamadas) == 2, "ambos contenidos distintos SÍ se parsean, ninguno se pierde",
              llamadas)
        cache_files = glob.glob(os.path.join(gw.DXF_CACHE_DIR, "*.npz"))
        check(len(cache_files) == 2, "quedan dos archivos de caché distintos", cache_files)
    finally:
        gw.parse_dxf = orig
    reset_cache()


def e2a_aviso_de_omitidas_se_reemite_en_acierto():
    section("E.2a — El aviso de caras omitidas se reemite en un acierto de caché")
    reset_cache()
    orig = gw.parse_dxf
    def fake_parse(path, fname):
        # Replica el comportamiento real de parse_dxf: loguea al parsear.
        gw.log_warn(f'DXF "{fname}": 2 caras omitidas.')
        return np.zeros((1, 3, 3), dtype=np.float64), 2
    gw.parse_dxf = fake_parse
    try:
        gw.parse_warnings.clear()
        gw.parse_dxf_cached(b"contenido con omitidas", "omite.dxf")
        n1 = sum(1 for w in gw.parse_warnings if "omitidas" in w)
        check(n1 == 1, "primera carga (parseo real): un aviso de caras omitidas", gw.parse_warnings)

        gw.parse_warnings.clear()
        gw.parse_dxf_cached(b"contenido con omitidas", "omite.dxf")
        n2 = sum(1 for w in gw.parse_warnings if "omitidas" in w)
        check(n2 == 1,
              "segunda carga (desde caché): el aviso NO se pierde, se reemite igual",
              gw.parse_warnings)
    finally:
        gw.parse_dxf = orig
    reset_cache()


def e2a_real_end_to_end():
    section("E.2a — Fin a fin con los DXF reales del repositorio")
    if not _TIENE_DXF_REALES:
        print("  ⊘ omitido: faltan test_data/FM2.dxf o test_data/Bht.dxf")
        return
    reset_cache()
    raw = open(FM2_PATH, "rb").read()

    t0 = time.perf_counter()
    tris_frio, skipped_frio = gw.parse_dxf_cached(raw, "FM2.dxf")
    t_frio = time.perf_counter() - t0

    t0 = time.perf_counter()
    tris_tibio, skipped_tibio = gw.parse_dxf_cached(raw, "FM2.dxf")
    t_tibio = time.perf_counter() - t0

    check(np.array_equal(tris_frio, tris_tibio),
          "los triángulos del acierto de caché son IDÉNTICOS a los del parseo real")
    check(skipped_frio == skipped_tibio, "el conteo de omitidas coincide")
    check(t_tibio < t_frio / 3,
          f"el acierto de caché es sustancialmente más rápido ({t_frio:.2f}s → {t_tibio:.3f}s)",
          (t_frio, t_tibio))

    # Comparación directa contra el parseo SIN caché, para confirmar que el
    # caché no altera el resultado (regresión contra el parser real).
    tris_directo, skipped_directo = gw.parse_dxf(FM2_PATH, "FM2.dxf")
    check(np.array_equal(tris_frio, tris_directo),
          "el resultado cacheado es idéntico al de parse_dxf() sin caché")
    reset_cache()


# ─────────────────────────────────────────────────────────────────────────────
def _mk_layer(name, atributos, caseron=None, tris=None):
    tris = tris if tris is not None else np.array([[[0, 0, 0], [1, 0, 0], [0, 1, 0]]], dtype=np.float64)
    lay = gw.Layer(name=name, kind="litologia", triangles=tris,
                   bbox_min=tris.reshape(-1, 3).min(0), bbox_max=tris.reshape(-1, 3).max(0))
    gw.set_layer_attributes(lay, atributos)
    lay.caseron = caseron
    gw.layers[name] = lay
    return lay


def e2b_firma_cambia_con_lo_relevante():
    section("E.2b — La firma de clasificación cambia con lo que SÍ afecta classify()")
    reset_registry()
    _mk_layer("capa_Kfa", {"litologia": "Kfa"})
    sig0 = gw.vocab_classification_signature()

    # Cambiar los atributos de una capa (equivalente a reasignar un alias).
    gw.layers["capa_Kfa"].atributos = {"litologia": "Bht"}
    sig1 = gw.vocab_classification_signature()
    check(sig1 != sig0, "reasignar el atributo de una capa cambia la firma")
    gw.layers["capa_Kfa"].atributos = {"litologia": "Kfa"}
    check(gw.vocab_classification_signature() == sig0, "revertir el cambio restaura la firma")

    # Cambiar rol/nivel/padre en el registro (afecta anidamiento y composición).
    prev_rol = gw.attr_registry["Kfa"].rol
    gw.attr_registry["Kfa"].rol = "alteracion"
    check(gw.vocab_classification_signature() != sig0,
          "cambiar el rol de un atributo referenciado cambia la firma")
    gw.attr_registry["Kfa"].rol = prev_rol
    check(gw.vocab_classification_signature() == sig0, "revertir el rol restaura la firma")

    # Cambiar la geometría de una malla (nueva malla subida con el mismo nombre).
    nueva = np.array([[[9, 9, 9], [10, 9, 9], [9, 10, 9]]], dtype=np.float64)
    gw.layers["capa_Kfa"].triangles = nueva
    check(gw.vocab_classification_signature() != sig0,
          "cambiar la geometría de una malla cambia la firma (nueva versión del DXF)")
    reset_registry()


def e2b_firma_estable_con_lo_irrelevante():
    section("E.2b — La firma NO cambia con lo que solo afecta al entrenamiento")
    reset_registry()
    _mk_layer("capa_Kfa", {"litologia": "Kfa"})
    sig0 = gw.vocab_classification_signature()

    gw.attr_registry["Kfa"].ucs_media = 999.0
    gw.attr_registry["Kfa"].calidad = 4
    gw.attr_registry["Kfa"].fuente = "otra fuente"
    check(gw.vocab_classification_signature() == sig0,
          "banda de UCS / calidad / fuente NO afectan la firma (no afectan classify())")

    gw.exclude_attribute("Kfa", "solo para el test")
    check(gw.vocab_classification_signature() == sig0,
          "una exclusión de entrenamiento tampoco afecta la firma")
    reset_registry()


def e2c_memoiza_reclasificaciones_redundantes():
    section("E.2c — classify_all_wells_cached() no repite trabajo si nada cambió")
    reset_registry(); reset_cache()
    _mk_layer("capa_Kfa", {"litologia": "Kfa"})
    pts = [gw.MWDPoint(largo=i * 0.02, vel=1, pp=1, pa=1, pd=1, pr=1, pf=1, se=1,
                       t=0.0, este=0.3, norte=0.3, cota=-1.0) for i in range(5)]
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=pts)

    llamadas = []
    orig = gw.classify_all_wells
    def espia():
        llamadas.append(1)
        return orig()
    gw.classify_all_wells = espia
    try:
        r1 = gw.classify_all_wells_cached()
        check(r1 is True and len(llamadas) == 1, "primera llamada SÍ reclasifica")
        r2 = gw.classify_all_wells_cached()
        check(r2 is False and len(llamadas) == 1,
              "segunda llamada sin cambios NO vuelve a recorrer los puntos", llamadas)
        check(gw.wells["W"].points[0].dominio == "Kfa",
              "el resultado de la clasificación sigue disponible pese al memoizado")

        gw.layers["capa_Kfa"].atributos = {"litologia": "Bht"}
        r3 = gw.classify_all_wells_cached()
        check(r3 is True and len(llamadas) == 2,
              "cambiar la asignación de la capa SÍ dispara una reclasificación", llamadas)

        r4 = gw.classify_all_wells_cached(force=True)
        check(r4 is True and len(llamadas) == 3,
              "force=True reclasifica aunque nada haya cambiado", llamadas)
    finally:
        gw.classify_all_wells = orig
    reset_registry(); reset_cache()


# ─────────────────────────────────────────────────────────────────────────────
# E.3 — Parseo por bloques: parse_mw() ya no materializa el árbol XML
# completo en memoria antes de procesar. Usa ET.iterparse en modo streaming
# y libera cada <Sample> (elem.clear()) apenas se extrae su <Val> — con
# ~150 pozos por caserón, no es viable tener las 150 árboles DOM completos
# en memoria a la vez (E.1/E.3).

MW_REAL_PATH = os.path.join(HERE, "test_data", "MWPCS_1043_PR01_TH_P07H9_260314_0048.xml")
_TIENE_MW_REAL = os.path.exists(MW_REAL_PATH)


def _mk_synthetic_mw_xml(path, n_samples, extra_param=True):
    """Genera un MWD IREDES sintético con n_samples <Sample>, para perfilar
    memoria a una escala que los fixtures reales del repo no alcanzan."""
    params = [
        '<Parameter Unit="m" Full="LengthTag">LT</Parameter>',
        '<Parameter Unit="m/min" Full="PenetrRate">PR</Parameter>',
        '<Parameter Unit="Bar" Full="PercPressure">PP</Parameter>',
        '<Parameter Unit="Bar" Full="FeedPressure">FP</Parameter>',
        '<Parameter Unit="Bar" Full="DampPressure">DP</Parameter>',
        '<Parameter Unit="Bar" Full="RotPressure">RP</Parameter>',
        '<Parameter Unit="Bar" Full="FlushPressure">FLP</Parameter>',
    ]
    if extra_param:
        params.append('<Parameter Unit="LogPoint" Full="DRMWDoption">OPT1</Parameter>')
    samples = []
    for i in range(n_samples):
        lt = i * 0.02
        samples.append(
            f"<Sample><TiStamp>2026-01-01T00:00:{i%60:02d}</TiStamp>"
            f"<Val>{lt:.3f} 1.0 150.0 40.0 100.0 55.0 6.0 0 </Val></Sample>")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<DRMWD xmlns="http://www.iredes.org/xml/DrillRig" xmlns:IR="http://www.iredes.org/xml">
  <IR:PlanIdRef>SYN_PLAN</IR:PlanIdRef>
  <MWDholeId>1</MWDholeId>
  <CompactMWDdata>
    <MWDparams>
      {''.join(params)}
    </MWDparams>
    {''.join(samples)}
  </CompactMWDdata>
</DRMWD>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)


def _parse_mw_old_style(path, fname):
    """
    Copia congelada de la implementación PRE-E.3 de parse_mw (ET.parse +
    findall, árbol completo en memoria), conservada SOLO para comparar
    memoria/resultado contra la versión en streaming. No se usa en
    producción.
    """
    import xml.etree.ElementTree as ET
    try: root = ET.parse(path).getroot()
    except Exception as e: raise RuntimeError(f"XML ilegible: {e}")
    pn = root.find(f".//{gw.IR}PlanIdRef")
    plan_id = (pn.text or "").strip() if pn is not None else ""
    hn = root.find(f".//{gw.DR}MWDholeId")
    hole_id = (hn.text or "").strip() if hn is not None else None
    if not hole_id:
        import re
        m = re.search(r"H(\d+)_", fname, re.I)
        if m: hole_id = m.group(1)
    samples = root.findall(f".//{gw.DR}Sample")
    puntos, largo_max, skipped = [], 0.0, 0
    for s in samples:
        vn = s.find(f"{gw.DR}Val")
        if vn is None or not vn.text: skipped += 1; continue
        parts = [float(x) for x in vn.text.strip().split()]
        if len(parts) < 7: skipped += 1; continue
        lt, rop, pp, ap, dp, rp, flp = parts[:7]
        se = (pp + rp + ap) / (rop + gw.EPS)
        puntos.append(gw.MWDPoint(largo=lt, vel=rop, pp=pp, pa=ap, pd=dp, pr=rp, pf=flp,
                                  se=se, t=0.0))
        if lt > largo_max: largo_max = lt
    for p in puntos: p.t = p.largo/largo_max if largo_max > 0 else 0.0
    return {"plan_id": plan_id, "hole_id": hole_id, "largo_max": largo_max, "puntos": puntos}


def e3_streaming_mismo_resultado_que_antes():
    section("E.3 — El parseo en streaming da EXACTAMENTE el mismo resultado")
    if not _TIENE_MW_REAL:
        print("  ⊘ omitido: falta test_data/MWPCS_1043_PR01_TH_P07H9_260314_0048.xml")
        return
    fname = os.path.basename(MW_REAL_PATH)
    nuevo = gw.parse_mw(MW_REAL_PATH, fname)
    viejo = _parse_mw_old_style(MW_REAL_PATH, fname)

    check(nuevo["plan_id"] == viejo["plan_id"], "mismo plan_id", (nuevo["plan_id"], viejo["plan_id"]))
    check(nuevo["hole_id"] == viejo["hole_id"], "mismo hole_id")
    check(len(nuevo["puntos"]) == len(viejo["puntos"]),
          "mismo número de puntos", (len(nuevo["puntos"]), len(viejo["puntos"])))
    check(abs(nuevo["largo_max"] - viejo["largo_max"]) < 1e-9, "mismo largo_max")
    campos = ("largo", "vel", "pp", "pa", "pd", "pr", "pf", "se", "t")
    iguales = all(
        all(abs(getattr(pn, c) - getattr(pv, c)) < 1e-9 for c in campos)
        for pn, pv in zip(nuevo["puntos"], viejo["puntos"])
    )
    check(iguales, "todos los puntos son idénticos campo a campo, streaming vs. árbol completo")


def e3_streaming_libera_memoria():
    section("E.3 — El streaming usa memoria pico MENOR que materializar el árbol completo")
    import tracemalloc
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp.close()
    try:
        _mk_synthetic_mw_xml(tmp.name, n_samples=30_000)

        tracemalloc.start()
        gw.parse_mw(tmp.name, "grande.xml")
        _, peak_nuevo = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        _parse_mw_old_style(tmp.name, "grande.xml")
        _, peak_viejo = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"  · pico streaming: {peak_nuevo/1e6:.2f} MB · "
              f"pico árbol completo: {peak_viejo/1e6:.2f} MB")
        check(peak_nuevo < peak_viejo,
              "el streaming pica MENOS memoria que ET.parse + findall sobre el árbol completo",
              (peak_nuevo, peak_viejo))
    finally:
        os.unlink(tmp.name)


def e3_xml_malformado_lanza_error():
    section("E.3 — XML ilegible falla ruidosamente, no en silencio")
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w", encoding="utf-8")
    tmp.write("esto no es XML en absoluto <<<")
    tmp.close()
    try:
        gw.parse_mw(tmp.name, "roto.xml")
        ok = False
    except RuntimeError as e:
        ok = "ilegible" in str(e)
    check(ok, "un XML malformado lanza RuntimeError con 'ilegible' en el mensaje")
    os.unlink(tmp.name)


def e3_timeout_omite_el_resto_sin_reventar():
    section("E.3 — El presupuesto de tiempo sigue cortando el parseo sin excepción")
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp.close()
    try:
        _mk_synthetic_mw_xml(tmp.name, n_samples=5000)
        orig_budget = gw.PARSE_BUDGET_S
        gw.PARSE_BUDGET_S = 0.0
        try:
            gw.parse_warnings.clear()
            mw = gw.parse_mw(tmp.name, "presupuesto.xml")
        finally:
            gw.PARSE_BUDGET_S = orig_budget
        check(len(mw["puntos"]) < 5000,
              "con presupuesto agotado, se detiene antes de terminar", len(mw["puntos"]))
        check(any("timeout" in w for w in gw.parse_warnings),
              "el corte por timeout queda declarado, no silencioso", gw.parse_warnings)
    finally:
        os.unlink(tmp.name)


def e3_excedente_sigue_funcionando_en_streaming():
    section("E.3 — La convención de <Val> (3.x / Paso 0) sigue intacta en streaming")
    tmp = tempfile.NamedTemporaryFile(suffix=".xml", delete=False)
    tmp.close()
    try:
        _mk_synthetic_mw_xml(tmp.name, n_samples=10, extra_param=True)
        gw.parse_warnings.clear()
        mw = gw.parse_mw(tmp.name, "excedente.xml")
        check(len(mw["puntos"]) == 10, "los 10 puntos se parsean pese al campo excedente")
        avisos = [w for w in gw.parse_warnings if "excedente" in w]
        check(len(avisos) == 1, "el campo excedente sigue reportándose EXACTAMENTE una vez",
              avisos)
        check("OPT1" in avisos[0], "el aviso sigue nombrando el campo descartado")
    finally:
        os.unlink(tmp.name)


# ─────────────────────────────────────────────────────────────────────────────
# E.4 — Submuestreo para visualización: ningún gráfico debe recibir 262.500
# puntos como marcadores. build_3d_figure() (el único visor que dibuja TODOS
# los pozos de un caserón a la vez, el resto son por-pozo y quedan chicos por
# construcción) recorta la VISTA a MAX_VIZ_POINTS, declara el conteo real
# siempre —se haya recortado o no— y nunca toca la población que usan los
# cálculos (well.points sigue completo).

def _mk_well_puntos(wn, n, este0=0.0):
    pts = [gw.MWDPoint(largo=i * 0.02, vel=1.0, pp=100.0, pa=50.0, pd=40.0, pr=30.0, pf=8.0,
                       se=100.0, t=0.0, este=este0 + i * 0.02, norte=0.0, cota=-i * 0.02)
           for i in range(n)]
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="P", hole_id=wn, points=pts)
    return gw.wells[wn]


def e4_submuestrear_indices_respeta_max():
    section("E.4 — _submuestrear_indices(): nunca supera max_n, conserva orden y extremos")
    check(gw._submuestrear_indices(100, 5000) == list(range(100)),
          "si ya cabe, devuelve TODOS los índices sin recortar")
    idx = gw._submuestrear_indices(10_000, 1000)
    check(len(idx) == 1000, "recorta a exactamente max_n índices", len(idx))
    check(idx == sorted(idx) and len(set(idx)) == len(idx),
          "los índices quedan ordenados y sin repetir")
    check(idx[0] == 0, "el primer índice (collar) siempre queda incluido", idx[0])
    check(idx[-1] >= 9000, "el muestreo cubre hasta cerca del final, no solo el principio",
          idx[-1])
    check(gw._submuestrear_indices(0, 100) == [], "cero elementos no revienta")


def e4_figura_3d_no_supera_el_tope():
    section("E.4 — build_3d_figure() nunca dibuja más de MAX_VIZ_POINTS marcadores")
    reset_registry()
    _mk_well_puntos("W1", 3000, este0=0.0)
    _mk_well_puntos("W2", 3000, este0=100.0)
    _mk_well_puntos("W3", 3000, este0=200.0)
    n_total_real = sum(len(w.points) for w in gw.wells.values())
    check(n_total_real > gw.MAX_VIZ_POINTS,
          "la fixture realmente supera el tope (si no, el test no prueba nada)", n_total_real)

    fig = gw.build_3d_figure(color_by="se")
    n_dibujados = sum(len(tr.x) for tr in fig.data if tr.type == "scatter3d"
                      and tr.mode and "markers" in tr.mode and len(tr.x) > 1)
    check(n_dibujados <= gw.MAX_VIZ_POINTS,
          f"el total de marcadores dibujados ({n_dibujados}) respeta MAX_VIZ_POINTS "
          f"({gw.MAX_VIZ_POINTS})", n_dibujados)
    check(n_dibujados > 0, "sí se dibuja algo (no quedó vacío)")

    titulo = str(fig.layout.title.text) if fig.layout.title and fig.layout.title.text else ""
    titulo_sin_puntos_miles = titulo.replace(".", "")
    check(str(n_total_real) in titulo_sin_puntos_miles,
          "el título declara el conteo REAL de puntos (población completa)", titulo)
    check(any(ch.isdigit() for ch in titulo) and "mostrando" in titulo.lower(),
          "el título declara cuántos se están mostrando, con la palabra 'mostrando'", titulo)
    reset_registry()


def e4_figura_3d_declara_conteo_aunque_no_recorte():
    section("E.4 — El conteo real se declara SIEMPRE, incluso sin recortar")
    reset_registry()
    _mk_well_puntos("W1", 50)
    n_total_real = len(gw.wells["W1"].points)
    check(n_total_real <= gw.MAX_VIZ_POINTS, "la fixture cabe entera (caso sin recorte)")

    fig = gw.build_3d_figure(color_by="se")
    titulo = str(fig.layout.title.text) if fig.layout.title and fig.layout.title.text else ""
    check(titulo != "", "el título existe aunque no haya recorte (nunca queda implícito)")
    check(str(n_total_real) in titulo,
          "declara el conteo real también cuando se muestra el 100%", titulo)

    n_dibujados = sum(len(tr.x) for tr in fig.data if tr.type == "scatter3d"
                      and tr.mode and "markers" in tr.mode and len(tr.x) > 1)
    check(n_dibujados == n_total_real,
          "sin recorte, se dibujan TODOS los puntos reales, ni uno menos", n_dibujados)
    reset_registry()


def e4_submuestreo_no_toca_la_poblacion_real():
    section("E.4 — El recorte es SOLO del dibujo: la población real queda intacta")
    reset_registry()
    _mk_well_puntos("W1", 8000)
    n_antes = len(gw.wells["W1"].points)

    gw.build_3d_figure(color_by="se")

    n_despues = len(gw.wells["W1"].points)
    check(n_antes == n_despues == 8000,
          "well.points NO se mutó ni se recortó por dibujar la figura",
          (n_antes, n_despues))
    n_calculo = len(list(gw.all_points()))
    check(n_calculo == 8000,
          "los cálculos (all_points, entrenamiento, DI) siguen viendo la población completa",
          n_calculo)
    reset_registry()


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    e2a_hash_contenido,
    e2a_cache_evita_reparseo,
    e2a_contenidos_distintos_no_colisionan,
    e2a_aviso_de_omitidas_se_reemite_en_acierto,
    e2a_real_end_to_end,
    e2b_firma_cambia_con_lo_relevante,
    e2b_firma_estable_con_lo_irrelevante,
    e2c_memoiza_reclasificaciones_redundantes,
    e3_streaming_mismo_resultado_que_antes,
    e3_streaming_libera_memoria,
    e3_xml_malformado_lanza_error,
    e3_timeout_omite_el_resto_sin_reventar,
    e3_excedente_sigue_funcionando_en_streaming,
    e4_submuestrear_indices_respeta_max,
    e4_figura_3d_no_supera_el_tope,
    e4_figura_3d_declara_conteo_aunque_no_recorte,
    e4_submuestreo_no_toca_la_poblacion_real,
]


def test_e_escala():
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
    print("✓ E COMPLETA (E.2 reorientado al parseo) — todas las verificaciones pasaron.")
    print("=" * 72)
