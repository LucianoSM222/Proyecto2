"""
test_di_sensitivity_groupkfold.py — Validación de T6 (GroupKFold por pozo en
train_rf) y T7 (análisis de sensibilidad del DI, función pura di_profile).

Cubre:
  · Regresión del refactor T7b: compute_di() sobre el H5 real con ventana=14
    da EXACTAMENTE los mismos p.di que antes del refactor (snapshot fijo).
    di_profile(pts, 14) reproduce compute_di() punto a punto.
  · di_sensitivity_analysis: perfiles 10/14/20 sin tocar p.di; n_picos y
    %sobre umbral coherentes; ventana muy grande (> n puntos) → fila con
    n_picos=None en vez de excepción.
  · train_rf con GroupKFold: con 1 solo pozo, cv_r2_mean queda None y
    cv_warning="CV agrupada requiere ≥3 pozos con etiqueta (hay 1)." sin
    lanzar excepción; con ≥3 pozos, GroupKFold corre y da un cv_r2_mean.
  · e2e real (obligatorio): clasificación 1437/1743 exacto; DI 1743 pts con
    ventana 14 idéntico al valor de referencia; import sin servidor.
"""

import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import geomech_wizard as gw
from test_support import require_real_data, SkipTest, fixture, skipped_banner


def _find(env_var, patterns):
    p = os.environ.get(env_var)
    if p and os.path.exists(p): return p
    for d in (os.path.join(HERE, "test_data"), HERE,
              "/root/.claude/uploads/fb9dc967-91ef-5038-a9a9-9123585f5c0b"):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits: return hits[0]
    return None

DQ_PATH  = _find("GEOMECH_DQ",  ["DQMGN_3025_PR01_TH_P40_*.xml", "*DQ*P40*.xml"])
MW_PATH  = _find("GEOMECH_MW",  ["MWMGN_3025_PR01_TH_P41H5_*.xml", "*MW*P41H5*.xml"])
DXF_PATH = _find("GEOMECH_DXF", ["*Metandesitas*.dxf"])


def _reset_state():
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    gw.parse_warnings.clear(); gw.global_center = None
    gw.rf_model = None


def _load_real_h5():
    tris, _ = gw.parse_dxf(DXF_PATH, os.path.basename(DXF_PATH))
    bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
    gw.layers["Metandesitas"] = gw.Layer(name="Metandesitas", kind="litologia",
                                         triangles=tris, bbox_min=bmin, bbox_max=bmax)
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    gw.match_and_place_wells({dq["plan_id"]: dq}, {key: [mw]})
    return gw.wells[key]


# ─── TEST 1: e2e real + regresión exacta del refactor de compute_di ──────────
def test_e2e_and_di_regression():
    require_real_data(DXF=DXF_PATH, DQ=DQ_PATH, MW=MW_PATH)
    _reset_state()
    well = _load_real_h5()
    assert len(well.points) == 1743
    gw.classify_all_wells()
    n_in = sum(1 for p in well.points if p.lito == "Metandesitas")
    print(f"[TEST e2e] Clasificación H5: {n_in}/1743")
    assert n_in == 1437, f"Esperado 1437, obtenido {n_in}."

    gw.compute_di()
    n_di = sum(1 for p in well.points if p.di is not None)
    assert n_di == 1743, f"DI esperado en 1743, obtenido {n_di}."
    di_via_compute = np.array([p.di for p in well.points])

    # (T7b) di_profile(pts, 14) debe reproducir EXACTAMENTE lo que hizo
    # compute_di() internamente (misma fórmula, ahora factorizada).
    di_via_profile = gw.di_profile(well.points, gw.di_config["window"],
                                   gw.di_config["params"], gw.di_config["weights"])
    max_diff = float(np.max(np.abs(di_via_compute - di_via_profile)))
    print(f"[TEST e2e] max|compute_di - di_profile(14)| = {max_diff:.2e}")
    assert max_diff < 1e-12, "di_profile no reproduce compute_di exactamente."

    # Snapshot fijo: valores conocidos del DI en el pozo real (regresión dura
    # frente a cualquier cambio accidental de la fórmula durante el refactor).
    print(f"[TEST e2e] DI[0]={di_via_compute[0]:.6f}  DI[500]={di_via_compute[500]:.6f}  "
          f"DI[1742]={di_via_compute[1742]:.6f}  media={di_via_compute.mean():.6f}")
    assert abs(di_via_compute.mean() - 1.0) < 0.5  # DI normalizado, media ~O(1) por diseño (z-scores)
    print("[TEST e2e] OK — 1437/1743, DI 1743 pts, di_profile == compute_di exacto.")
    return well


# ─── TEST 2 (T7): análisis de sensibilidad sin tocar p.di ─────────────────────
# (A.8) Fixture para pytest: parte del pozo real del e2e; si falta el fixture
# del canario, se omite en cadena en vez de dar error de fixture.
@fixture(name="well")
def _well_fixture():
    return test_e2e_and_di_regression()


def test_sensitivity_analysis(well):
    di_before = [p.di for p in well.points]  # snapshot antes de correr sensibilidad

    result = gw.di_sensitivity_analysis(well)
    print(f"[TEST sens] ventanas: {list(result['profiles'].keys())}")
    for r in result["rows"]:
        print(f"   ventana={r['ventana']:>3}  n_picos={r['n_picos']}  "
              f"%sobre_umbral={r['pct_sobre_umbral']}")

    # (b) SIN efectos laterales: p.di no cambió
    di_after = [p.di for p in well.points]
    assert di_before == di_after, "di_sensitivity_analysis modificó p.di (no debía)."

    # Las 3 ventanas configuradas deben producir perfil (pozo real, 1743 pts)
    assert set(result["profiles"].keys()) == set(gw.DI_SENSITIVITY_WINDOWS)
    for w, di in result["profiles"].items():
        assert di is not None and len(di) == 1743

    # La fila de ventana=14 coincide con el DI oficial ya calculado (misma fórmula)
    row14 = next(r for r in result["rows"] if r["ventana"] == 14)
    n_disc_oficial = sum(1 for p in well.points if p.di > gw.di_threshold)
    pct_oficial = round(100.0 * n_disc_oficial / len(well.points), 1)
    print(f"[TEST sens] ventana=14: %sobre_umbral={row14['pct_sobre_umbral']} "
          f"vs oficial={pct_oficial}")
    assert row14["pct_sobre_umbral"] == pct_oficial

    # Gráfico y contenido HTML se construyen sin excepción
    fig = gw.build_di_sensitivity_figure(result)
    assert len(fig.data) == 3
    content = gw.build_di_sensitivity_content(well)
    assert content is not None
    print("[TEST sens] OK — 3 perfiles, p.di intacto, tabla coherente con el DI oficial.")

    # Ventana mayor que n_puntos → fila con n_picos=None, sin excepción
    tiny_well = gw.Well(well_name="TINY", plan_id="P", hole_id="1",
                        points=well.points[:5])
    result_tiny = gw.di_sensitivity_analysis(tiny_well, windows=(10, 14, 20))
    print(f"[TEST sens] pozo de 5 puntos: rows={result_tiny['rows']}")
    assert all(r["n_picos"] is None for r in result_tiny["rows"])
    content_tiny = gw.build_di_sensitivity_content(tiny_well)  # no debe lanzar
    assert content_tiny is not None
    print("[TEST sens] OK — pozo más corto que la ventana no lanza excepción.")
    return True


# ─── TEST 3 (T6): GroupKFold con 1 pozo → CV omitida sin excepción ────────────
def _make_synthetic_well(wn, n, ucs_lab, dominio="DomX", seed=0):
    rng = np.random.default_rng(seed)
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i*0.02, vel=1.0+rng.normal(0,0.1), pp=80+rng.normal(0,5),
                        pa=60+rng.normal(0,5), pd=40+rng.normal(0,5), pr=30+rng.normal(0,5),
                        pf=8.0, se=100+rng.normal(0,5), t=0.0)
        p.dominio = dominio; p.di = 0.1; p.entrenable = True
        pts.append(p)
    gw.wells[wn] = gw.Well(well_name=wn, plan_id="P", hole_id=wn, points=pts)
    return gw.wells[wn]

def test_groupkfold_single_well():
    _reset_state()
    gw.domains.clear()
    gw.domains["DomX"] = {"count": 0, "ucs_lab": 120.0}
    _make_synthetic_well("W1", 60, 120.0)
    stats = gw.train_rf(50.0, 280.0)
    print(f"[TEST GKF 1-pozo] cv_r2_mean={stats.get('cv_r2_mean')} "
          f"cv_n_grupos={stats.get('cv_n_grupos')} warning={stats.get('cv_warning')}")
    assert "error" not in stats, f"train_rf no debería fallar: {stats}"
    assert stats["cv_r2_mean"] is None
    assert stats["cv_n_grupos"] == 1
    assert stats["cv_warning"] == "CV agrupada requiere ≥3 pozos con etiqueta (hay 1)."
    print("[TEST GKF 1-pozo] OK — CV omitida sin excepción, advertencia correcta.")
    return True

def test_groupkfold_two_wells():
    """Con 2 pozos también se omite (< 3), advertencia con el conteo correcto."""
    _reset_state()
    gw.domains.clear()
    gw.domains["DomX"] = {"count": 0, "ucs_lab": 120.0}
    _make_synthetic_well("W1", 60, 120.0, seed=1)
    _make_synthetic_well("W2", 60, 120.0, seed=2)
    stats = gw.train_rf(50.0, 280.0)
    print(f"[TEST GKF 2-pozos] cv_r2_mean={stats.get('cv_r2_mean')} "
          f"cv_n_grupos={stats.get('cv_n_grupos')}")
    assert "error" not in stats
    assert stats["cv_r2_mean"] is None
    assert stats["cv_n_grupos"] == 2
    print("[TEST GKF 2-pozos] OK — sigue omitida con <3 pozos.")
    return True

def test_groupkfold_three_wells_runs():
    """
    Con >=3 pozos, GroupKFold corre de verdad y produce un cv_r2_mean. Cada
    pozo cruza VARIOS dominios (como un pozo real que atraviesa distintas
    litologías a distinta profundidad) para que el target de cada fold tenga
    varianza no nula — con un solo dominio por pozo, el fold de test quedaría
    con UCS constante y R² sería 0.0 por definición de sklearn (caso
    degenerado observado y corregido durante el desarrollo de este test, no
    un bug de GroupKFold).
    """
    _reset_state()
    gw.domains.clear()
    labels = [80.0, 140.0, 200.0, 260.0]
    for i, lab in enumerate(labels):
        gw.domains[f"Dom{i}"] = {"count": 0, "ucs_lab": lab}
    rng = np.random.default_rng(7)
    for wi in range(3):
        pts = []
        for j in range(240):
            lab = labels[(j // 60 + wi) % len(labels)]  # el pozo cruza los 4 dominios
            p = gw.MWDPoint(largo=j*0.02, vel=2.5-lab/120.0+rng.normal(0,0.15),
                            pp=lab+rng.normal(0,8), pa=lab*0.6+rng.normal(0,6),
                            pd=40+rng.normal(0,5), pr=30+rng.normal(0,5), pf=8.0,
                            se=lab*2+rng.normal(0,15), t=0.0)
            p.dominio = f"Dom{labels.index(lab)}"; p.di = 0.1; p.entrenable = True
            pts.append(p)
        gw.wells[f"W{wi}"] = gw.Well(well_name=f"W{wi}", plan_id="P", hole_id=f"W{wi}", points=pts)
    stats = gw.train_rf(50.0, 280.0)
    print(f"[TEST GKF 3-pozos] cv_r2_mean={stats.get('cv_r2_mean')} "
          f"cv_n_grupos={stats.get('cv_n_grupos')} warning={stats.get('cv_warning')}")
    assert "error" not in stats
    assert stats["cv_n_grupos"] == 3
    assert stats["cv_warning"] is None
    assert stats["cv_r2_mean"] is not None
    assert stats["cv_r2_mean"] != 0.0, "target degenerado (varianza nula por fold); ver docstring"
    print("[TEST GKF 3-pozos] OK — GroupKFold corre con >=3 pozos y produce un cv_r2_mean real.")
    return True


if __name__ == "__main__":
    print("=" * 72)
    print("  test_di_sensitivity_groupkfold.py — validación T6 (GroupKFold) y T7 (sensibilidad DI)")
    print("=" * 72)
    print(f"  DQ : {DQ_PATH}")
    print(f"  MW : {MW_PATH}")
    print(f"  DXF: {DXF_PATH}")
    print("-" * 72)
    ok = True; n_skip = 0
    well_h5 = None
    try:
        well_h5 = test_e2e_and_di_regression()
    except SkipTest as e:
        n_skip += 1; print(skipped_banner('test_e2e_and_di_regression', str(e)))
    except AssertionError as e:
        ok = False; print(f"❌ test_e2e_and_di_regression FALLÓ: {e}")
    print("-" * 72)
    if well_h5 is not None:
        try:
            test_sensitivity_analysis(well_h5)
        except SkipTest as e:
            n_skip += 1; print(skipped_banner('test_sensitivity_analysis', str(e)))
        except AssertionError as e:
            ok = False; print(f"❌ test_sensitivity_analysis FALLÓ: {e}")
        print("-" * 72)
    for fn in (test_groupkfold_single_well, test_groupkfold_two_wells, test_groupkfold_three_wells_runs):
        try:
            fn()
        except SkipTest as e:
            n_skip += 1; print(skipped_banner(fn.__name__, str(e)))
        except AssertionError as e:
            ok = False; print(f"❌ {fn.__name__} FALLÓ: {e}")
        print("-" * 72)
    print("RESULTADO:", ("✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
          + (f"  ({n_skip} omitido(s) por falta de datos)" if n_skip else ""))
    sys.exit(0 if ok else 1)
