"""
test_validation.py — Validación de T4 (módulo de validación multipozo de
posición de mallas DXF) para geomech_wizard.

Cubre:
  · E2E real (obligatorio): DXF Metandesitas + DQ P40 + MW P41H5 →
    clasificación EXACTA 1437/1743, DI en 1743 pts, import sin servidor.
  · Test sintético (T4f, obligatorio): malla plana (slab rectangular cerrado,
    12 triángulos) que cruza el pozo H5 real a L0 conocido; 2 pozos sintéticos
    paralelos al H5 desplazados en Este; picos DI artificiales en los 3 pozos a
    L0 + 2.0 m. El módulo debe reportar offset medio ≈ +2.0 m (±0.3 m) y
    veredicto de desplazamiento.
  · Caso "consistente": mismos pozos con picos EN la malla (offset ~0) →
    veredicto "consistente".
  · di_peaks: fusión de picos separados <0.5 m y exclusión del emboquillado
    (decoy con entrenable=False debe ignorarse).

Nota geométrica del slab: se usa un prisma rectangular CERRADO y delgado
(0.2 m) en vez de un rectángulo abierto porque points_in_mesh clasifica
dentro/fuera por paridad de intersecciones con rayo vertical: un sólido
cerrado da paridad limpia (entrada y salida bien definidas), mientras que una
lámina abierta produce estados dependientes del bbox. Cada pico se aparea con
los DOS cruces del slab (entrada L0−δ y salida L0+δ, δ≈0.11 m), de modo que la
media de offsets recupera exactamente +2.0.
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

# El e2e usa SOLO el DQ P40 (colocación por fallback_hole), que es la
# configuración con la que se validó el 1437/1743 histórico.
DQ_PATH  = _find("GEOMECH_DQ",  ["DQMGN_3025_PR01_TH_P40_*.xml", "*DQ*P40*.xml"])
MW_PATH  = _find("GEOMECH_MW",  ["MWMGN_3025_PR01_TH_P41H5_*.xml", "*MW*P41H5*.xml"])
DXF_PATH = _find("GEOMECH_DXF", ["*Metandesitas*.dxf"])


def _reset_state():
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    gw.parse_warnings.clear(); gw.global_center = None
    gw.mesh_validation_results.clear()


def _load_real_h5():
    """Carga DXF + DQ P40 + MW H5 con la vía normal de matching."""
    tris, _ = gw.parse_dxf(DXF_PATH, os.path.basename(DXF_PATH))
    bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
    gw.layers["Metandesitas"] = gw.Layer(name="Metandesitas", kind="litologia",
                                         triangles=tris, bbox_min=bmin, bbox_max=bmax)
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))
    key = f"{mw['plan_id']}_H{mw['hole_id']}"
    gw.match_and_place_wells({dq["plan_id"]: dq}, {key: [mw]})
    return gw.wells[key]


def _make_slab_layer(center, half_xy=50.0, half_z=0.1, name="Estructura_Sintetica"):
    """Prisma rectangular cerrado (12 triángulos) centrado en `center` (E,N,Z)."""
    x0, x1 = center[0]-half_xy, center[0]+half_xy
    y0, y1 = center[1]-half_xy, center[1]+half_xy
    z0, z1 = center[2]-half_z,  center[2]+half_z
    v = np.array([[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
                  [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]])
    quads = [(0,1,2,3),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
    tris = []
    for a,b,c,d in quads:
        tris.append([v[a],v[b],v[c]]); tris.append([v[a],v[c],v[d]])
    tris = np.array(tris, dtype=np.float64)
    layer = gw.Layer(name=name, kind="estructura", triangles=tris,
                     bbox_min=tris.reshape(-1,3).min(0), bbox_max=tris.reshape(-1,3).max(0))
    gw.layers[name] = layer
    return layer


def _clone_well_shifted(well, name, d_este):
    """Pozo sintético paralelo: mismos largos/muestras, desplazado en Este."""
    pts = []
    for p in well.points:
        q = gw.MWDPoint(largo=p.largo, vel=p.vel, pp=p.pp, pa=p.pa, pd=p.pd,
                        pr=p.pr, pf=p.pf, se=p.se, t=p.t,
                        este=p.este + d_este, norte=p.norte, cota=p.cota)
        pts.append(q)
    collar = dict(well.collar); collar["este"] += d_este
    final  = dict(well.final_pt); final["este"] += d_este
    w = gw.Well(well_name=name, plan_id=well.plan_id, hole_id=well.hole_id,
                points=pts, collar=collar, final_pt=final, origin="matched")
    gw.wells[name] = w
    return w


def _inject_di(well, l_peak):
    """
    DI sintético controlado: base 0.1 (< umbral) en todo el pozo; decoy alto en
    el emboquillado (largo≈1.0, quedará entrenable=False → debe ignorarse);
    pico principal en l_peak (di=6) y satélite en l_peak+0.3 (di=5) para probar
    la fusión <0.5 m.
    """
    for p in well.points: p.di = 0.1
    min(well.points, key=lambda p: abs(p.largo - 1.0)).di = 8.0          # decoy
    min(well.points, key=lambda p: abs(p.largo - l_peak)).di = 6.0        # pico
    min(well.points, key=lambda p: abs(p.largo - (l_peak+0.3))).di = 5.0  # satélite


# ─── TEST 1: e2e real (clasificación exacta + DI) ─────────────────────────────
def test_e2e_real():
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
    # Smoke: los cruces del pozo real con la malla real se detectan sin error
    crossings = gw.well_mesh_crossings(well, gw.layers["Metandesitas"])
    print(f"[TEST e2e] Cruces H5↔Metandesitas: {len(crossings)} "
          f"(primero en largo={crossings[0][0]:.2f} m)" if crossings else "sin cruces")
    assert len(crossings) >= 1, "H5 cruza Metandesitas (1437 dentro) → debe haber cruces."
    print("[TEST e2e] OK — 1437/1743, DI 1743, cruces detectados.")
    return well


# (A.8) Fixture para pytest: los tests sintéticos parten del pozo real. Si el
# fixture del canario no está, test_e2e_real omite y estos se omiten con él,
# en vez de aparecer como error de fixture no resuelto.
@fixture(name="well_h5")
def _well_h5_fixture():
    return test_e2e_real()


# ─── TEST 2 (T4f): malla desplazada — offset ≈ +2.0 m ────────────────────────
def test_synthetic_displacement(well_h5):
    L0 = 18.0
    OFFSET_REAL = 2.0

    # Punto del H5 a largo L0 → el slab se centra DESPLAZADO en XY respecto del
    # pozo: si el pozo pasara por el centro del rectángulo, el rayo vertical de
    # points_in_mesh caería sobre la ARISTA DIAGONAL compartida de los dos
    # triángulos de cada cara (doble conteo → parpadeo de paridad → cruces
    # falsos). Con el centro corrido, la diagonal queda a >10 m de los 3 pozos.
    p0 = min(well_h5.points, key=lambda p: abs(p.largo - L0))
    slab = _make_slab_layer((p0.este + 13.7, p0.norte - 9.3, p0.cota))

    # 2 pozos sintéticos paralelos desplazados en Este (dentro del footprint)
    w_a = _clone_well_shifted(well_h5, "SYNTH_E+8", +8.0)
    w_b = _clone_well_shifted(well_h5, "SYNTH_E-8", -8.0)

    # Emboquillado con el corte EXISTENTE (reutilizado, según decisión de diseño)
    gw.apply_inicio_filter(2.0)

    # Picos DI inyectados a L0 + 2.0 en los 3 pozos
    for w in (well_h5, w_a, w_b):
        _inject_di(w, L0 + OFFSET_REAL)

    # (b) di_peaks: 1 solo evento por pozo (fusión del satélite, decoy excluido)
    for w in (well_h5, w_a, w_b):
        pks = gw.di_peaks(w)
        assert len(pks) == 1, f"{w.well_name}: se esperaba 1 pico, hay {len(pks)}."
        assert abs(pks[0][0] - (L0 + OFFSET_REAL)) < 0.05, \
            f"{w.well_name}: pico en {pks[0][0]:.2f}, esperado ≈{L0+OFFSET_REAL}."
    print(f"[TEST T4f] di_peaks: 1 evento/pozo en ≈{L0+OFFSET_REAL} m "
          f"(decoy emboquillado ignorado, satélite fusionado) ✓")

    # (a) cruces del H5 con el slab: entrada y salida en ≈ L0 ∓ 0.11
    crs = gw.well_mesh_crossings(well_h5, slab)
    print(f"[TEST T4f] Cruces H5↔slab: {[(round(l,3)) for l,_ in crs]}")
    assert len(crs) == 2, f"Se esperaban 2 cruces (slab cerrado), hay {len(crs)}."
    assert all(abs(l - L0) < 0.5 for l, _ in crs)
    # coordenada interpolada del cruce ≈ posición del pozo a ese largo
    lc, cc = crs[0]
    pn = min(well_h5.points, key=lambda p: abs(p.largo - lc))
    assert np.linalg.norm(cc - np.array([pn.este, pn.norte, pn.cota])) < 0.1

    # (d)+(e) módulo completo, con callback de progreso
    calls = []
    res = gw.validate_mesh_positions(progress_cb=lambda f, m: calls.append(f))
    assert calls and calls[-1] <= 1.0, "el callback de progreso no se invocó"
    r = next(x for x in res if x["malla"] == "Estructura_Sintetica")
    print(f"[TEST T4f] pozos cruzan={r['n_pozos_cruzan']} apareados={r['n_pozos_apareados']} "
          f"pares={r['n_pares']} offset={r['offset_medio']}±{r['offset_std']} m → {r['veredicto']}")
    assert r["n_pozos_apareados"] == 3
    assert r["n_pares"] == 6      # 2 cruces (entrada+salida) × 3 pozos
    assert abs(r["offset_medio"] - OFFSET_REAL) <= 0.3, \
        f"offset medio {r['offset_medio']} fuera de {OFFSET_REAL}±0.3."
    assert r["veredicto"].startswith("posible desplazamiento"), r["veredicto"]
    assert "+2.0" in r["veredicto"]
    print(f"[TEST T4f] OK — offset medio {r['offset_medio']:+.2f} m ≈ +2.0, "
          f"veredicto de desplazamiento ✓")

    # export CSV con detalle por pozo
    gw.mesh_validation_results.clear(); gw.mesh_validation_results.extend(res)
    df = gw.export_validation_csv()
    assert len(df) == 6 and set(df["pozo"]).issuperset({"SYNTH_E+8", "SYNTH_E-8"})
    print(f"[TEST T4f] export CSV: {len(df)} filas, columnas={list(df.columns)[:5]}…")
    return res


# ─── TEST 3: caso consistente — picos EN la malla → offset ≈ 0 ────────────────
def test_synthetic_consistent(well_h5):
    L0 = 18.0
    for w in gw.wells.values():
        _inject_di(w, L0)   # picos exactamente en la malla
    res = gw.validate_mesh_positions()
    r = next(x for x in res if x["malla"] == "Estructura_Sintetica")
    print(f"[TEST consist] offset={r['offset_medio']}±{r['offset_std']} m → {r['veredicto']}")
    assert abs(r["offset_medio"]) < 0.3
    assert r["veredicto"] == "consistente", r["veredicto"]
    print("[TEST consist] OK — picos en la malla → veredicto 'consistente' ✓")
    return True


if __name__ == "__main__":
    print("=" * 72)
    print("  test_validation.py — validación T4 (consistencia multipozo de mallas)")
    print("=" * 72)
    print(f"  DQ : {DQ_PATH}")
    print(f"  MW : {MW_PATH}")
    print(f"  DXF: {DXF_PATH}")
    print("-" * 72)
    ok = True; n_skip = 0
    well_h5 = None
    try:
        well_h5 = test_e2e_real()
    except SkipTest as e:
        n_skip += 1; print(skipped_banner('test_e2e_real', str(e)))
    except AssertionError as e:
        ok = False; print(f"❌ test_e2e_real FALLÓ: {e}")
    print("-" * 72)
    if well_h5 is not None:
        try:
            test_synthetic_displacement(well_h5)
        except SkipTest as e:
            n_skip += 1; print(skipped_banner('test_synthetic_displacement', str(e)))
        except AssertionError as e:
            ok = False; print(f"❌ test_synthetic_displacement FALLÓ: {e}")
        print("-" * 72)
        try:
            test_synthetic_consistent(well_h5)
        except SkipTest as e:
            n_skip += 1; print(skipped_banner('test_synthetic_consistent', str(e)))
        except AssertionError as e:
            ok = False; print(f"❌ test_synthetic_consistent FALLÓ: {e}")
        print("-" * 72)
    print("RESULTADO:", ("✅ TODOS LOS TESTS PASARON" if ok else "❌ HAY TESTS FALLIDOS")
          + (f"  ({n_skip} omitido(s) por falta de datos)" if n_skip else ""))
    sys.exit(0 if ok else 1)
