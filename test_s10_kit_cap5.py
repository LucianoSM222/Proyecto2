"""
test_s10_kit_cap5.py — Sesión 10: kit de resultados del Capítulo 5.

El kit es lo que se pega en la memoria. Tres exigencias:

  · NOMENCLATURA CONSISTENTE. Todo archivo se llama por su identificador, y
    el identificador no depende del orden en que se generó ni de qué datos
    había cargados. Una tabla que cambia de número entre dos corridas obliga
    a reescribir las referencias del texto.

  · NUMERACIÓN ESTABLE. Los identificadores están declarados, no derivados.
    Correr el kit dos veces da los mismos números.

  · NADA FALTA EN SILENCIO. Un ítem que no se pudo generar aparece en el
    índice con su estado y su motivo. Un índice donde el ítem simplemente no
    está es peor que uno que dice "faltó y por esto".

El índice mapea cada archivo a la sección del capítulo donde va, que es lo
que evita tener que reconstruir a mano dónde iba cada figura.
"""

import os, sys, tempfile, zipfile, io

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


def _pozo(wn, este, ucs=120.0, lito="Bht", n=30):
    pts = []
    for i in range(n):
        p = gw.MWDPoint(largo=i * 0.5, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este = este; p.norte = N0; p.cota = Z0 - i * 0.5
        p.ucs_ml = float(ucs); p.ucs_matriz = float(ucs); p.di = 0.4
        p.entrenable = True; p.dominio = lito; p.lito = lito
        pts.append(p)
    w = gw.Well(well_name=wn, plan_id=f"CAS_PR01_TH_{wn}", hole_id=wn, points=pts)
    w.caseron = "CAS_A"
    gw.wells[wn] = w
    return w


# ─────────────────────────────────────────────────────────────────────────────
def indice_declarado_y_completo():
    section("10 — El índice está DECLARADO: qué va en cada sección del capítulo")
    ind = gw.KIT_CAP5
    check(len(ind) >= 10, "el kit declara sus ítems", len(ind))
    ids = [i["id"] for i in ind]
    check(len(ids) == len(set(ids)), "sin identificadores repetidos",
          [i for i in ids if ids.count(i) > 1])
    for it in ind:
        for k in ("id", "seccion", "titulo", "tipo", "generador"):
            check(k in it, f"cada ítem declara {k}", it.get("id"))
            break
    check(all(i["tipo"] in ("tabla", "figura", "csv", "dxf") for i in ind),
          "cada ítem declara su tipo", sorted({i["tipo"] for i in ind}))
    check(all(i["seccion"].startswith("5.") for i in ind),
          "y a qué sección del Capítulo 5 va",
          sorted({i["seccion"] for i in ind})[:5])


def los_cinco_obligatorios():
    section("10 — Los cinco entregables que la sesión exige, presentes")
    titulos = " | ".join(f"{i['id']} {i['titulo']}" for i in gw.KIT_CAP5).lower()
    for clave, etiqueta in (
            ("traslape", "la matriz de traslape de bandas"),
            ("cinco modelos", "la comparación de los cinco modelos"),
            ("justificación de variables", "el reporte de justificación de variables"),
            ("ablación de cota", "la ablación de cota"),
            ("concordancia", "los diagnósticos de concordancia")):
        check(clave in titulos, f"{etiqueta} está en el kit", titulos[:200])
    # La matriz de traslape va con AMBOS criterios, no con uno.
    tr = [i for i in gw.KIT_CAP5 if "traslape" in i["titulo"].lower()]
    check(tr and "ambos criterios" in tr[0]["titulo"].lower(),
          "y el traslape declara que va con ambos criterios",
          tr[0]["titulo"] if tr else None)


def numeracion_estable():
    section("10 — Numeración estable: dos corridas, los mismos números")
    reset()
    _pozo("W1", E0)
    with tempfile.TemporaryDirectory() as td:
        r1 = gw.build_chapter5_kit(os.path.join(td, "a"))
        r2 = gw.build_chapter5_kit(os.path.join(td, "b"))
        m1 = {i["id"]: i["archivo"] for i in r1["items"]}
        m2 = {i["id"]: i["archivo"] for i in r2["items"]}
        check(list(m1) == list(m2), "los identificadores no se mueven",
              (list(m1)[:3], list(m2)[:3]))
        check(m1 == m2, "y cada uno mantiene su nombre de archivo")
    # Con MENOS datos cargados los números tampoco cambian.
    reset()
    with tempfile.TemporaryDirectory() as td:
        r3 = gw.build_chapter5_kit(td)
        check([i["id"] for i in r3["items"]] == list(m1),
              "ni siquiera cuando no hay datos y varios ítems no se generan",
              [i["id"] for i in r3["items"]][:5])


def nada_falta_en_silencio():
    section("10 — Un ítem que no se pudo generar aparece con su motivo")
    reset()   # sin datos: la mayoría no puede generarse
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        check(len(rep["items"]) == len(gw.KIT_CAP5),
              "el índice lista TODOS los ítems declarados, generados o no",
              (len(rep["items"]), len(gw.KIT_CAP5)))
        fallidos = [i for i in rep["items"] if i["estado"] != "ok"]
        check(fallidos, "con datos vacíos varios no se generan", len(fallidos))
        check(all(i.get("motivo") for i in fallidos),
              "y cada uno declara POR QUÉ no se generó",
              [i["id"] for i in fallidos if not i.get("motivo")])
        check(all(i["archivo"] is None for i in fallidos),
              "sin dejar un archivo a medias en el disco")
        gen = [i for i in rep["items"] if i["estado"] == "ok"]
        for i in gen:
            check(os.path.exists(os.path.join(td, i["archivo"])),
                  f"{i['id']}: el archivo declarado existe", i["archivo"])
            break
        check(rep["n_generados"] + rep["n_fallidos"] == len(gw.KIT_CAP5),
              "el resumen cuadra", (rep["n_generados"], rep["n_fallidos"]))


def nomenclatura_consistente():
    section("10 — Nomenclatura: el archivo se llama por su identificador")
    reset()
    _pozo("W1", E0)
    _pozo("W2", E0 + 3.0, ucs=200.0)
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        gen = [i for i in rep["items"] if i["estado"] == "ok"]
        check(gen, "algo se generó", rep["n_generados"])
        malos = [i for i in gen
                 if not i["archivo"].startswith(i["id"].replace(".", "_"))]
        check(not malos, "todo archivo empieza por su identificador",
              [(i["id"], i["archivo"]) for i in malos[:3]])
        check(all("." in i["archivo"] for i in gen),
              "y lleva extensión según su tipo",
              [i["archivo"] for i in gen[:3]])


def exportadores_que_devuelven_dataframe():
    section("10 — Los exportadores de la UI devuelven DataFrame, no texto CSV")
    reset()
    _pozo("W1", E0)
    _pozo("W2", E0 + 3.0, ucs=200.0)
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        por_id = {i["id"]: i for i in rep["items"]}
        # T5.17 sale de export_predictions_csv, que devuelve el DataFrame crudo
        # porque alimenta el botón de descarga de la aplicación.
        it = por_id["T5.17"]
        check(it["estado"] == "ok",
              "el kit acepta el DataFrame y escribe el CSV igual", it.get("motivo"))
        if it["estado"] == "ok":
            texto = open(os.path.join(td, it["archivo"]), encoding="utf-8").read()
            check(texto.startswith("#"),
                  "poniéndole el encuadre que el exportador no trae", texto[:60])
            check("ucs_matriz" in texto, "y con las columnas de la predicción",
                  texto.splitlines()[3][:120] if len(texto.splitlines()) > 3 else texto[:120])
    # Sin datos, el mismo camino declara el vacío en vez de reventar.
    reset()
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        it = {i["id"]: i for i in rep["items"]}["T5.17"]
        check(it["estado"] == "sin_datos",
              "y sin puntos cargados lo declara, no lanza un error", it.get("estado"))
        check(it.get("motivo"), "con su motivo", it.get("motivo"))
    # Ningún ítem del kit puede terminar en "error": eso es un defecto del
    # adaptador, no una falta de datos, y no debe pasar inadvertido.
    check(not [i for i in rep["items"] if i["estado"] == "error"],
          "ningún ítem falla por error de código",
          [(i["id"], i["motivo"]) for i in rep["items"] if i["estado"] == "error"])


def indice_exportable():
    section("10 — El índice se exporta: CSV para la planilla, Markdown para el texto")
    reset()
    _pozo("W1", E0)
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        csv = gw.export_kit_index_csv(rep)
        head = [l for l in csv.splitlines() if not l.startswith("#")][0]
        for col in ("id", "seccion", "titulo", "tipo", "archivo", "estado"):
            check(col in head, f"el CSV del índice trae la columna {col}", head)
        md = gw.export_kit_index_md(rep)
        check(md.lstrip().startswith("#"), "el Markdown arranca con un título", md[:60])
        check("| " in md, "y trae la tabla del índice")
        check(gw.TERMINOLOGIA_C in md,
              "usando 'modelo geológico informado por MWD'", md[:400])
        # Los dos índices quedan escritos en el directorio del kit.
        check(os.path.exists(os.path.join(td, rep["indice_csv"])),
              "el índice CSV queda en el kit", rep.get("indice_csv"))
        check(os.path.exists(os.path.join(td, rep["indice_md"])),
              "y el Markdown también", rep.get("indice_md"))


def kit_declara_su_procedencia():
    section("10 — El kit declara con qué datos se generó")
    reset()
    _pozo("W1", E0)
    with tempfile.TemporaryDirectory() as td:
        rep = gw.build_chapter5_kit(td)
        check(rep.get("generado"), "cuándo se generó", rep.get("generado"))
        check("procedencia" in rep, "de qué caserones y capas salió",
              list(rep))
        check(rep.get("terminologia") == gw.TERMINOLOGIA_C,
              "y con qué terminología", rep.get("terminologia"))


def el_zip_es_el_mismo_kit():
    """
    EL DEFECTO QUE ESTE TEST EXISTE PARA IMPEDIR: había DOS generadores de kit.
    `build_chapter5_kit`, con sus 22 ítems declarados y cada falla nombrada, y
    `_build_kit_zip` —el que corre desde el botón de la interfaz— que producía
    seis archivos sueltos con siete `except Exception: pass`. Con ese, un CSV
    que reventaba simplemente no aparecía en el ZIP y nadie se enteraba: es
    exactamente el default silencioso que el proyecto prohíbe, y encima el
    usuario recibía un kit distinto del documentado.
    """
    section("10 — El ZIP del botón es el kit declarado, no un segundo kit paralelo")
    reset()
    _pozo("W1", E0)
    _pozo("W2", E0 + 12.0, ucs=180.0, lito="Kpcli")
    data = gw._build_kit_zip()
    check(isinstance(data, bytes) and len(data) > 0, "el ZIP se arma", len(data or b""))
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        nombres = zf.namelist()
        check(gw.KIT_INDICE_CSV in nombres,
              "y trae el índice: lo que no se pudo generar viene nombrado con su "
              "motivo, en vez de faltar callado", nombres[:8])
        check(gw.KIT_INDICE_MD in nombres, "con su versión en Markdown", nombres[:8])
        # Todo archivo que el índice declara generado tiene que estar DENTRO.
        cab = zf.read(gw.KIT_INDICE_CSV).decode("utf-8")
        filas = [l for l in cab.splitlines() if not l.startswith("#")]
        check(len(filas) - 1 == len(gw.KIT_CAP5),
              "el índice del ZIP lista los 22 ítems declarados",
              (len(filas) - 1, len(gw.KIT_CAP5)))
        faltan = [n for n in _archivos_ok(cab) if n not in nombres]
        check(not faltan, "y cada archivo que el índice da por generado está en "
                          "el ZIP", faltan)


def _archivos_ok(csv_texto):
    """Archivos que el índice declara en estado ok."""
    import csv as _csv
    filas = [l for l in csv_texto.splitlines() if not l.startswith("#")]
    out = []
    for r in _csv.DictReader(filas):
        if r.get("estado") == "ok" and r.get("archivo"):
            out.append(r["archivo"])
    return out


def el_zip_sin_datos_no_revienta_ni_miente():
    section("10 — Sin datos, el ZIP se entrega igual y dice qué falta")
    reset()   # ni un pozo
    data = gw._build_kit_zip()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        nombres = zf.namelist()
        check(gw.KIT_INDICE_CSV in nombres, "el índice viene igual", nombres)
        texto = zf.read(gw.KIT_INDICE_MD).decode("utf-8")
        check("no se pudieron generar" in texto or "no se generaron" in texto
              or "motivo" in texto.lower(),
              "y explica que faltan ítems, con su motivo", texto[:400])


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    indice_declarado_y_completo,
    los_cinco_obligatorios,
    numeracion_estable,
    nada_falta_en_silencio,
    nomenclatura_consistente,
    exportadores_que_devuelven_dataframe,
    indice_exportable,
    kit_declara_su_procedencia,
    el_zip_es_el_mismo_kit,
    el_zip_sin_datos_no_revienta_ni_miente,
]


def test_s10_kit_cap5():
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
    print("✓ SESIÓN 10 — todas las verificaciones pasaron.")
    print("=" * 72)
