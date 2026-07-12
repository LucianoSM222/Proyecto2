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


if __name__ == "__main__":
    print("=" * 70)
    print("  test_matching.py — validación T1 (matching robusto MW↔DQ)")
    print("=" * 70)
    print(f"  DQ : {DQ_PATH}")
    print(f"  MW : {MW_PATH}")
    print(f"  DXF: {DXF_PATH}")
    print("-" * 70)
    ok = True
    try:
        test_multi_dq_hermanos()
    except AssertionError as e:
        ok = False; print(f"[TEST c] FALLÓ: {e}")
    try:
        test_end_to_end()
    except AssertionError as e:
        ok = False; print(f"[TEST e2e] FALLÓ: {e}")
    print("-" * 70)
    print("RESULTADO:", "✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
    sys.exit(0 if ok else 1)
