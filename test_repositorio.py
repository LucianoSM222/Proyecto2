"""
test_repositorio.py — Carpeta-repositorio y guardado a disco.

DOS COSAS QUE VAN JUNTAS:

  · GUARDAR A CARPETA. El .gwz se guarda bien —ida y vuelta verificada con
    140 pozos y 164.524 puntos— pero pesa 18 MB, y descargar eso por el
    navegador en Colab falla sin decir nada. Guardar a una ruta del disco
    esquiva el transporte entero.

  · CARGAR DESDE CARPETA. En vez de subir archivo por archivo, se apunta a una
    carpeta del computador que hace de repositorio y el programa la recorre.
    Es lo que vuelve manejable un caserón con 477 XML.

El descubrimiento NO adivina en silencio: devuelve qué encontró, clasificado
por tipo, y qué archivos no supo clasificar. Un archivo que no se reconoce se
nombra, no se descarta callado.
"""

import os, sys, tempfile, json

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
    gw.seed_param_registry(force=True)
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()


def _repo(base):
    """Repositorio de mentira con la estructura que tendría uno real."""
    est = {
        "PCS_1043/xml/DQPCS_1043_TH_P01.xml": "<DRPQual/>",
        "PCS_1043/xml/MWPCS_1043_TH_P01H1.xml": "<x/>",
        "PCS_1043/capas/litologia/Bht.dxf": "0\nSECTION\n",
        "PCS_1043/capas/estructura/FM1.dxf": "0\nSECTION\n",
        "sondajes/MPC_header.csv": "holeid;x_utm\n",
        "sondajes/MPC_survey.csv": "holeid;depth\n",
        "notas/leeme.txt": "esto no es dato",
        "PCS_1043/planilla.xlsx": "no importa",
    }
    for rel, txt in est.items():
        p = os.path.join(base, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(txt)
    return base


# ─────────────────────────────────────────────────────────────────────────────
def descubre_y_clasifica():
    section("Repositorio — recorre la carpeta y clasifica lo que encuentra")
    with tempfile.TemporaryDirectory() as td:
        _repo(td)
        rep = gw.explorar_repositorio(td)
        check(rep["status"] == "ok", "el recorrido corre", rep.get("motivo"))
        if rep["status"] != "ok":
            return
        check(len(rep["dxf"]) == 2, "encuentra los dos DXF", rep["dxf"])
        check(len(rep["dq"]) == 1, "el DQ", rep["dq"])
        check(len(rep["mw"]) == 1, "el MW", rep["mw"])
        check(len(rep["sondajes"]) == 2, "y los CSV de sondaje", rep["sondajes"])
        check(rep["raiz"] == td, "declara desde dónde miró", rep.get("raiz"))


def lo_no_reconocido_se_nombra():
    section("Repositorio — lo que no reconoce lo NOMBRA, no lo descarta callado")
    with tempfile.TemporaryDirectory() as td:
        _repo(td)
        rep = gw.explorar_repositorio(td)
        nombres = " ".join(rep.get("no_reconocidos") or [])
        check("leeme.txt" in nombres, "el txt aparece entre los no reconocidos",
              rep.get("no_reconocidos"))
        check("planilla.xlsx" in nombres, "y la planilla también",
              rep.get("no_reconocidos"))
        check(rep.get("motivo_no_reconocidos"),
              "con una explicación de qué significa que estén ahí",
              rep.get("motivo_no_reconocidos"))


def el_caseron_sale_de_la_carpeta():
    section("Repositorio — el caserón se deduce de la carpeta que lo contiene")
    with tempfile.TemporaryDirectory() as td:
        _repo(td)
        rep = gw.explorar_repositorio(td)
        cas = rep.get("por_caseron") or {}
        check("PCS_1043" in cas, "se reconoce el caserón por su carpeta", sorted(cas))
        d = cas.get("PCS_1043") or {}
        check(len(d.get("dxf") or []) == 2 and len(d.get("mw") or []) == 1,
              "con sus archivos asociados", {k: len(v) for k, v in d.items()})
        check(rep.get("criterio_caseron"),
              "declarando con qué criterio se dedujo", rep.get("criterio_caseron"))


def carpeta_inexistente_se_declara():
    section("Repositorio — una carpeta que no existe se declara, no revienta")
    rep = gw.explorar_repositorio("/no/existe/esta/carpeta")
    check(rep["status"] == "error", "el estado lo dice", rep.get("status"))
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))


def guardar_a_disco():
    section("Guardado — a una ruta del disco, sin pasar por el navegador")
    reset()
    pts = [gw.MWDPoint(largo=i * 0.5, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                       pr=45.0, pf=8.0, se=340.0, t=0.0) for i in range(20)]
    for i, p in enumerate(pts):
        p.este = 376700.0; p.norte = 6959000.0; p.cota = 300.0 - i * 0.5
        p.entrenable = True
    w = gw.Well(well_name="W1", plan_id="P1", hole_id="1", points=pts)
    w.caseron = "CAS_A"
    gw.wells["W1"] = w

    with tempfile.TemporaryDirectory() as td:
        destino = os.path.join(td, "sub", "proyecto.gwz")
        rep = gw.guardar_proyecto_en(destino)
        check(rep["status"] == "ok", "guarda", rep.get("motivo"))
        check(os.path.exists(destino), "el archivo existe en la ruta pedida", destino)
        check(rep["tamano_bytes"] > 0 and rep["tamano_MB"] >= 0,
              "y declara cuánto pesa, en bytes y en MB",
              (rep.get("tamano_bytes"), rep.get("tamano_MB")))
        check(rep["n_pozos"] == 1 and rep["n_puntos"] == 20,
              "con qué guardó", (rep.get("n_pozos"), rep.get("n_puntos")))
        # Y se puede volver a cargar desde ahí.
        reset()
        gw.load_project(destino)
        check(len(gw.wells) == 1, "y se recupera desde el disco", list(gw.wells))

    # Una ruta imposible se declara en vez de reventar.
    rep2 = gw.guardar_proyecto_en("/proc/no/puedo/escribir.gwz")
    check(rep2["status"] == "error", "una ruta imposible se declara",
          rep2.get("status"))
    check(rep2.get("motivo"), "con el motivo", rep2.get("motivo"))
    reset()


def la_ruta_del_repositorio_es_configurable():
    section("Repositorio — la ruta vive en el perfil de faena")
    check("repo.ruta" in gw.param_registry,
          "la carpeta-repositorio es un parámetro, no una constante")
    p = gw.param_registry.get("repo.ruta") or {}
    check(p.get("tipo") == "texto", "de tipo texto", p.get("tipo"))
    gw.set_param("repo.ruta", "/tmp/mi_repo")
    check(gw.get_param("repo.ruta") == "/tmp/mi_repo", "se puede fijar")
    d = json.loads(gw.export_site_profile())
    check(d["parametros"].get("repo.ruta") == "/tmp/mi_repo",
          "y viaja en el perfil exportado")
    gw.seed_param_registry(force=True)


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    descubre_y_clasifica,
    lo_no_reconocido_se_nombra,
    el_caseron_sale_de_la_carpeta,
    carpeta_inexistente_se_declara,
    guardar_a_disco,
    la_ruta_del_repositorio_es_configurable,
]


def test_repositorio():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
        gw.seed_param_registry(force=True)
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    try:
        for t in ALL_TESTS:
            t()
    finally:
        reset()
        gw.seed_param_registry(force=True)
    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ REPOSITORIO — todas las verificaciones pasaron.")
    print("=" * 72)
