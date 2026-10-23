"""
test_guardar_cargar_proyecto.py — Los botones de proyecto responden de verdad.

LO REPORTADO, en palabras del autor: «Sigue sin responder los botones de
guardado y cargado de proyecto».

DOS DEFECTOS DISTINTOS, uno por botón.

  · CARGAR: "btn-load-project" NO estaba en la lista de botones que hacen
    clic programático sobre el <input type=file> oculto — a diferencia de
    "btn-dxf", "btn-xml" y "btn-drillhole", que sí. Tenía en cambio un
    callback Python aparte que solo cambiaba el `style` del Upload a
    `display:block`. Ese Upload vive lejos del botón, en otra parte del
    layout, con `children=html.Span("")` — una caja vacía, sin borde visible
    ni texto. El usuario hacía clic y, en la práctica, no pasaba nada visible:
    el navegador nunca abre el selector de archivos nativo. Ahora está en la
    misma lista clientside que los otros tres.

  · GUARDAR: la lógica de guardado a disco funcionaba —se puede llamar
    directamente y produce el .gwz—, pero solo declaraba una ruta del
    servidor en un toast. Sin una descarga real del navegador, quien usa la
    plataforma (típicamente desde Colab) no tiene cómo recuperar el archivo:
    el botón "respondía" para el código pero no para la persona. Ahora,
    cuando el archivo es chico (≤ PROYECTO_DESCARGA_MAX_MB), se ofrece
    TAMBIÉN por descarga real; por sobre ese tamaño se explica por qué no.
"""

import os, sys

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


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _escenario():
    reset()
    pts = []
    for i in range(60):
        p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                        pr=45.0, pf=8.0, se=340.0, t=0.0)
        p.este = E0; p.norte = N0 + i * 0.15; p.cota = Z0 - i * 0.12
        p.entrenable = True; p.dominio = p.lito = "Bht"
        pts.append(p)
    gw.wells["T1"] = gw.Well(well_name="T1", plan_id="CAS_PR01_TH_P01",
                             hole_id="1", points=pts)


def _abre_click_de(upload_id):
    # _inline_scripts se puebla al renderizar el index, no al importar. El
    # cuerpo de la función clientside es genérico (function(n){...}) y no
    # menciona el id del BOTÓN —eso solo vive en el wiring Input/Output—, así
    # que lo que se busca es el id del Upload al que apunta el querySelector.
    gw.app.server.test_client().get("/")
    scripts = getattr(gw.app, "_inline_scripts", [])
    return [s for s in scripts
            if f"#{upload_id} input[type=file]" in s and "querySelector" in s]


# ─────────────────────────────────────────────────────────────────────────────
def cargar_abre_el_selector_nativo():
    section("Cargar — el botón abre el selector de archivos, como los otros tres")
    for btn, upload in (("btn-dxf", "up-dxf"), ("btn-xml", "up-xml"),
                        ("btn-drillhole", "up-drillhole"),
                        ("btn-load-project", "up-project")):
        hits = _abre_click_de(upload)
        check(hits, f"{btn} tiene su clientside callback que clickea "
              f"#{upload} input[type=file]", len(hits))
        check(f"{btn}.n_clicks" in gw.app.callback_map,
              f"y {btn}.n_clicks está registrado como salida de un callback: "
              "es la parte que hace que el clic de verdad dispare algo",
              btn)


def ya_no_hay_callback_que_solo_revele_el_upload():
    section("Cargar — no queda el callback viejo que solo cambiaba el estilo")
    check(not hasattr(gw, "trigger_load_project"),
          "trigger_load_project ya no existe: el defecto que dejaba el Upload "
          "invisible sin clickearlo se fue con la función, no se dejó al lado "
          "del arreglo nuevo")


def guardar_ofrece_descarga_real_cuando_es_chico():
    section("Guardar — un proyecto chico se ofrece por descarga, no solo a disco")
    _escenario()
    import tempfile
    tmpdir = tempfile.mkdtemp()
    gw.set_param("repo.ruta_proyecto", tmpdir)
    try:
        class Ctx:
            triggered_id = "btn-save-project"
            triggered = [{"value": 1}]
        gw.callback_context = Ctx()
        desc, is_open, body, *_ = gw.on_export_trigger(None, None, [None], 1, None)
        check(desc is not None and is_open, "el diálogo de confirmación se abre",
              (desc, is_open))
        out = gw.on_export_confirm(1, desc)
        check(len(out) == 6, "el callback de confirmar devuelve sus seis salidas",
              len(out))
        _, descarga, _, modal_open, mensaje, toast_open = out
        check(descarga is not gw.no_update,
              "y el segundo output (download-project) trae un archivo real "
              "para el navegador: antes quedaba siempre en no_update, que es "
              "exactamente 'el botón no responde'", descarga)
        check(modal_open is False, "el diálogo se cierra tras confirmar")
        check("guardado en" in mensaje.lower(), "el toast declara la ruta igual",
              mensaje)
        check("Sin descarga automática" not in mensaje,
              "y no trae la disculpa de tamaño, porque el archivo es chico")
        ruta_esperada = os.path.join(
            tmpdir, [f for f in os.listdir(tmpdir) if f.endswith(".gwz")][0])
        check(os.path.exists(ruta_esperada),
              "el .gwz efectivamente quedó escrito a disco también", ruta_esperada)
    finally:
        gw.reset_param("repo.ruta_proyecto")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def guardar_explica_cuando_no_descarga():
    section("Guardar — sobre el tamaño límite, se explica en vez de callar")
    _escenario()
    import tempfile
    tmpdir = tempfile.mkdtemp()
    gw.set_param("repo.ruta_proyecto", tmpdir)
    umbral_original = gw.PROYECTO_DESCARGA_MAX_MB
    gw.PROYECTO_DESCARGA_MAX_MB = -1.0   # cualquier archivo real "supera" esto
    try:
        class Ctx:
            triggered_id = "btn-save-project"
            triggered = [{"value": 1}]
        gw.callback_context = Ctx()
        desc, *_ = gw.on_export_trigger(None, None, [None], 1, None)
        out = gw.on_export_confirm(1, desc)
        _, descarga, _, _, mensaje, _ = out
        check(descarga is gw.no_update,
              "sin descarga cuando supera el umbral: no se intenta mandar un "
              "archivo que se sabe que va a fallar", descarga)
        check("Sin descarga automática" in mensaje and "MB" in mensaje,
              "y el mensaje dice por qué, con el número: callar ahí sería el "
              "default silencioso que el proyecto prohíbe", mensaje)
    finally:
        gw.PROYECTO_DESCARGA_MAX_MB = umbral_original
        gw.reset_param("repo.ruta_proyecto")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


def guardar_sin_datos_avisa_y_no_revienta():
    section("Guardar — sin pozos cargados, avisa en vez de intentar guardar vacío")
    reset()
    class Ctx:
        triggered_id = "btn-save-project"
        triggered = [{"value": 1}]
    gw.callback_context = Ctx()
    desc, is_open, body, *_ = gw.on_export_trigger(None, None, [None], 1, None)
    check(is_open is not True or desc is None,
          "sin pozos no se abre un diálogo prometiendo guardar nada",
          (desc, is_open))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    cargar_abre_el_selector_nativo,
    ya_no_hay_callback_que_solo_revele_el_upload,
    guardar_ofrece_descarga_real_cuando_es_chico,
    guardar_explica_cuando_no_descarga,
    guardar_sin_datos_avisa_y_no_revienta,
]


def test_guardar_cargar_proyecto():
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
    print("✓ GUARDAR/CARGAR PROYECTO — todas las verificaciones pasaron.")
    print("=" * 72)
