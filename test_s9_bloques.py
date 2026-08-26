"""
test_s9_bloques.py — Sesión 9: modelo de bloques por IDW anisotrópico.

Es el entregable central del alcance que fijó el autor: una malla de puntos
con UCS aproximadamente cierto y un valor de discontinuidad/fracturamiento
por sector. Todo lo demás del pipeline existe para llegar acá.

Tres exigencias que el test vigila una por una:

  · MÁSCARA DE SOPORTE. Un bloque sin dato cercano queda VACÍO. Nunca
    interpolado desde lejos: un modelo que rellena todo es un modelo que
    miente en los bordes, y ahí es justo donde se planifica la tronadura.

  · ANISOTROPÍA. El yacimiento es estratiforme: la litología continúa
    lateralmente y cambia con la cota. La búsqueda tiene que ser más larga en
    horizontal que en vertical, o el modelo mezcla estratos distintos. Es la
    misma razón por la que la cota está prohibida como predictora.

  · CONFIANZA CON CALIDAD DE ETIQUETA. Un dominio anclado en un ensayo de
    laboratorio del sitio y otro anclado en literatura NO pueden salir con la
    misma confianza. Se reutiliza pi_factor() del registro de atributos, que
    ya codifica esa jerarquía.

Terminología obligatoria en toda salida: "modelo geológico informado por MWD".
Nunca "corregido" ni "exacto".
"""

import os, sys, tempfile

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


def reset():
    gw.seed_attribute_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear(); gw.set_training_caserones(None)


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _pozo(wn, este, norte, cota_top, n=40, paso=0.5, ucs=120.0, di=0.4,
          lito="Bht", caseron="CAS_A"):
    """
    Pozo vertical sintético con UCS ya predicho por el modelo. La sesión 9
    interpola lo que el pipeline dejó en los puntos; no vuelve a predecir.
    """
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * paso, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este = este; p.norte = norte; p.cota = cota_top - i * paso
        p.ucs_ml = float(ucs); p.ucs_matriz = float(ucs)
        p.di = float(di); p.entrenable = True
        p.dominio = lito; p.lito = lito
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = caseron
    gw.wells[wn] = w
    return w


# ─────────────────────────────────────────────────────────────────────────────
def bloque_de_dos_metros_y_medio():
    section("9 — Bloque de 2,5 m, coherente con el burden y el espaciamiento")
    reset()
    _pozo("W1", E0, N0, Z0, n=40)
    rep = gw.interpolate_block_model()
    check(rep["status"] == "ok", "el modelo se construye", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(rep["bloque_m"] == 2.5, "el tamaño por defecto es 2,5 m", rep.get("bloque_m"))
    check(len(rep["bloques"]) > 0, "y hay bloques con valor", len(rep["bloques"]))
    b = rep["bloques"][0]
    for k in ("x", "y", "z", "tamano_m", "ucs", "di", "confianza"):
        check(k in b, f"cada bloque trae {k}", list(b))
    check(gw.TERMINOLOGIA_C in rep.get("terminologia", ""),
          "la salida usa 'modelo geológico informado por MWD'", rep.get("terminologia"))


def mascara_de_soporte():
    section("9 — Máscara de soporte: sin dato cercano el bloque queda VACÍO")
    reset()
    # Dos pozos separados 60 m. Entre medio no hay ni un solo dato: ningún
    # bloque de esa franja puede recibir valor.
    _pozo("W_izq", E0, N0, Z0, n=40)
    _pozo("W_der", E0 + 60.0, N0, Z0, n=40)

    rep = gw.interpolate_block_model()
    check(rep["status"] == "ok", "corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(rep["n_vacios"] > 0,
          "hay bloques que quedan vacíos y se cuentan", rep.get("n_vacios"))
    check(rep.get("motivo_vacios"),
          "declarando por qué quedaron vacíos", rep.get("motivo_vacios"))

    # Ningún bloque con valor puede estar a más del radio de búsqueda de un dato.
    centro_e = E0 + 30.0
    lejanos = [b for b in rep["bloques"] if abs(b["x"] - centro_e) < 10.0]
    check(not lejanos,
          "y ningún bloque del vacío central recibió valor interpolado desde lejos",
          [(b["x"], b["ucs"]) for b in lejanos[:3]])
    check(all(b["dist_min_m"] <= gw.IDW_RADIO_H_M + 1e-6 for b in rep["bloques"]),
          "todo bloque con valor tiene un dato dentro del radio de búsqueda",
          max((b["dist_min_m"] for b in rep["bloques"]), default=None))


def anisotropia_horizontal():
    section("9 — Anisotropía: el yacimiento es estratiforme, la cota separa")
    reset()
    # Dato LATERAL a 5 m en el plano, UCS 100. Dato VERTICAL a 5 m en cota,
    # UCS 300. Con anisotropía el lateral pesa más: el bloque tiene que salir
    # mucho más cerca de 100 que de 300.
    _pozo("W_lat", E0 + 5.0, N0, Z0, n=1, ucs=100.0)
    _pozo("W_vert", E0, N0, Z0 - 5.0, n=1, ucs=300.0)
    _pozo("W_centro", E0, N0, Z0, n=1, ucs=200.0)   # ancla el bloque objetivo

    rep = gw.interpolate_block_model(min_muestras=1)
    check(rep["status"] == "ok", "corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    # Bloque que contiene el origen.
    cand = [b for b in rep["bloques"]
            if abs(b["x"] - E0) <= 2.5 and abs(b["y"] - N0) <= 2.5 and abs(b["z"] - Z0) <= 2.5]
    check(cand, "existe el bloque del origen", len(rep["bloques"]))
    if not cand:
        return
    b = min(cand, key=lambda b: abs(b["z"] - Z0))
    check(b["ucs"] < 200.0,
          "el dato lateral (100 MPa) pesa más que el vertical (300 MPa)", b["ucs"])
    check(rep["anisotropia"][2] > rep["anisotropia"][0],
          "la anisotropía penaliza la separación vertical", rep.get("anisotropia"))
    check(gw.IDW_RADIO_V_M < gw.IDW_RADIO_H_M,
          "y el radio vertical es menor que el horizontal",
          (gw.IDW_RADIO_V_M, gw.IDW_RADIO_H_M))


def confianza_incorpora_calidad_de_etiqueta():
    section("9 — Confianza: ensayo del sitio y literatura NO pesan igual")
    reset()
    # Dos litologías con geometría idéntica: lo único que cambia es de dónde
    # viene su ancla de UCS.
    gw.create_attribute(attr_id="Sitio", nombre_oficial="Anclada en ensayo del sitio",
                        rol="litologia", ucs_min=100.0, ucs_max=140.0,
                        ucs_central=120.0, calidad=1, fuente="ensayo del sitio")
    gw.create_attribute(attr_id="Literat", nombre_oficial="Anclada en literatura",
                        rol="litologia", ucs_min=100.0, ucs_max=140.0,
                        ucs_central=120.0, calidad=4, fuente="literatura")
    _pozo("W_sitio", E0, N0, Z0, n=20, ucs=120.0, lito="Sitio")
    _pozo("W_lit", E0 + 40.0, N0, Z0, n=20, ucs=120.0, lito="Literat")

    rep = gw.interpolate_block_model()
    check(rep["status"] == "ok", "corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    c_sitio = [b["confianza"] for b in rep["bloques"] if b["lito"] == "Sitio"]
    c_lit = [b["confianza"] for b in rep["bloques"] if b["lito"] == "Literat"]
    check(c_sitio and c_lit, "hay bloques de las dos litologías",
          (len(c_sitio), len(c_lit)))
    if c_sitio and c_lit:
        check(np.median(c_sitio) > np.median(c_lit),
              "el dominio anclado en ensayo del sitio sale con MÁS confianza",
              (float(np.median(c_sitio)), float(np.median(c_lit))))
    check("calidad" in (rep.get("definicion_confianza") or "").lower(),
          "y la definición de confianza declara que incorpora la calidad de la etiqueta",
          rep.get("definicion_confianza"))
    check(all(0.0 <= b["confianza"] <= 1.0 for b in rep["bloques"]),
          "la confianza está acotada a [0, 1]")


def ucs_dentro_de_limites_fisicos():
    section("9 — UCS: 0 a 450 MPa, sin truncamiento silencioso")
    reset()
    _pozo("W1", E0, N0, Z0, n=20, ucs=200.0)
    rep = gw.interpolate_block_model()
    check(all(0.0 <= b["ucs"] <= 450.0 for b in rep["bloques"]),
          "todo UCS del modelo cae dentro de los límites físicos")
    check(rep.get("limites_ucs") == [0.0, 450.0],
          "que el reporte declara explícitamente", rep.get("limites_ucs"))


def exportacion_dual():
    section("9 — Exportación dual: CSV y DXF con capas por banda")
    reset()
    _pozo("W1", E0, N0, Z0, n=30, ucs=120.0)
    _pozo("W2", E0 + 5.0, N0, Z0, n=30, ucs=260.0, lito="Bht")
    rep = gw.interpolate_block_model()
    check(rep["status"] == "ok", "el modelo corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return

    csv = gw.export_block_model_csv(rep)
    cab = [l for l in csv.splitlines() if l.startswith("#")]
    check(any(gw.TERMINOLOGIA_C in l for l in cab),
          "el CSV declara 'modelo geológico informado por MWD'", cab[:2])
    head = [l for l in csv.splitlines() if not l.startswith("#")][0]
    for col in ("x", "y", "z", "tamano_m", "ucs", "di", "confianza"):
        check(col in head, f"el CSV trae la columna {col}", head)

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "bloques.dxf")
        out = gw.export_block_model_dxf(rep, path)
        check(os.path.exists(out), "el DXF se escribe", out)
        import ezdxf
        doc = ezdxf.readfile(out)
        capas = [l.dxf.name for l in doc.layers]
        bandas = [c for c in capas if c.startswith(gw.BLOQUE_LAYER_PREFIX)]
        check(len(bandas) >= 2,
              "y trae una capa por banda de resistencia, no una sola", capas)
        msp = doc.modelspace()
        check(len(msp) > 0, "con geometría dentro", len(msp))


def bandas_son_trazables():
    section("9 — Las bandas de resistencia son ISRM, no percentiles")
    check(len(gw.BANDAS_RESISTENCIA) >= 4, "hay varias bandas",
          len(gw.BANDAS_RESISTENCIA))
    check("isrm" in gw.BANDAS_RESISTENCIA_FUENTE.lower(),
          "y su fuente es la clasificación ISRM, criterio trazable",
          gw.BANDAS_RESISTENCIA_FUENTE)
    # Cubren el rango físico completo sin huecos.
    lim = [b[0] for b in gw.BANDAS_RESISTENCIA] + [gw.BANDAS_RESISTENCIA[-1][1]]
    check(lim[0] == 0.0 and lim[-1] >= 450.0,
          "y cubren de 0 a 450 MPa sin dejar UCS fuera de banda", (lim[0], lim[-1]))
    check(gw.banda_resistencia(120.0) is not None, "un UCS típico cae en una banda")
    check(gw.banda_resistencia(-1.0) is None,
          "y un UCS fuera de los límites físicos no recibe banda inventada")


def sin_datos_no_hay_modelo():
    section("9 — Sin puntos con UCS: se declara, no se entrega un modelo vacío disfrazado")
    reset()
    rep = gw.interpolate_block_model()
    check(rep["status"] == "sin_datos", "el estado lo dice", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    check(rep.get("bloques") == [], "y sin bloques", rep.get("bloques"))


def la_cota_no_es_predictora():
    section("9 — La cota entra como GEOMETRÍA de interpolación, nunca como predictora")
    reset()
    _pozo("W1", E0, N0, Z0, n=20)
    gw.interpolate_block_model()
    check(gw.ML_FEATURES == ["vel", "pp", "pa", "pd", "pr", "pf", "se"],
          "ML_FEATURES sigue sin coordenadas", gw.ML_FEATURES)
    check(not any(c in gw.ML_FEATURES for c in ("este", "norte", "cota", "x", "y", "z")),
          "ninguna coordenada se coló como predictora")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    bloque_de_dos_metros_y_medio,
    mascara_de_soporte,
    anisotropia_horizontal,
    confianza_incorpora_calidad_de_etiqueta,
    ucs_dentro_de_limites_fisicos,
    exportacion_dual,
    bandas_son_trazables,
    sin_datos_no_hay_modelo,
    la_cota_no_es_predictora,
]


def test_s9_bloques():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ SESIÓN 9 — todas las verificaciones pasaron.")
    print("=" * 72)
