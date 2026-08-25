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

Usa los DXF reales del repo (FM2.dxf, Bht.dxf) para el caso end-to-end; el
resto son fixtures sintéticas mínimas.
"""

import os, sys, glob, shutil, hashlib, time

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
ALL_TESTS = [
    e2a_hash_contenido,
    e2a_cache_evita_reparseo,
    e2a_contenidos_distintos_no_colisionan,
    e2a_aviso_de_omitidas_se_reemite_en_acierto,
    e2a_real_end_to_end,
    e2b_firma_cambia_con_lo_relevante,
    e2b_firma_estable_con_lo_irrelevante,
    e2c_memoiza_reclasificaciones_redundantes,
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
