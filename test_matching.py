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

DQ_PATH  = _find("GEOMECH_DQ",  ["*DQ*P40*.xml", "*DQMGN*.xml", "*DQ*.xml"])
MW_PATH  = _find("GEOMECH_MW",  ["*MW*P41*H5*.xml", "*MWMGN*.xml", "*MW*.xml"])
DXF_PATH = _find("GEOMECH_DXF", ["*Metandesitas*.dxf", "*.dxf"])


def _reset_state():
    """Deja el estado global limpio entre tests."""
    gw.wells.clear()
    gw.layers.clear()
    gw.domains.clear()
    gw.parse_warnings.clear()
    gw.global_center = None


# ─── TEST (c): multi-DQ hermanos ──────────────────────────────────────────────
def test_multi_dq_hermanos():
    assert DQ_PATH and os.path.exists(DQ_PATH), "No se encontró el DQ real."
    assert MW_PATH and os.path.exists(MW_PATH), "No se encontró el MW real."
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
    assert DQ_PATH and MW_PATH, "Faltan XML reales."
    if not (DXF_PATH and os.path.exists(DXF_PATH)):
        print("[TEST e2e] OMITIDO — no se encontró el DXF Metandesitas "
              "(define GEOMECH_DXF o colócalo en ./test_data).")
        return None
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


if __name__ == "__main__":
    print("=" * 70)
    print("  test_matching.py — validación T1 (matching robusto MW↔DQ)")
    print("=" * 70)
    print(f"  DQ : {DQ_PATH}")
    print(f"  MW : {MW_PATH}")
    print(f"  DXF: {DXF_PATH}")
    print(f"  Hermanos reales: {'sí' if _have_real_hermanos() else 'no'} ({_HDIR})")
    print("-" * 70)
    ok = True
    def _run(fn, tag):
        global ok
        try:
            fn()
        except AssertionError as e:
            ok = False; print(f"[{tag}] FALLÓ: {e}")

    _run(test_multi_dq_hermanos, "TEST c")
    _run(test_end_to_end, "TEST e2e")
    if _have_real_hermanos():
        _run(test_real_hermanos_exact, "hermanos-exact")
        _run(test_real_fallback_no_exact, "hermanos-fallback")
        _run(test_real_coherence_rejection, "rechazo-coherencia")
        _run(test_real_all_p41_holes_no_wrong_fan, "no-wrong-fan")
    else:
        print("Tests de hermanos reales OMITIDOS (faltan DQ P39/P40/P41/P42 o MW P41H5).")
    print("-" * 70)
    print("RESULTADO:", "✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
    sys.exit(0 if ok else 1)
