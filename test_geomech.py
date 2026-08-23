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


def _make_synthetic_xlsx(path):
    """
    Genera un XLSX geomecánico sintético con el formato EXACTO documentado:
    hoja BUDGET_S_2026_V02, encabezados en la fila índice 2 (0-indexado),
    datos desde la fila 3, columnas por índice 2=Caserón, 3=Nivel,
    23=Litología, 24=UCS, 25=RMR, 26=RQD, 27=GSI. 36 columnas totales.
    Incluye la fila Metandesitas con UCS "100 - 267" (mid=183.5) y variedad de
    formatos de rango. También filas sin litología (deben saltarse).
    """
    n_cols = 36
    grid = [["" for _ in range(n_cols)] for _ in range(2)]  # 2 filas basura
    header = ["" for _ in range(n_cols)]
    header[2], header[3], header[23] = "Caseron", "Nivel", "Litologia"
    header[24], header[25], header[26], header[27] = "UCS(MPa)", "RMR", "RQD", "GSI"
    grid.append(header)

    litos = ["Albitofiro", "Brecha Hidrotermal", "Lavas Inferiores",
             "Metandesitas", "Andesita", "Toba"]
    ucs_fmts = ["150 - 230", "50 - 150", "267", "100 - 267", "120 - 180", "90 - 140"]
    caserones = ["PCC_1502", "PCC_1504", "PCC_1506", "PCC_1508",
                 "PCC_1510", "PCC_1512", "MGN_3025"]
    data_rows = []
    idx = 0
    for cas in caserones:
        for li, lito in enumerate(litos):
            row = ["" for _ in range(n_cols)]
            row[2] = cas
            row[3] = f"N{1500 + li}"
            row[23] = lito
            row[24] = ucs_fmts[li % len(ucs_fmts)]
            row[25] = "45 a 60"
            row[26] = "44 a 67"
            row[27] = str(55 + li)
            data_rows.append(row)
            idx += 1
    # Fila Metandesitas explícita con "100 - 267" en un caserón conocido
    row = ["" for _ in range(n_cols)]
    row[2] = "MGN_3025"; row[3] = "N3025"; row[23] = "Metandesitas"
    row[24] = "100 - 267"; row[25] = "50 a 65"; row[26] = "40 a 70"; row[27] = "60"
    data_rows.append(row)
    # Un par de filas SIN litología (deben saltarse)
    empty = ["" for _ in range(n_cols)]; empty[2] = "PCC_9999"; empty[3] = "N0"
    data_rows.append(empty)
    data_rows.append(["" for _ in range(n_cols)])

    grid.extend(data_rows)
    df = pd.DataFrame(grid)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="BUDGET_S_2026_V02", header=False, index=False)


def _reset_state():
    gw.wells.clear(); gw.layers.clear(); gw.domains.clear()
    gw.parse_warnings.clear(); gw.global_center = None
    gw.rf_model = None


# ─── TEST 1: parse_geomech_excel ──────────────────────────────────────────────
def test_parse_geomech():
    path = XLSX_PATH
    synthetic = False
    if not (path and os.path.exists(path)):
        path = SYNTH_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _make_synthetic_xlsx(path)
        synthetic = True

    records = gw.parse_geomech_excel(path)
    src = "SINTÉTICO" if synthetic else "REAL"
    print(f"[TEST parse] Fuente {src}: {len(records)} registros parseados.")
    assert len(records) >= 40, f"Se esperaban ≥40 registros, hay {len(records)}."

    print("[TEST parse] 3 ejemplos:")
    for rec in records[:3]:
        print(f"   · {rec['caseron']} / {rec['litologia']}: "
              f"UCS [{rec['ucs_lo']}, {rec['ucs_mid']}, {rec['ucs_hi']}]  "
              f"RMR={rec['rmr_raw']}  RQD [{rec['rqd_lo']},{rec['rqd_mid']},{rec['rqd_hi']}]  "
              f"GSI={rec['gsi_raw']}")

    # Verificar el parseo de una banda con rango y una con valor único
    for rec in records:
        assert rec["ucs_lo"] is None or rec["ucs_lo"] <= rec["ucs_hi"]
    # Debe existir la fila Metandesitas "100 - 267" → mid 183.5 (en el Excel
    # real es el caserón MGN_3032; en el fixture sintético, MGN_3025).
    gw.index_geomech_bands(records)
    meta_183 = [r for r in records
                if _norm(r["litologia"]).startswith("metandesita")
                and r["ucs_mid"] is not None and abs(r["ucs_mid"] - 183.5) < 1e-6]
    if any(_norm(r["litologia"]).startswith("metandesita") for r in records):
        assert meta_183, "No se encontró la fila Metandesitas '100-267' (mid=183.5)."
        print(f"[TEST parse] Metandesitas '100-267' en caserón(es): "
              f"{[r['caseron'] for r in meta_183]} → mid=183.5 ✓")
    return records


def _norm(s):
    return gw._norm_txt(s)


# ─── TEST 2: end-to-end con archivos reales ───────────────────────────────────
def test_end_to_end_bands():
    require_real_data(DXF=DXF_PATH, DQ=DQ_PATH, MW=MW_PATH)
    _reset_state()

    # Cargar bandas (reales o sintéticas) para tener la banda de Metandesitas
    if XLSX_PATH and os.path.exists(XLSX_PATH):
        records = gw.parse_geomech_excel(XLSX_PATH)
    else:
        if not os.path.exists(SYNTH_PATH):
            os.makedirs(os.path.dirname(SYNTH_PATH), exist_ok=True)
            _make_synthetic_xlsx(SYNTH_PATH)
        records = gw.parse_geomech_excel(SYNTH_PATH)
    gw.index_geomech_bands(records)

    # DXF Metandesitas
    tris, _ = gw.parse_dxf(DXF_PATH, os.path.basename(DXF_PATH))
    bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
    layer = gw.Layer(name="Metandesitas", kind="litologia", triangles=tris,
                     bbox_min=bmin, bbox_max=bmax)
    gw.layers["Metandesitas"] = layer
    # Asignar el caserón cuya banda Metandesitas es "100 - 267" (mid=183.5). En
    # el Excel real es MGN_3032; en el fixture sintético, MGN_3025. Se busca
    # dinámicamente para no depender del archivo.
    caseron_183 = None
    for rec in records:
        if gw._norm_txt(rec["litologia"]).startswith("metandesita") \
           and rec["ucs_mid"] is not None and abs(rec["ucs_mid"] - 183.5) < 1e-6:
            caseron_183 = rec["caseron"]; break
    assert caseron_183, "No se encontró la fila Metandesitas '100-267' (mid=183.5)."
    layer.caseron = caseron_183
    ok = gw.apply_layer_band(layer)
    print(f"[TEST e2e] Caserón con banda 100-267: {caseron_183}")
    print(f"[TEST e2e] Banda Metandesitas autocompletada: {ok} → "
          f"[{layer.ucs_lo}, {layer.ucs_mid}, {layer.ucs_hi}], ucs_lab={layer.ucs_lab}")
    assert ok and abs(layer.ucs_mid - 183.5) < 1e-6, "La banda de Metandesitas debe dar mid=183.5."

    # XML reales
    dq = gw.parse_dq(DQ_PATH, os.path.basename(DQ_PATH))
    mw = gw.parse_mw(MW_PATH, os.path.basename(MW_PATH))
    dq_results = {dq["plan_id"]: dq}
    key = f"{mw['plan_id']}_H{mw['hole_id'] or 'X'}"
    gw.match_and_place_wells(dq_results, {key: [mw]})
    well = gw.wells[key]
    assert len(well.points) == 1743

    # Clasificación 1437/1743
    gw.classify_all_wells()
    n_inside = sum(1 for p in well.points if p.lito == "Metandesitas")
    print(f"[TEST e2e] Clasificación dentro de Metandesitas: {n_inside}/1743")
    assert n_inside == 1437, f"Esperado 1437, obtenido {n_inside}."

    # DI 1743
    gw.compute_di()
    n_di = sum(1 for p in well.points if p.di is not None)
    assert n_di == 1743, f"DI esperado 1743, obtenido {n_di}."

    # Entrenar con la banda (domains ucs_lab = ucs_mid) y predecir intervalo
    gw.build_domain_index()
    dom = gw.domains.get("Metandesitas", {})
    print(f"[TEST e2e] domains['Metandesitas'].ucs_lab = {dom.get('ucs_lab')} (debe = ucs_mid 183.5)")
    assert dom.get("ucs_lab") is not None and abs(dom["ucs_lab"] - 183.5) < 0.6
    stats = gw.train_rf(50.0, 280.0)
    assert "error" not in stats, f"train_rf falló: {stats}"
    gw.predict_all_wells()

    # p10 <= ucs_ml <= p90 en TODOS los puntos
    viol = [p for p in well.points
            if not (p.ucs_ml_p10 is not None and p.ucs_ml_p90 is not None
                    and p.ucs_ml_p10 <= p.ucs_ml <= p.ucs_ml_p90)]
    print(f"[TEST e2e] Puntos con intervalo válido: {1743 - len(viol)}/1743")
    assert not viol, f"{len(viol)} puntos violan p10<=ucs_ml<=p90."

    # band_consistency corre sin excepciones sobre datos reales
    gw.band_consistency()
    cats = {}
    for p in well.points:
        cats[p.band_check] = cats.get(p.band_check, 0) + 1
    print(f"[TEST e2e] band_consistency sobre H5: {cats}")

    # Ejemplo de hover/CSV con intervalo
    ej = next((p for p in well.points if p.ucs_ml is not None), None)
    if ej:
        print(f"[TEST e2e] Ejemplo intervalo: 'UCS ML: {gw._fmt_ucs_interval(ej)}'")
    print("[TEST e2e] OK — 1437/1743, DI 1743, banda=183.5, intervalo válido en todos.")
    return True


# ─── TEST 3: band_consistency — tres categorías (caso sintético a mano) ───────
def test_band_consistency_categories():
    _reset_state()
    # Bandas: RocaA [100,150], RocaB [140,200] en el mismo caserón PCC_TEST
    records = [
        {"caseron":"PCC_TEST","litologia":"RocaA","ucs_lo":100.0,"ucs_mid":125.0,"ucs_hi":150.0,
         "rmr_raw":"45 a 60","rqd_lo":40.0,"rqd_mid":55.0,"rqd_hi":70.0,"gsi_raw":"55"},
        {"caseron":"PCC_TEST","litologia":"RocaB","ucs_lo":140.0,"ucs_mid":170.0,"ucs_hi":200.0,
         "rmr_raw":"50 a 65","rqd_lo":45.0,"rqd_mid":60.0,"rqd_hi":75.0,"gsi_raw":"60"},
    ]
    gw.index_geomech_bands(records)

    # Capas DXF que representan cada litología, ambas del caserón PCC_TEST
    dummy = np.zeros((1, 3, 3))
    for ln in ("RocaA", "RocaB"):
        lay = gw.Layer(name=ln, kind="litologia", triangles=dummy,
                       bbox_min=np.zeros(3), bbox_max=np.ones(3))
        lay.caseron = "PCC_TEST"
        gw.layers[ln] = lay

    def mk(ucs, p10, p90, lito="RocaA"):
        p = gw.MWDPoint(largo=1.0, vel=1.0, pp=1.0, pa=1.0, pd=1.0, pr=1.0, pf=1.0, se=1.0, t=0.0)
        p.ucs_ml, p.ucs_ml_p10, p.ucs_ml_p90 = ucs, p10, p90
        p.lito = lito
        return p

    # p_comp: mediana 120 dentro de [100,150], solo RocaA la contiene → compatible
    # p_incomp: intervalo [170,190] no intersecta [100,150] → incompatible
    # p_amb: mediana 145 en [100,150] Y en [140,200] (2 litos) → ambiguo
    p_comp   = mk(120.0, 110.0, 130.0)
    p_incomp = mk(180.0, 170.0, 190.0)
    p_amb    = mk(145.0, 135.0, 155.0)
    well = gw.Well(well_name="W_TEST", plan_id="P", hole_id="1",
                   points=[p_comp, p_incomp, p_amb])
    gw.wells["W_TEST"] = well

    gw.band_consistency()
    print(f"[TEST bands] compatible={p_comp.band_check} "
          f"incompatible={p_incomp.band_check} ambiguo={p_amb.band_check}")
    assert p_comp.band_check == "compatible",   f"esperado compatible, {p_comp.band_check}"
    assert p_incomp.band_check == "incompatible", f"esperado incompatible, {p_incomp.band_check}"
    assert p_amb.band_check == "ambiguo",        f"esperado ambiguo, {p_amb.band_check}"
    print("[TEST bands] OK — tres categorías correctas.")
    return True


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
