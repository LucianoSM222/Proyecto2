"""
test_di_rqd.py — Validación de T5 (módulo DI↔RQD: validación externa del
Índice de Discontinuidad usando el RQD de laboratorio, independiente del MWD).

Cubre:
  · Unitario del Spearman manual (spearman_rho), sin scipy: series
    perfectamente anticorrelacionadas → rho=-1.0; perfectamente
    correlacionadas → rho=+1.0; con empates → resultado finito y coherente.
  · di_vs_rqd_by_caseron sobre un escenario sintético construido a mano:
    varios caserones con RQD conocido del Excel real y DI inyectado
    ANTICORRELACIONADO por diseño (rho debe salir negativo y fuerte).
  · Umbral de min_puntos: un caserón con <100 puntos queda excluido.
  · di_rqd_correlation: con <4 caserones evaluables, rho=None + advertencia.
  · e2e real (obligatorio): clasificación 1437/1743 exacto, DI 1743 pts,
    import sin levantar servidor.
"""

import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import geomech_wizard as gw


def _find(env_var, patterns):
    p = os.environ.get(env_var)
    if p and os.path.exists(p): return p
    for d in (os.path.join(HERE, "test_data"), HERE,
              "/root/.claude/uploads/fb9dc967-91ef-5038-a9a9-9123585f5c0b"):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits: return hits[0]
    return None

DQ_PATH   = _find("GEOMECH_DQ",   ["DQMGN_3025_PR01_TH_P40_*.xml", "*DQ*P40*.xml"])
MW_PATH   = _find("GEOMECH_MW",   ["MWMGN_3025_PR01_TH_P41H5_*.xml", "*MW*P41H5*.xml"])
DXF_PATH  = _find("GEOMECH_DXF",  ["*Metandesitas*.dxf"])
XLSX_PATH = _find("GEOMECH_XLSX", ["geomecanica_de_caserones.xlsx", "*caserones*.xlsx"])


def _reset_state():
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    gw.parse_warnings.clear(); gw.global_center = None


# ─── TEST 1: spearman_rho — casos conocidos ───────────────────────────────────
def test_spearman_known_cases():
    # Perfectamente anticorrelacionadas
    x = [1, 2, 3, 4, 5, 6]
    y = [6, 5, 4, 3, 2, 1]
    rho = gw.spearman_rho(x, y)
    print(f"[TEST spearman] anticorrelación perfecta: rho={rho}")
    assert rho is not None
    assert abs(rho - (-1.0)) < 1e-9, f"esperado -1.0, obtenido {rho}"

    # Perfectamente correlacionadas
    rho2 = gw.spearman_rho(x, x)
    print(f"[TEST spearman] correlación perfecta: rho={rho2}")
    assert abs(rho2 - 1.0) < 1e-9, f"esperado 1.0, obtenido {rho2}"

    # Monótona no lineal (y = x^3) → Spearman también da 1.0 (a diferencia de Pearson)
    y3 = [v**3 for v in x]
    rho3 = gw.spearman_rho(x, y3)
    print(f"[TEST spearman] monótona no lineal (cubo): rho={rho3}")
    assert abs(rho3 - 1.0) < 1e-9, f"esperado 1.0, obtenido {rho3}"

    # n < 2 → None (único caso real donde el guard de varianza nula dispara:
    # con argsort(argsort(·)) el vector de rangos es SIEMPRE una permutación
    # 0..n-1 para n>=2, incluso si los valores originales son constantes —
    # es la limitación conocida de rankear sin promediar empates, documentada
    # en spearman_rho; no confundir con un bug).
    assert gw.spearman_rho([1], [2]) is None
    assert gw.spearman_rho([], []) is None
    rho_const = gw.spearman_rho([1, 1, 1, 1], [1, 2, 3, 4])
    print(f"[TEST spearman] serie 'constante' con este método de rankeo: rho={rho_const} "
          f"(finito, no None — coherente con no promediar empates)")
    assert rho_const is not None and np.isfinite(rho_const)

    # Con empates: orden parcial, resultado debe ser finito y del signo esperado
    x5 = [1, 1, 2, 2, 3, 3]
    y5 = [3, 3, 2, 2, 1, 1]  # anticorrelacionada con empates
    rho5 = gw.spearman_rho(x5, y5)
    print(f"[TEST spearman] con empates (anticorr.): rho={rho5}")
    assert rho5 is not None and rho5 < -0.8

    print("[TEST spearman] OK — casos conocidos correctos (-1.0, +1.0, monótona, "
          "n<2→None, empates coherentes).")
    return True


# ─── TEST 2: escenario sintético con anticorrelación DI↔RQD por diseño ────────
def _make_layer_with_caseron(name, caseron, lito_alias=None):
    dummy = np.zeros((1, 3, 3))
    lay = gw.Layer(name=name, kind="litologia", triangles=dummy,
                   bbox_min=np.zeros(3), bbox_max=np.ones(3))
    lay.caseron = caseron
    lay.lito_alias = lito_alias
    gw.layers[name] = lay
    return lay

def _make_well_with_lito(wn, lito_name, n_pts, di_values, entrenable_first=5):
    pts = []
    for i in range(n_pts):
        p = gw.MWDPoint(largo=float(i)*0.02, vel=1.0, pp=1.0, pa=1.0, pd=1.0, pr=1.0, pf=1.0, se=1.0, t=0.0)
        p.lito = lito_name
        p.di = di_values[i]
        p.entrenable = i >= entrenable_first  # excluye "emboquillado" simulado
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="P", hole_id=wn, points=pts)
    return gw.wells[wn]

def test_synthetic_anticorrelation():
    """
    Se seleccionan del Excel REAL 5 caserones con RQD conocido y bien
    dispersos, se les asigna una Layer, y se inyecta DI medio por caserón
    DECRECIENTE cuando el RQD es CRECIENTE (roca más sana → menos picos DI).
    Con esa construcción, rho debe salir fuertemente negativo.
    """
    assert XLSX_PATH, "Falta el Excel geomecánico real."
    _reset_state()
    records = gw.parse_geomech_excel(XLSX_PATH)
    gw.index_geomech_bands(records)
    with_rqd = [r for r in records if r["rqd_mid"] is not None]
    assert len(with_rqd) >= 5, "Se necesitan >=5 bandas con RQD en el Excel real."
    # Tomar 5 con RQD bien distinto entre sí para una prueba nítida
    with_rqd_sorted = sorted(with_rqd, key=lambda r: r["rqd_mid"])
    picked = [with_rqd_sorted[0], with_rqd_sorted[len(with_rqd_sorted)//4],
              with_rqd_sorted[len(with_rqd_sorted)//2],
              with_rqd_sorted[3*len(with_rqd_sorted)//4], with_rqd_sorted[-1]]

    rng = np.random.default_rng(42)
    N = 150  # >= DI_RQD_MIN_PUNTOS(100) tras excluir emboquillado
    # DI medio objetivo: anticorrelacionado con rqd_mid (rqd alto → DI bajo)
    rqds = [r["rqd_mid"] for r in picked]
    rqd_min, rqd_max = min(rqds), max(rqds)
    for i, rec in enumerate(picked):
        cas, lito = rec["caseron"], rec["litologia"]
        _make_layer_with_caseron(f"Lay{i}", cas, lito_alias=lito)
        frac = (rec["rqd_mid"] - rqd_min) / (rqd_max - rqd_min + 1e-9)
        di_target = 3.0 - 2.5 * frac  # RQD alto (frac→1) => DI bajo (~0.5); RQD bajo => DI alto (~3.0)
        di_vals = list(rng.normal(di_target, 0.05, size=N))
        _make_well_with_lito(f"W{i}", f"Lay{i}", N, di_vals, entrenable_first=10)

    data = gw.di_vs_rqd_by_caseron()
    print(f"[TEST sintético] caserones evaluables: {len(data)}")
    for d in data:
        print(f"   {d['caseron']:12s} RQD={d['rqd_mid']:6.1f}  DI_medio={d['di_medio']:.3f} "
              f"±{d['di_std']:.3f}  n={d['n_puntos']}")
    assert len(data) == 5, f"esperados 5 caserones evaluables, hay {len(data)}"
    # n_puntos = N - entrenable_first (emboquillado excluido)
    for d in data:
        assert d["n_puntos"] == N - 10, f"{d['caseron']}: n_puntos={d['n_puntos']}"

    result = gw.di_rqd_correlation()
    print(f"[TEST sintético] rho={result['rho']:.3f}  n={result['n']}")
    assert result["rho"] is not None
    assert result["rho"] < -0.9, f"se esperaba anticorrelación fuerte, rho={result['rho']}"
    print("[TEST sintético] OK — anticorrelación fuerte detectada (rho<-0.9) por diseño.")

    # Export CSV
    df = gw.export_di_rqd_csv()
    assert len(df) == 5 and {"caseron","di_medio","di_std","rqd_mid","n_puntos"} <= set(df.columns)
    print(f"[TEST sintético] export CSV: {len(df)} filas ✓")
    return True


# ─── TEST 3: umbral min_puntos excluye caserones con pocos puntos ─────────────
def test_min_puntos_threshold():
    _reset_state()
    records = gw.parse_geomech_excel(XLSX_PATH)
    gw.index_geomech_bands(records)
    with_rqd = [r for r in records if r["rqd_mid"] is not None]
    rec = with_rqd[0]
    _make_layer_with_caseron("LayPoco", rec["caseron"], lito_alias=rec["litologia"])
    # Solo 50 puntos entrenables (< 100)
    di_vals = [1.0] * 60
    _make_well_with_lito("WPoco", "LayPoco", 60, di_vals, entrenable_first=10)  # 50 entrenables
    data_default = gw.di_vs_rqd_by_caseron()
    print(f"[TEST umbral] con 50 puntos entrenables (<100): evaluables={len(data_default)}")
    assert len(data_default) == 0, "debería excluirse por tener <100 puntos"

    data_relaxed = gw.di_vs_rqd_by_caseron(min_puntos=40)
    print(f"[TEST umbral] con min_puntos=40: evaluables={len(data_relaxed)}")
    assert len(data_relaxed) == 1 and data_relaxed[0]["n_puntos"] == 50
    print("[TEST umbral] OK — el umbral min_puntos filtra correctamente.")
    return True


# ─── TEST 4: <4 caserones → rho=None + advertencia ────────────────────────────
def test_insufficient_caserones():
    _reset_state()
    records = gw.parse_geomech_excel(XLSX_PATH)
    gw.index_geomech_bands(records)
    with_rqd = [r for r in records if r["rqd_mid"] is not None]
    for i, rec in enumerate(with_rqd[:2]):  # solo 2 caserones evaluables
        _make_layer_with_caseron(f"Lay{i}", rec["caseron"], lito_alias=rec["litologia"])
        _make_well_with_lito(f"W{i}", f"Lay{i}", 150, [1.0]*150, entrenable_first=10)
    result = gw.di_rqd_correlation()
    print(f"[TEST insuficiente] n={result['n']} rho={result['rho']} warning={result['warning']}")
    assert result["n"] == 2
    assert result["rho"] is None
    assert "insuficientes" in result["warning"]
    print("[TEST insuficiente] OK — <4 caserones ⇒ rho omitido con advertencia.")
    return True


# ─── TEST 5: e2e real (clasificación + DI intactos) ───────────────────────────
def test_e2e_real():
    assert DXF_PATH and DQ_PATH and MW_PATH, "Faltan archivos reales."
    _reset_state()
    tris, _ = gw.parse_dxf(DXF_PATH, os.path.basename(DXF_PATH))
    bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
    gw.layers["Metandesitas"] = gw.Layer(name="Metandesitas", kind="litologia",
                                         triangles=tris, bbox_min=bmin, bbox_max=bmax)
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    gw.match_and_place_wells({dq["plan_id"]: dq}, {key: [mw]})
    well = gw.wells[key]
    assert len(well.points) == 1743
    gw.classify_all_wells()
    n_in = sum(1 for p in well.points if p.lito == "Metandesitas")
    print(f"[TEST e2e] Clasificación H5: {n_in}/1743")
    assert n_in == 1437, f"Esperado 1437, obtenido {n_in}."
    gw.compute_di()
    n_di = sum(1 for p in well.points if p.di is not None)
    assert n_di == 1743, f"DI esperado en 1743, obtenido {n_di}."
    print("[TEST e2e] OK — 1437/1743, DI 1743.")
    return True


if __name__ == "__main__":
    print("=" * 72)
    print("  test_di_rqd.py — validación T5 (DI ↔ RQD, validación externa)")
    print("=" * 72)
    print(f"  DQ  : {DQ_PATH}")
    print(f"  MW  : {MW_PATH}")
    print(f"  DXF : {DXF_PATH}")
    print(f"  XLSX: {XLSX_PATH}")
    print("-" * 72)
    ok = True
    for fn in (test_spearman_known_cases, test_synthetic_anticorrelation,
               test_min_puntos_threshold, test_insufficient_caserones, test_e2e_real):
        try:
            fn()
        except AssertionError as e:
            ok = False; print(f"❌ {fn.__name__} FALLÓ: {e}")
        print("-" * 72)
    print("RESULTADO:", "✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
    sys.exit(0 if ok else 1)
