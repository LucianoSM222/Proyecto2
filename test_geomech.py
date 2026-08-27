"""
test_geomech.py — Validación de T2 (etiquetado caserón×litología + predicción
con intervalo) y T3 (verificación de banda) para geomech_wizard.

Cubre:
  · parse_geomech_excel sobre un XLSX geomecánico: ≥40 registros, imprime 3
    ejemplos con sus bandas parseadas. Usa el archivo real si la variable de
    entorno GEOMECH_XLSX (o ./test_data/geomecanica_de_caserones.xlsx) existe;
    si no, genera un fixture sintético con el MISMO formato documentado
    (hoja BUDGET_S_2026_V02, encabezados en fila índice 2, datos desde la 3,
    columnas 2/3/23/24/25/26/27), incluyendo una fila Metandesitas UCS "100 - 267".
  · End-to-end con los archivos reales (DXF + DQ + MW): clasificación 1437/1743,
    DI 1743, banda de Metandesitas desde Excel (mid=183.5), entrenamiento y
    verificación p10 <= ucs_ml <= p90 en TODOS los puntos.
  · band_consistency() sobre un caso sintético construido a mano que produce
    las tres categorías: compatible / incompatible / ambiguo.

Rutas: GEOMECH_DQ / GEOMECH_MW / GEOMECH_DXF / GEOMECH_XLSX (env) o ./test_data
o la carpeta de subida de la sesión.
"""

import os, sys, glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import pandas as pd
import geomech_wizard as gw
from test_support import require_real_data, SkipTest, fixture, skipped_banner


def _find(env_var, patterns):
    p = os.environ.get(env_var)
    if p and os.path.exists(p):
        return p
    for d in (os.path.join(HERE, "test_data"), HERE,
              "/root/.claude/uploads/fb9dc967-91ef-5038-a9a9-9123585f5c0b"):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(d, pat)))
            if hits:
                return hits[0]
    return None

# (A.8) Patrones ESTRICTOS: sin el comodín de reserva, que hacía tomar
# cualquier DXF/XML presente y fallar con un mensaje confuso en vez de
# omitir el test por falta del fixture correcto.
DQ_PATH   = _find("GEOMECH_DQ",   ["DQMGN_3025_PR01_TH_P40_*.xml", "*DQ*P40*.xml"])
MW_PATH   = _find("GEOMECH_MW",   ["MWMGN_3025_PR01_TH_P41H5_*.xml", "*MW*P41H5*.xml"])
DXF_PATH  = _find("GEOMECH_DXF",  ["*Metandesitas*.dxf"])
# Solo el XLSX geomecánico REAL (no el fixture sintético, que tiene otro nombre).
XLSX_PATH = _find("GEOMECH_XLSX", ["geomecanica_de_caserones.xlsx", "*caserones*.xlsx"])
SYNTH_PATH = os.path.join(HERE, "test_data", "synthetic_bands.xlsx")


def _reset_state():
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    gw.parse_warnings.clear(); gw.global_center = None
    gw.rf_model = None


# ─── TEST 1: parse_geomech_excel ──────────────────────────────────────────────
def _norm(s):
    return gw._norm_txt(s)


# ─── TEST 2: end-to-end con archivos reales ───────────────────────────────────
# ─── TEST 3: band_consistency — tres categorías (caso sintético a mano) ───────
# ─── TEST 4: el intervalo p10/p90 se ENSANCHA con múltiples etiquetas UCS ─────
def test_interval_widens():
    """
    En el e2e con un solo dominio etiquetado (Metandesitas) todas las etiquetas
    son iguales (mid=183.5) y el intervalo colapsa a un punto — comportamiento
    correcto. Aquí se comprueba que, con VARIAS bandas UCS distintas, el
    percentil 10/90 vectorizado sí produce un intervalo de ancho > 0 y que
    p10 <= mediana <= p90.
    """
    _reset_state()
    # Varios dominios con UCS de laboratorio repartidos en 80..220 MPa y firmas
    # MWD correlacionadas con el UCS pero con RUIDO ALTO: así los árboles del RF
    # discrepan y el intervalo p10/p90 se ensancha de verdad (a diferencia del
    # e2e con un solo dominio, donde todas las etiquetas son iguales).
    gw.domains.clear()
    labels = np.linspace(80.0, 220.0, 14)
    for i, lab in enumerate(labels):
        gw.domains[f"D{i}"] = {"count": 0, "ucs_lab": float(lab)}
    pts = []
    rng = np.random.default_rng(0)
    for i, lab in enumerate(labels):
        for _ in range(12):
            p = gw.MWDPoint(largo=1.0,
                            vel=2.5 - lab/120.0 + rng.normal(0, 0.4),
                            pp=lab + rng.normal(0, 25),
                            pa=lab*0.6 + rng.normal(0, 20),
                            pd=40 + rng.normal(0, 10), pr=30 + rng.normal(0, 10), pf=8.0,
                            se=lab*2 + rng.normal(0, 60), t=0.0)
            p.dominio = f"D{i}"; p.di = 0.1
            pts.append(p)
    gw.wells["W"] = gw.Well(well_name="W", plan_id="P", hole_id="1", points=pts)
    stats = gw.train_rf(50.0, 280.0)
    assert "error" not in stats, f"train_rf falló: {stats}"
    gw.predict_all_wells()
    all_pts = list(gw.all_points())
    # Orden p10<=mediana<=p90 en todos
    for p in all_pts:
        assert p.ucs_ml_p10 <= p.ucs_ml <= p.ucs_ml_p90
    # Al menos un punto con intervalo de ancho > 0 (no degenerado)
    anchos = [p.ucs_ml_p90 - p.ucs_ml_p10 for p in all_pts]
    print(f"[TEST interval] ancho intervalo: min={min(anchos):.1f} "
          f"max={max(anchos):.1f} medio={np.mean(anchos):.1f} MPa")
    assert max(anchos) > 0, "El intervalo p10/p90 nunca se ensancha."
    print("[TEST interval] OK — intervalo vectorizado válido y no degenerado.")
    return True


if __name__ == "__main__":
    print("=" * 72)
    print("  test_geomech.py — validación T2 (bandas + intervalo) y T3 (consistencia)")
    print("=" * 72)
    print(f"  DQ  : {DQ_PATH}")
    print(f"  MW  : {MW_PATH}")
    print(f"  DXF : {DXF_PATH}")
    print(f"  XLSX: {XLSX_PATH or '(sintético)'}")
    print("-" * 72)
    ok = True; n_skip = 0
    for fn in (test_parse_geomech, test_end_to_end_bands,
               test_band_consistency_categories, test_interval_widens):
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
