"""
test_matching.py — Validación del matching robusto MW↔DQ (T1) y del pipeline
end-to-end con los archivos reales de Pucobre.

Cubre:
  · TEST (c) — Matching con multi-DQ hermanos: se carga el DQ real, se duplica
    en memoria con plan_id alterado ("...P41", que matchea EXACTO con el MW) y
    con la geometría del collar desplazada +50 m en Norte. Se verifica que el
    matching elige el DQ ORIGINAL (P40), cuyo collar cumple la coherencia de
    largo, y NO el twin desplazado, aunque el plan_id del twin matchee mejor.

  · TEST end-to-end (requiere el DXF Metandesitas): parseo de los 3 archivos,
    matching del pozo H5 (debe quedar "matched"/"fallback_hole", NUNCA
    "ambiguous"), clasificación contra Metandesitas = EXACTAMENTE 1437/1743,
    y cálculo de DI sobre los 1743 puntos.

Rutas de datos: se toman de variables de entorno GEOMECH_DQ / GEOMECH_MW /
GEOMECH_DXF; si no están, se buscan en ./test_data; si tampoco, en la carpeta
de subida de la sesión. El TEST (c) solo necesita los dos XML; el end-to-end
además necesita el DXF (se omite con aviso si no está disponible).

NOTA GEOMÉTRICA IMPORTANTE (por qué se desplaza el collar y no todo el pozo):
una traslación rígida de collar Y final por igual PRESERVA la distancia
euclidiana collar→final, así que la coherencia de largo |largo−dist|/largo es
invariante a ella y NO podría distinguir el twin. Por eso el twin desplaza el
collar en Norte (que es justo el "salto en el eje Norte" reportado como
síntoma del bug), lo que rompe la coherencia de largo y da a la validación una
señal real, tal como exige el resultado esperado del test (c).
"""

import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geomech_wizard as gw
from test_support import require_real_data, SkipTest, fixture, skipped_banner


# ─── Localización de los archivos de datos ────────────────────────────────────
def _find(env_var, patterns):
    p = os.environ.get(env_var)
    if p and os.path.exists(p):
        return p
    search_dirs = [
        os.path.join(HERE, "test_data"),
        HERE,
        "/root/.claude/uploads/fb9dc967-91ef-5038-a9a9-9123585f5c0b",
    ]
    for d in search_dirs:
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits:
                return hits[0]
    return None

# (A.8) Patrones ESTRICTOS: sin el comodín de reserva, que hacía tomar
# cualquier DXF/XML presente y fallar con un mensaje confuso en vez de
# omitir el test por falta del fixture correcto.
DQ_PATH  = _find("GEOMECH_DQ",  ["DQMGN_3025_PR01_TH_P40_*.xml", "*DQ*P40*.xml"])
MW_PATH  = _find("GEOMECH_MW",  ["MWMGN_3025_PR01_TH_P41H5_*.xml", "*MW*P41H5*.xml"])
DXF_PATH = _find("GEOMECH_DXF", ["*Metandesitas*.dxf"])


def _reset_state():
    """Deja el estado global limpio entre tests."""
    gw.wells.clear()
    gw.layers.clear()
    gw.domains.clear()
    gw.parse_warnings.clear()
    gw.global_center = None


# ─── TEST (c): multi-DQ hermanos ──────────────────────────────────────────────
def test_multi_dq_hermanos():
    require_real_data(DQ=DQ_PATH, MW=MW_PATH)
    _reset_state()

    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))

    assert mw["hole_id"] == "5", f"hole_id MW inesperado: {mw['hole_id']}"
    assert dq["plan_id"] == "MGN_3025_PR01_TH_P40", f"plan DQ inesperado: {dq['plan_id']}"
    assert mw["plan_id"] == "MGN_3025_PR01_TH_P41", f"plan MW inesperado: {mw['plan_id']}"
    assert "5" in dq["tiros"], "El DQ real no trae el hole 5."

    orig_collar_norte = dq["tiros"]["5"]["collar"]["norte"]

    # Twin: plan_id alterado a P41 (== plan del MW → matchea EXACTO/mejor por
    # prefijo) y collar desplazado +50 m en Norte (rompe la coherencia de largo,
    # reproduciendo el "salto en Norte"). Ver nota geométrica en el encabezado.
    DISPLACE_N = 50.0
    alt_tiros = {}
    for hid, t in dq["tiros"].items():
        c = dict(t["collar"]); f = dict(t["final_pt"])
        c["norte"] += DISPLACE_N
        alt_tiros[hid] = {"collar": c, "final_pt": f}
    dq_alt = {"plan_id": "MGN_3025_PR01_TH_P41", "tiros": alt_tiros}

    # El twin matchea el plan del MW EXACTAMENTE (mejor que el original por prefijo)
    assert dq_alt["plan_id"] == mw["plan_id"]
    assert gw._plan_prefix_sim(mw["plan_id"], dq_alt["plan_id"]) > \
           gw._plan_prefix_sim(mw["plan_id"], dq["plan_id"]), \
           "El twin debería matchear mejor por prefijo de plan_id."

    dq_results = {dq["plan_id"]: dq, dq_alt["plan_id"]: dq_alt}
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    mw_by_hole = {key: [mw]}

    counts = gw.match_and_place_wells(dq_results, mw_by_hole)
    well = gw.wells.get(key)
    assert well is not None, "No se creó el pozo."

    # El elegido debe ser el DQ ORIGINAL (P40): collar SIN el +50 N.
    assert well.origin == "fallback_hole", \
        f"origin esperado 'fallback_hole' (twin rechazado), obtenido '{well.origin}'."
    assert abs(well.collar["norte"] - orig_collar_norte) < 1e-6, \
        "Se eligió el collar desplazado (twin) en vez del original."
    assert counts["ambiguous"] == 0 and counts["no_dq"] == 0

    # Coherencia del elegido bajo tolerancia; la del twin por encima.
    err_orig = gw._coherence_err(mw["largo_max"],
                                 dq["tiros"]["5"]["collar"], dq["tiros"]["5"]["final_pt"])
    err_twin = gw._coherence_err(mw["largo_max"],
                                 dq_alt["tiros"]["5"]["collar"], dq_alt["tiros"]["5"]["final_pt"])
    assert err_orig < gw.COHERENCE_TOL, f"El original no cumple coherencia ({err_orig:.3%})."
    assert err_twin >= gw.COHERENCE_TOL, f"El twin NO fue rechazado ({err_twin:.3%})."

    print(f"[TEST c] OK — pozo '{key}': origin={well.origin}, "
          f"collar Norte={well.collar['norte']:.3f} (original, no +50). "
          f"Coherencia original={err_orig:.3%} < {gw.COHERENCE_TOL:.0%} ; "
          f"twin={err_twin:.3%} (rechazado). "
          f"El plan_id del twin (P41) matcheaba EXACTO pero fue descartado por coherencia.")
    return True


# ─── TEST end-to-end con los archivos reales ──────────────────────────────────
def test_end_to_end():
    require_real_data(DQ=DQ_PATH, MW=MW_PATH, DXF=DXF_PATH)
    _reset_state()

    # DXF
    tris, _ = gw.parse_dxf(DXF_PATH, os.path.basename(DXF_PATH))
    bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
    name = "Metandesitas"
    gw.layers[name] = gw.Layer(name=name, kind="litologia", triangles=tris,
                               bbox_min=bmin, bbox_max=bmax)
    print(f"[TEST e2e] DXF: {len(tris)} triángulos.")

    # XML reales (DQ + MW) por la vía normal de matching
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))
    dq_results = {dq["plan_id"]: dq}
    key = f"{mw['plan_id']}_H{mw['hole_id'] or 'X'}"
    mw_by_hole = {key: [mw]}
    counts = gw.match_and_place_wells(dq_results, mw_by_hole)

    well = gw.wells[key]
    n_pts = len(well.points)
    print(f"[TEST e2e] MW '{key}': {n_pts} puntos, origin={well.origin}.")
    assert n_pts == 1743, f"Se esperaban 1743 puntos MWD, hay {n_pts}."
    assert well.origin in ("matched", "fallback_hole"), \
        f"H5 quedó '{well.origin}' (NUNCA debe ser 'ambiguous' con estos archivos)."
    assert well.origin == "fallback_hole", \
        f"Con P41(MW) vs P40(DQ) se esperaba 'fallback_hole', obtenido '{well.origin}'."

    # Clasificación geométrica contra Metandesitas
    gw.classify_all_wells()
    n_inside = sum(1 for p in well.points if p.lito == name)
    print(f"[TEST e2e] Clasificación H5 dentro de Metandesitas: {n_inside}/{n_pts}.")
    assert n_inside == 1437, f"Se esperaban EXACTAMENTE 1437 dentro, obtenidos {n_inside}."

    # DI sobre los 1743 puntos
    gw.compute_di()
    n_di = sum(1 for p in well.points if p.di is not None)
    print(f"[TEST e2e] DI calculado en {n_di}/{n_pts} puntos.")
    assert n_di == 1743, f"DI esperado en 1743 puntos, obtenido {n_di}."

    print("[TEST e2e] OK — 1437/1743 dentro, DI sobre 1743, H5=fallback_hole.")
    return True


# ─── TESTS con abanicos hermanos REALES (P39/P40/P41/P42) ─────────────────────
# Datos de campo: MW P41H5 (largo 36.07). Sus fans hermanos están ~2.5 m
# separados en Norte (P39→6960144, P40→6960141.5, P41→6960139, P42→6960136.5) y
# TODOS pasan la coherencia de largo (<5%): P39=2.0%, P40=0.25%, P41=0.0%,
# P42=0.12%. Es decir, entre hermanos verdaderos la coherencia es la RED DE
# SEGURIDAD, y el plan_id exacto es el discriminador. Estos tests lo verifican.
def _find_dir():
    for d in (os.path.join(HERE, "test_data"),
              "/root/.claude/uploads/fb9dc967-91ef-5038-a9a9-9123585f5c0b"):
        if glob.glob(os.path.join(d, "DQMGN_*P41_*.xml")):
            return d
    return None

_HDIR = _find_dir()
_SIBLINGS = {
    "P39": "DQMGN_3025_PR01_TH_P39_260519_1038.xml",
    "P40": "DQMGN_3025_PR01_TH_P40_260523_0012.xml",
    "P41": "DQMGN_3025_PR01_TH_P41_260525_1059.xml",
    "P42": "DQMGN_3025_PR01_TH_P42_260527_0506.xml",
}
_MW_P41H5 = "MWMGN_3025_PR01_TH_P41H5_260523_1430.xml"

def _load_dq_results(planes):
    res = {}
    for pl in planes:
        f = os.path.join(_HDIR, _SIBLINGS[pl])
        dq = gw.parse_dq(f, _SIBLINGS[pl])
        res[dq["plan_id"]] = dq
    return res

def _have_real_hermanos():
    if not _HDIR: return False
    return all(os.path.exists(os.path.join(_HDIR, f)) for f in _SIBLINGS.values()) \
        and os.path.exists(os.path.join(_HDIR, _MW_P41H5))

def test_real_hermanos_exact():
    """Con los 4 DQ hermanos cargados, MW P41H5 debe matchear el DQ P41 EXACTO."""
    if not _have_real_hermanos():
        raise SkipTest(
            "Faltan los DQ hermanos P39/P40/P41/P42 o el MW P41H5. "
            "Test de hermanos reales omitido.")
    _reset_state()
    dq_results = _load_dq_results(["P39", "P40", "P41", "P42"])
    mw = gw.parse_mw(os.path.join(_HDIR, _MW_P41H5), _MW_P41H5)
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    counts = gw.match_and_place_wells(dq_results, {key: [mw]})
    w = gw.wells[key]
    print(f"[TEST hermanos-exact] origin={w.origin} plan={gw._plan_short(w.plan_id)} "
          f"collarN={w.collar['norte']:.1f} counts={counts}")
    assert w.origin == "matched", f"esperado matched, obtenido {w.origin}"
    assert gw._plan_short(w.plan_id) == "P41"
    # Collar del fan P41 (~6960139), NO de otro hermano
    assert abs(w.collar["norte"] - 6960139.0) < 1.0, "collar de fan equivocado"
    err = gw._coherence_err(mw["largo_max"], w.collar, w.final_pt)
    assert err < 0.01, f"coherencia del exacto debería ser ~0%, es {err:.2%}"
    print("[TEST hermanos-exact] OK — P41 exacto, coherencia 0%, sin salto de fan.")
    return True

def test_real_fallback_no_exact():
    """Sin el DQ P41, MW P41H5 cae a un hermano COHERENTE (no ambiguo)."""
    if not _have_real_hermanos():
        raise SkipTest(
            "Faltan los DQ hermanos P39/P40/P41/P42 o el MW P41H5. "
            "Test de hermanos reales omitido.")
    _reset_state()
    dq_results = _load_dq_results(["P39", "P40", "P42"])  # sin P41
    mw = gw.parse_mw(os.path.join(_HDIR, _MW_P41H5), _MW_P41H5)
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    counts = gw.match_and_place_wells(dq_results, {key: [mw]})
    w = gw.wells[key]
    err = gw._coherence_err(mw["largo_max"], w.collar, w.final_pt)
    print(f"[TEST hermanos-fallback] origin={w.origin} collarN={w.collar['norte']:.1f} "
          f"err={err:.2%} counts={counts}")
    assert w.origin == "fallback_hole", f"esperado fallback_hole, obtenido {w.origin}"
    assert counts["ambiguous"] == 0, "no debería quedar ambiguo (hay hermanos coherentes)"
    assert err < 0.05, f"el hermano elegido debe cumplir coherencia, err={err:.2%}"
    print("[TEST hermanos-fallback] OK — fallback a hermano coherente (P40), sin ambiguo.")
    return True

def test_real_coherence_rejection():
    """
    Red de seguridad con geometría REAL: se corrompe el hole 5 del DQ P41
    (match EXACTO de plan) reemplazándolo por la geometría del hole 1 (19.4 m,
    muy corta). La coherencia debe RECHAZAR ese exacto (err ~46%) y caer a un
    hermano coherente. origin pasa a fallback_hole y el collar NO es el corrupto.
    """
    if not _have_real_hermanos():
        raise SkipTest(
            "Faltan los DQ hermanos P39/P40/P41/P42 o el MW P41H5. "
            "Test de hermanos reales omitido.")
    _reset_state()
    dq_results = _load_dq_results(["P39", "P40", "P41", "P42"])
    mw = gw.parse_mw(os.path.join(_HDIR, _MW_P41H5), _MW_P41H5)
    p41 = dq_results["MGN_3025_PR01_TH_P41"]
    # Corromper: hole 5 recibe la geometría (corta) del hole 1
    hole1 = p41["tiros"]["1"]
    corrupt_collar = dict(hole1["collar"])
    p41["tiros"]["5"] = {"collar": corrupt_collar, "final_pt": dict(hole1["final_pt"])}
    err_corrupt = gw._coherence_err(mw["largo_max"], corrupt_collar, hole1["final_pt"])
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    counts = gw.match_and_place_wells(dq_results, {key: [mw]})
    w = gw.wells[key]
    err_chosen = gw._coherence_err(mw["largo_max"], w.collar, w.final_pt)
    print(f"[TEST rechazo-coherencia] P41(corrupto) err={err_corrupt:.1%} RECHAZADO → "
          f"origin={w.origin} collarN={w.collar['norte']:.1f} err_elegido={err_chosen:.2%}")
    assert err_corrupt > 0.05, "el hole 5 corrupto debería violar coherencia"
    assert w.origin == "fallback_hole", f"esperado fallback_hole, obtenido {w.origin}"
    # No se usó el collar corrupto (el del hole 1)
    assert abs(w.collar["norte"] - corrupt_collar["norte"]) > 1.0
    assert err_chosen < 0.05, "el hermano elegido debe cumplir coherencia"
    print("[TEST rechazo-coherencia] OK — exacto-pero-incoherente descartado, "
          "hermano coherente elegido.")
    return True

def test_real_all_p41_holes_no_wrong_fan():
    """
    Bug original: al cargar varios hermanos, un hole_id común podía asignarse al
    fan EQUIVOCADO. Aquí se cargan TODOS los MW del plan P41 + los 4 DQ hermanos
    y se verifica la garantía anti-bug:

      · NINGÚN pozo P41 termina colocado en un fan hermano (fallback == 0):
        cuando el DQ P41 propio existe y es coherente, se usa; si su hole propio
        NO es coherente (perforación parcial), se marca ambiguo en vez de saltar
        a un hermano equivocado.
      · Todo pozo 'matched' cae en el fan P41 con coherencia < 5%.
      · Todo pozo 'ambiguous' realmente incumple la coherencia con su hole P41
        (caso legítimo: MWD más corto que el hole planificado, p.ej. H6 = 31.3 m
        de un hole de ~36 m → todos los hermanos > 5%).
    """
    if not _have_real_hermanos():
        raise SkipTest(
            "Faltan los DQ hermanos P39/P40/P41/P42 o el MW P41H5. "
            "Test de hermanos reales omitido.")
    _reset_state()
    dq_results = _load_dq_results(["P39", "P40", "P41", "P42"])
    p41 = dq_results["MGN_3025_PR01_TH_P41"]
    mw_files = sorted(glob.glob(os.path.join(_HDIR, "MWMGN_3025_PR01_TH_P41H*_*.xml")))
    if not mw_files:
        print("[TEST no-wrong-fan] OMITIDO — sin MW P41 adicionales."); return None
    mw_by_hole = {}
    for f in mw_files:
        mw = gw.parse_mw(f, os.path.basename(f))
        if not mw["hole_id"]: continue
        mw_by_hole.setdefault(f"{mw['plan_id']}_H{mw['hole_id']}", []).append(mw)
    counts = gw.match_and_place_wells(dq_results, mw_by_hole)
    n_total = len(gw.wells)
    matched = [w for w in gw.wells.values() if w.origin == "matched"]
    ambiguous = [(wn, w) for wn, w in gw.wells.items() if w.origin == "ambiguous"]
    print(f"[TEST no-wrong-fan] {n_total} pozos P41 → matched={len(matched)} "
          f"ambiguos={len(ambiguous)} counts={counts}")

    # GARANTÍA ANTI-BUG: ningún P41 colocado en fan hermano.
    assert counts["fallback"] == 0, "¡un pozo P41 fue colocado en un fan hermano!"
    assert counts["no_dq"] == 0

    # Los 'matched' están en el fan P41 y son coherentes.
    for w in matched:
        assert gw._plan_short(w.plan_id) == "P41"
        err = gw._coherence_err(max(m["largo_max"] for m in mw_by_hole[w.well_name]),
                                w.collar, w.final_pt)
        assert err < 0.05, f"{w.well_name}: matched pero err={err:.2%}"

    # Cada 'ambiguous' realmente incumple coherencia con su propio hole P41.
    for wn, w in ambiguous:
        hid = w.hole_id
        L = max(m["largo_max"] for m in mw_by_hole[wn])
        t = p41["tiros"].get(hid)
        assert t is not None, f"{wn}: hole {hid} ausente en P41"
        err_p41 = gw._coherence_err(L, t["collar"], t["final_pt"])
        print(f"   · ambiguo {wn}: largo={L:.2f} err_P41={err_p41:.1%} "
              f"(perforación parcial legítima)")
        assert err_p41 >= 0.05, f"{wn}: marcado ambiguo pero P41 sí era coherente"

    print("[TEST no-wrong-fan] OK — 0 saltos de fan; matched coherentes; "
          "ambiguos justificados por incoherencia real.")
    return True


# ─── Convención de campos de <Val>: 7 exactos, excedente REPORTADO ────────────
# Los Simba COPROD de Pucobre declaran una 8ª columna OPT1 ("DRMWDoption").
# Se descarta del uso, pero descartarla en silencio sería indistinguible de un
# cambio de esquema del equipo, que sí invalidaría el orden de los 7.
_MW_EXTRA_PATHS = sorted(glob.glob(os.path.join(HERE, "test_data", "MWPCC_0042_*.xml")))


def test_campo_excedente_se_reporta():
    require_real_data(MW_PCC_0042=(_MW_EXTRA_PATHS[0] if _MW_EXTRA_PATHS else None))
    _reset_state()
    path = _MW_EXTRA_PATHS[0]
    fname = os.path.basename(path)
    mw = gw.parse_mw(path, fname)

    assert mw["puntos"], f"{fname}: no se parseó ningún punto"
    avisos = [w for w in gw.parse_warnings if "excedente" in w]
    print(f"[TEST excedente] {fname}: {len(mw['puntos'])} pts, "
          f"{len(avisos)} aviso(s) de campo excedente")
    assert len(avisos) == 1, (
        f"El campo excedente debe reportarse EXACTAMENTE una vez por archivo; "
        f"hubo {len(avisos)}: {avisos}")
    assert "OPT1" in avisos[0], f"El aviso debe nombrar el campo descartado: {avisos[0]}"
    for campo in gw.MWD_VAL_ORDER:
        assert campo in avisos[0], f"El aviso debe declarar el orden vigente: falta {campo}"

    # Los 7 campos de la convención se leen en el orden correcto: el primer
    # <Val> del archivo, comparado contra el punto ya parseado.
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    crudo = [float(x) for x in
             root.find(f".//{gw.DR}Sample/{gw.DR}Val").text.strip().split()]
    assert len(crudo) == gw.MWD_VAL_FIELDS + 1, (
        f"El fixture debe traer 1 campo excedente; trae {len(crudo)}")
    p = mw["puntos"][0]
    lt, rop, pp, fp_feed, dp, rp, flp = crudo[:gw.MWD_VAL_FIELDS]
    leido = [p.largo, p.vel, p.pp, p.pa, p.pd, p.pr, p.pf]
    assert leido == [lt, rop, pp, fp_feed, dp, rp, flp], (
        f"Orden de <Val> alterado: esperado {[lt,rop,pp,fp_feed,dp,rp,flp]}, "
        f"leído {leido}")
    print("[TEST excedente] OK — OPT1 descartado y reportado una vez; "
          "orden LT|ROP|PP|FP|DP|RP|FLP intacto.")
    return True


# ─── Fusión de DQ hermanos del MISMO plan (carga a escala) ───────────────────
# Un abanico real se re-releva varias veces: PCS_1043 trae 56 archivos DQ para
# 34 planes, y P107 solo tiene cuatro revisiones (23, 14, 13 y 13 tiros).
# Quedarse con UNA sola —la primera o la última que llegue— pierde los tiros
# que solo aparecen en las otras, y con ellos el MWD que los referencia: sin
# fusionar, PCS_1043 daba 345 pozos ambiguos de 468; fusionando, 9.
#
# Pero fusionar en silencio sería igual de malo: 138 de 344 tiros repetidos
# traen coordenadas DISTINTAS entre revisiones (mediana 1,3 m, 34 casos sobre
# 20 m). Ese desacuerdo es un dato geológico, no ruido, y debe declararse.

def _mk_dq(plan_id, tiros, fecha=""):
    return {"plan_id": plan_id, "tiros": tiros, "fecha": fecha, "fname": f"{plan_id}_{fecha}.xml"}


def _tiro(e, n, z, largo=10.0):
    return {"collar": {"este": e, "norte": n, "cota": z},
            "final_pt": {"este": e + largo, "norte": n, "cota": z}}


def test_merge_dq_une_tiros_de_revisiones():
    """Los tiros que solo existen en una revisión NO se pierden."""
    _reset_state()
    dqs = [
        _mk_dq("P1", {"1": _tiro(0, 0, 0), "2": _tiro(1, 0, 0)}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P1", {"2": _tiro(1, 0, 0), "3": _tiro(2, 0, 0)}, fecha="2026-01-02T00:00:00"),
    ]
    merged, rep = gw.merge_dq_siblings(dqs)
    assert set(merged) == {"P1"}, f"debe quedar un solo plan: {list(merged)}"
    assert set(merged["P1"]["tiros"]) == {"1", "2", "3"}, (
        f"los tres tiros deben sobrevivir la fusión: {sorted(merged['P1']['tiros'])}")
    assert rep["n_planes"] == 1 and rep["n_archivos"] == 2
    assert rep["n_tiros"] == 3, rep
    assert not rep["conflictos"], f"tiros idénticos no son conflicto: {rep['conflictos']}"
    print(f"[TEST merge-dq] OK — 2 revisiones → 3 tiros únicos, 0 conflictos.")
    return True


def test_merge_dq_gana_el_mas_reciente_y_lo_declara():
    """Ante coordenadas distintas para el mismo tiro gana la revisión más
    reciente, y el desacuerdo se REPORTA con su magnitud."""
    _reset_state()
    dqs = [
        _mk_dq("P1", {"1": _tiro(0, 0, 0)}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P1", {"1": _tiro(30, 40, 0)}, fecha="2026-03-01T00:00:00"),   # 50 m
    ]
    merged, rep = gw.merge_dq_siblings(dqs)
    c = merged["P1"]["tiros"]["1"]["collar"]
    assert (c["este"], c["norte"]) == (30, 40), f"debe ganar el más reciente: {c}"
    assert len(rep["conflictos"]) == 1, rep["conflictos"]
    con = rep["conflictos"][0]
    assert con["plan_id"] == "P1" and con["hole_id"] == "1"
    assert abs(con["dist_m"] - 50.0) < 1e-6, con
    assert "2026-03-01" in con["gana"], con

    # El orden de llegada NO decide: fusionar al revés da el mismo ganador.
    merged2, _ = gw.merge_dq_siblings(list(reversed(dqs)))
    c2 = merged2["P1"]["tiros"]["1"]["collar"]
    assert (c2["este"], c2["norte"]) == (30, 40), (
        f"el ganador debe depender de la fecha, no del orden de carga: {c2}")
    print("[TEST merge-dq] OK — gana el más reciente, conflicto de 50 m declarado.")
    return True


def test_merge_dq_avisa_desplazamientos_grandes():
    """Un desplazamiento sobre el umbral se registra como advertencia visible."""
    _reset_state()
    gw.parse_warnings.clear()
    dqs = [
        _mk_dq("P1", {"1": _tiro(0, 0, 0)}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P1", {"1": _tiro(0, 0, 0.05)}, fecha="2026-02-01T00:00:00"),   # 5 cm
        _mk_dq("P2", {"9": _tiro(0, 0, 0)}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P2", {"9": _tiro(0, 0, 99.0)}, fecha="2026-02-01T00:00:00"),   # 99 m
    ]
    _, rep = gw.merge_dq_siblings(dqs)
    grandes = [c for c in rep["conflictos"] if c["dist_m"] > gw.DQ_MERGE_WARN_M]
    assert len(grandes) == 1 and grandes[0]["plan_id"] == "P2", rep["conflictos"]
    avisos = [w for w in gw.parse_warnings if "P2" in w and "9" in w]
    assert avisos, f"el desplazamiento grande debe avisarse: {gw.parse_warnings}"
    print(f"[TEST merge-dq] OK — 5 cm no alarma, 99 m sí ({len(grandes)} aviso).")
    return True


def test_merge_dq_ignora_planes_vacios():
    """Un archivo sin plan_id o sin tiros (p.ej. un plan de perforación mal
    clasificado como DQ) no puede entrar como plan fantasma."""
    _reset_state()
    dqs = [
        _mk_dq("", {}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P1", {}, fecha="2026-01-01T00:00:00"),
        _mk_dq("P2", {"1": _tiro(0, 0, 0)}, fecha="2026-01-01T00:00:00"),
    ]
    merged, rep = gw.merge_dq_siblings(dqs)
    assert set(merged) == {"P2"}, f"solo el plan con tiros sobrevive: {list(merged)}"
    assert rep["n_descartados"] == 2, rep
    print("[TEST merge-dq] OK — plan vacío y plan sin tiros descartados y contados.")
    return True


def test_parse_dq_expone_fecha():
    """parse_dq debe traer la fecha del DQ: sin ella no hay criterio de
    'más reciente' que no sea el orden arbitrario del sistema de archivos."""
    require_real_data(DQ=DQ_PATH)
    _reset_state()
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    assert "fecha" in dq, f"parse_dq debe exponer 'fecha': {list(dq)}"
    assert dq["fecha"], "la fecha no puede venir vacía en un DQ real"
    assert dq.get("fname"), "parse_dq debe recordar de qué archivo vino"
    print(f"[TEST merge-dq] OK — parse_dq expone fecha={dq['fecha']}.")
    return True


if __name__ == "__main__":
    print("=" * 70)
    print("  test_matching.py — validación T1 (matching robusto MW↔DQ)")
    print("=" * 70)
    print(f"  DQ : {DQ_PATH}")
    print(f"  MW : {MW_PATH}")
    print(f"  DXF: {DXF_PATH}")
    print(f"  Hermanos reales: {'sí' if _have_real_hermanos() else 'no'} ({_HDIR})")
    print("-" * 70)
    ok = True; n_skip = 0
    def _run(fn, tag):
        global ok, n_skip
        try:
            fn()
        except SkipTest as e:
            n_skip += 1; print(skipped_banner(tag, str(e)))
        except AssertionError as e:
            ok = False; print(f"[{tag}] FALLÓ: {e}")

    _run(test_multi_dq_hermanos, "TEST c")
    _run(test_end_to_end, "TEST e2e")
    _run(test_campo_excedente_se_reporta, "campo-excedente")
    _run(test_merge_dq_une_tiros_de_revisiones, "merge-dq-une")
    _run(test_merge_dq_gana_el_mas_reciente_y_lo_declara, "merge-dq-reciente")
    _run(test_merge_dq_avisa_desplazamientos_grandes, "merge-dq-avisa")
    _run(test_merge_dq_ignora_planes_vacios, "merge-dq-vacios")
    _run(test_parse_dq_expone_fecha, "merge-dq-fecha")
    if _have_real_hermanos():
        _run(test_real_hermanos_exact, "hermanos-exact")
        _run(test_real_fallback_no_exact, "hermanos-fallback")
        _run(test_real_coherence_rejection, "rechazo-coherencia")
        _run(test_real_all_p41_holes_no_wrong_fan, "no-wrong-fan")
    else:
        print("Tests de hermanos reales OMITIDOS (faltan DQ P39/P40/P41/P42 o MW P41H5).")
    print("-" * 70)
    print("RESULTADO:", ("✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
          + (f"  ({n_skip} omitido(s) por falta de datos)" if n_skip else ""))
    sys.exit(0 if ok else 1)
