"""
test_centro_reportes.py — Los reportes se guardan y se abren, no se lanzan encima.

LO PEDIDO, en palabras del autor: «Los reportes que vas entregando podrían
quedar almacenados en algún lugar donde uno cliquee un botón, aparezca el
listado y puedas elegir cuál ver y/o descargar. Es más, podríamos notificar que
se habilitó o actualizó si se cambiaron los datos. Mas no lanzarlos encima para
no hacer más lento con ventanas.»

Dos exigencias, y la segunda es la que importa:

  1. Hay UN lugar con el listado, y desde ahí se abre o se baja el que se pida.
  2. ARMAR EL LISTADO NO CORRE NINGÚN REPORTE. Un centro de reportes que
     calcula los nueve para pintar los títulos es más lento que no tenerlo.
     Este test lo verifica de la única forma que vale: envolviendo cada
     generador y contando llamadas.

Y una tercera que este proyecto no negocia: un reporte que hoy no se puede
correr NO se ofrece en gris y ya. Dice qué falta. Un botón inerte sin motivo es
el default silencioso vestido de interfaz.
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


def _escenario(n_tiros=4, n_pts=80, seed=0):
    """Pozos con UCS y DI ya calculados, como después de correr el modelo."""
    reset()
    rng = np.random.default_rng(seed)
    for k in range(n_tiros):
        pts = []
        for i in range(n_pts):
            p = gw.MWDPoint(largo=i * 0.2, vel=0.9, pp=200.0, pa=60.0, pd=75.0,
                            pr=45.0, pf=8.0, se=340.0, t=0.0)
            p.este = E0 + k * 2.0 + rng.normal(0, .2)
            p.norte = N0 + i * 0.15
            p.cota = Z0 - i * 0.12
            p.entrenable = True
            p.dominio = p.lito = "Bht"
            p.di = 2.4 if 30 <= i < 50 else float(0.4 + rng.normal(0, .05))
            p.ucs_ml = float(128.1 + rng.normal(0, 6))
            p.ucs_matriz = p.ucs_ml
            p.ucs_modelo = "banda"
            pts.append(p)
        w = gw.Well(well_name=f"T{k}", plan_id="CAS_PR01_TH_P01", hole_id=f"{k}",
                    points=pts)
        w.caseron = "CAS_A"
        gw.wells[f"T{k}"] = w
    gw.domains["Bht"] = {"count": n_tiros * n_pts, "ucs_lab": 128.1,
                         "atributo_id": "Bht", "alteracion_id": None,
                         "estructura_id": None, "pi_factor": None, "calidad": 1,
                         "fuente_ucs": "prueba", "modo_ucs": "central"}


def _ids(x, out=None):
    out = [] if out is None else out
    if isinstance(x, (list, tuple)):
        for y in x:
            _ids(y, out)
        return out
    i = getattr(x, "id", None)
    if i is not None:
        out.append(i)
    for a in ("children", "title", "label"):
        v = getattr(x, a, None)
        if v is not None:
            _ids(v, out)
    return out


# ─────────────────────────────────────────────────────────────────────────────
def el_listado_existe_y_nombra_su_generador():
    section("Reportes — hay un listado, y cada entrada sabe quién la produce")
    check(len(gw.REPORTES) >= 6, "el catálogo tiene los reportes del programa",
          len(gw.REPORTES))
    ids = [r["id"] for r in gw.REPORTES]
    check(len(ids) == len(set(ids)), "sin ids repetidos", ids)
    for r in gw.REPORTES:
        for k in ("id", "titulo", "que", "gen"):
            check(r.get(k), f'{r.get("id")} declara {k}', sorted(r))
        fn = getattr(gw, r["gen"], None)
        check(callable(fn),
              f'el generador de {r["id"]} existe de verdad: un catálogo que '
              f'apunta a una función inexistente falla recién al hacer clic',
              r["gen"])


def armar_el_listado_no_corre_ni_un_reporte():
    section("Reportes — pintar la lista no calcula nada (esto es TODO el punto)")
    _escenario()
    llamadas = []
    originales = {}
    for r in gw.REPORTES:
        nombre = r["gen"]
        if nombre in originales:
            continue
        fn = getattr(gw, nombre)
        originales[nombre] = fn

        def espia(*a, _n=nombre, _f=fn, **kw):
            llamadas.append(_n)
            return _f(*a, **kw)
        setattr(gw, nombre, espia)
    try:
        lista = gw.reportes_disponibles()
        cuerpo = gw._reportes_panel_body()
    finally:
        for nombre, fn in originales.items():
            setattr(gw, nombre, fn)
    check(llamadas == [],
          "armar el listado NO corrió ningún reporte: si los corriera, abrir "
          "esta ventana costaría lo que cuestan los nueve juntos", llamadas)
    check(len(lista) == len(gw.REPORTES), "el listado los trae a todos",
          len(lista))
    ids = _ids(cuerpo)
    botones = [i for i in ids if isinstance(i, dict) and i.get("type") == "rep-ver"]
    check(len(botones) == len(gw.REPORTES),
          "y cada uno tiene su botón para abrirlo", len(botones))
    check("rep-salida" in ids, "con un lugar donde mostrarlo", ids)


def lo_que_no_se_puede_correr_dice_que_falta():
    section("Reportes — el que no se puede correr declara qué falta")
    reset()
    lista = gw.reportes_disponibles()
    bloqueados = [r for r in lista if not r["disponible"]]
    check(bloqueados,
          "sin datos cargados hay reportes que todavía no se pueden correr",
          len(bloqueados))
    check(all(r["motivo"] for r in bloqueados),
          "y TODOS dicen qué falta: un botón gris sin motivo no informa nada",
          [r["id"] for r in bloqueados if not r["motivo"]])
    _escenario()
    lista2 = gw.reportes_disponibles()
    habilitados = [r["id"] for r in lista2 if r["disponible"]]
    check(len(habilitados) > len([r["id"] for r in lista if r["disponible"]]),
          "al cargar datos se habilitan más reportes que antes", habilitados)
    check(all(not r["motivo"] for r in lista2 if r["disponible"]),
          "el habilitado no arrastra un motivo de bloqueo viejo")


def se_abre_el_que_se_pide_y_solo_ese():
    section("Reportes — se corre el que se pidió, no los demás")
    _escenario()
    llamadas = []
    originales = {}
    for r in gw.REPORTES:
        nombre = r["gen"]
        if nombre in originales:
            continue
        fn = getattr(gw, nombre)
        originales[nombre] = fn

        def espia(*a, _n=nombre, _f=fn, **kw):
            llamadas.append(_n)
            return _f(*a, **kw)
        setattr(gw, nombre, espia)
    try:
        rep = gw.generar_reporte("perfil")
    finally:
        for nombre, fn in originales.items():
            setattr(gw, nombre, fn)
    check(rep["status"] == "ok", "el reporte pedido corre", rep.get("motivo"))
    check(rep.get("titulo"), "y viene con su título", rep.get("titulo"))
    check(llamadas == ["site_profile_report"],
          "corrió UNO solo: el que se pidió", llamadas)


def un_reporte_que_revienta_no_tumba_la_pantalla():
    section("Reportes — si un generador falla, se dice; no se cae el programa")
    _escenario()
    rep = gw.generar_reporte("no_existe_este")
    check(rep["status"] == "error", "un id inexistente se rechaza", rep)
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))
    original = gw.site_profile_report

    def revienta():
        raise ValueError("falla de prueba")
    gw.site_profile_report = revienta
    try:
        rep2 = gw.generar_reporte("perfil")
    finally:
        gw.site_profile_report = original
    check(rep2["status"] == "error",
          "un generador que revienta se reporta como error, no propaga", rep2)
    check("falla de prueba" in str(rep2.get("motivo")),
          "y el motivo dice qué reventó de verdad, no un mensaje genérico",
          rep2.get("motivo"))
    vista = gw._render_reporte("perfil")
    check(vista is not None, "y la vista se arma igual")


def avisa_lo_que_se_habilito_desde_la_ultima_vez():
    section("Reportes — avisa cuál se habilitó al cargar datos nuevos")
    reset()
    gw._reportes_vistos.clear()
    gw._reportes_panel_body()                    # primera mirada: queda visto
    check(gw.reportes_nuevos() == [],
          "mirar dos veces sin cambiar nada no inventa novedades",
          gw.reportes_nuevos())
    _escenario()
    nuevos = gw.reportes_nuevos()
    check(nuevos,
          "al cargar pozos y correr el modelo, avisa cuáles se habilitaron",
          nuevos)
    cuerpo = gw._reportes_panel_body()
    check(gw.reportes_nuevos() == [],
          "y una vez avisado no vuelve a insistir con lo mismo",
          gw.reportes_nuevos())
    check(cuerpo is not None, "el panel se arma con el aviso dentro")


def el_boton_esta_en_la_barra():
    section("Reportes — se llega desde la barra, con un clic")
    ids = _ids(gw.app.layout)
    for i in ("btn-open-reportes", "reportes-modal", "reportes-body",
              "dl-reporte", "rep-abierto"):
        check(i in ids, f"la interfaz tiene {i}")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    el_listado_existe_y_nombra_su_generador,
    armar_el_listado_no_corre_ni_un_reporte,
    lo_que_no_se_puede_correr_dice_que_falta,
    se_abre_el_que_se_pide_y_solo_ese,
    un_reporte_que_revienta_no_tumba_la_pantalla,
    avisa_lo_que_se_habilito_desde_la_ultima_vez,
    el_boton_esta_en_la_barra,
]


def test_centro_reportes():
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
    print("✓ CENTRO DE REPORTES — todas las verificaciones pasaron.")
    print("=" * 72)
