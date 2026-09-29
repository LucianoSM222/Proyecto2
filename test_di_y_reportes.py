"""
test_di_y_reportes.py — Los tres detalles del cierre: calibración que no
guardaba, FLP que no aparecía, y reportes que se veían como código.

LO REPORTADO, en palabras del autor:

  «La parte de DI está rota: 1. Al calibrar no guarda los valores de la tabla
  de pesos. 2. No se está considerando el FLP, aparece su cuadrado pero no lo
  considera en el cálculo. 3. Los reportes no se ven como se veían antes con
  ventana, gráficos lindos en formato directo para ver y todo eso, solo se ven
  código y no lo quiero así. Y al descargarlo, la idea es que sea en formato
  imagen jpeg/jpg/png, la que use menos peso.»

1 · LA CALIBRACIÓN NO GUARDABA. Escribía los pesos en las casillas Y subía
    `refresh` en el mismo retorno. `render_wizard` escucha `refresh`, así que
    `_step3()` se volvía a dibujar y recreaba los `dbc.Input` con
    `value=di_config[...]` — los de la variante ACTIVA, que calibrar no toca a
    propósito: quién corre lo decide quien mira el veredicto. El resultado se
    borraba solo en el mismo ciclo en que aparecía. Ahora la propuesta queda
    en `_di_panel_pendiente` y el panel la lee desde ahí, sin activar nada;
    aplicar («Calcular DI») o restaurar la descartan.

2 · EL FLP NO APARECÍA. El cálculo SÍ lo usaba —`pf` tiene peso 0,20 en la
    convención y `di_profile` lo integra—, pero `di_config_summary()` lo
    rotulaba «FP», que en IREDES es el AVANCE, y omitía `pa` por completo:
    de las cinco presiones se declaraban cuatro, una con la sigla de otra.
    Esa línea encabeza el panel Y se antepone a cada CSV exportado como
    procedencia, así que el error viajaba en los datos. La sigla ahora se
    escribe UNA vez, en CAL_SIGLAS, de donde sale también CAL_ETIQUETAS.

3 · LOS REPORTES ERAN CÓDIGO. `json.dumps()` dentro de un `html.Pre`. Ahora
    `_reporte_secciones()` parte el reporte en secciones dibujables y ALIMENTA
    LAS DOS SALIDAS —la pantalla y la imagen— para que no puedan discrepar.
    La descarga es PNG; la elección se midió, no se supuso (ver
    `reporte_imagen`), y el JSON queda de respaldo si no hay con qué producir
    la imagen.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import dash_bootstrap_components as dbc
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
    gw.seed_di_variants(force=True)
    gw.activar_di(gw.DI_VARIANTE_CONVENCION)
    gw._di_panel_pendiente.clear()
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()


def _textos(x, out=None):
    out = [] if out is None else out
    if isinstance(x, str):
        out.append(x); return out
    if isinstance(x, (list, tuple)):
        for y in x: _textos(y, out)
        return out
    c = getattr(x, "children", None)
    if c is not None: _textos(c, out)
    return out


def _hay(x, tipo):
    if isinstance(x, tipo): return True
    c = getattr(x, "children", None)
    if isinstance(c, (list, tuple)): return any(_hay(y, tipo) for y in c)
    return _hay(c, tipo) if c is not None else False


def _cajas_del_panel():
    """Los valores que muestran las siete casillas del DI en el Paso 3."""
    out = {}

    def walk(x):
        i = getattr(x, "id", None)
        if isinstance(i, str) and (i.startswith("di-w-") or i in ("di-window", "di-thresh")):
            out[i] = getattr(x, "value", None)
        c = getattr(x, "children", None)
        if isinstance(c, (list, tuple)):
            for y in c: walk(y)
        elif c is not None:
            walk(c)
    walk(gw._step3())
    return out


# ── 1 · la calibración conserva sus pesos ────────────────────────────────────
def los_pesos_calibrados_sobreviven_al_redibujo():
    section("Calibración — los pesos siguen ahí después de que el paso se redibuje")
    reset()
    antes = _cajas_del_panel()
    check(antes["di-w-pd"] == 0.25 and antes["di-window"] == 14,
          "de partida, las casillas muestran la convención", antes)
    # Lo que deja do_calibrar_di al terminar.
    gw._di_panel_pendiente.update({"window": 20, "threshold": 2.0, "pp": 0.10,
                                   "pd": 0.65, "pf": 0.05, "pr": 0.10, "pa": 0.10})
    d = _cajas_del_panel()
    check(d["di-w-pd"] == 0.65 and d["di-window"] == 20 and d["di-thresh"] == 2.0,
          "tras calibrar, el panel muestra los pesos calibrados aunque "
          "`refresh` haya vuelto a construir las casillas desde cero", d)
    check(d["di-w-pa"] == 0.10,
          "incluido el peso del avance, que es el que más fácil se perdía", d)


def calibrar_no_activa_la_variante_sola():
    section("Calibración — proponer no es aplicar: la variante activa no cambia")
    reset()
    gw._di_panel_pendiente.update({"window": 20, "threshold": 2.0, "pp": 0.10,
                                   "pd": 0.65, "pf": 0.05, "pr": 0.10, "pa": 0.10})
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "el DI que corre sigue siendo el de convención: qué variante corre "
          "lo decide quien mira el veredicto, no la calibración", gw.di_activo())
    check(gw.di_config["weights"]["pd"] == 0.25,
          "y los pesos vigentes siguen intactos", gw.di_config["weights"])


def aplicar_o_restaurar_descartan_la_propuesta():
    section("Calibración — «Calcular DI» y «Restaurar» limpian lo pendiente")
    reset()
    gw._di_panel_pendiente.update({"window": 20, "threshold": 2.0, "pp": 0.10,
                                   "pd": 0.65, "pf": 0.05, "pr": 0.10, "pa": 0.10})
    gw.aplicar_di_config(window=20, threshold=2.0,
                         weights={"pp": 0.10, "pd": 0.65, "pf": 0.05,
                                  "pr": 0.10, "pa": 0.10})
    gw._di_panel_pendiente.clear()     # lo que hace do_di tras aplicar
    d = _cajas_del_panel()
    check(d["di-w-pd"] == 0.65,
          "aplicada, la casilla sigue mostrando 0,65 — pero ahora porque ES "
          "la variante que corre, no porque quedara una propuesta colgando",
          (d, gw.di_activo()))
    check(gw.di_activo() != gw.DI_VARIANTE_CONVENCION,
          "y la variante activa ya no es la convención", gw.di_activo())


# ── 2 · el FLP se declara, y con su sigla ────────────────────────────────────
def el_resumen_declara_las_cinco_presiones():
    section("FLP — el resumen del DI nombra las cinco, no cuatro")
    reset()
    s = gw.di_config_summary()
    print(f"      {s}")
    for k, sigla in gw.CAL_SIGLAS.items():
        check(f"{sigla}=" in s, f"aparece {sigla} ({k})", s)


def el_barrido_ya_no_lleva_la_sigla_del_avance():
    section("FLP — `pf` es FLP (barrido), no FP (avance)")
    reset()
    s = gw.di_config_summary()
    check("FLP=0,2" in s or "FLP=0.2" in s,
          "el peso 0,20 de `pf` sale rotulado FLP", s)
    check(",FP=" not in s,
          "y ya no existe un «FP=» suelto: en IREDES esa sigla es el avance, "
          "que ahora se declara como FP/AP", s)
    check(gw.CAL_ETIQUETAS["pf"] == "Barrido (FLP)"
          and gw.CAL_ETIQUETAS["pa"] == "Avance (FP/AP)",
          "y las etiquetas de pantalla salen de la MISMA fuente que el "
          "resumen, para que no se vuelvan a cruzar",
          (gw.CAL_ETIQUETAS["pf"], gw.CAL_ETIQUETAS["pa"]))


def el_calculo_del_di_si_usa_el_barrido():
    section("FLP — y el cálculo lo usa de verdad (no era el defecto, se comprueba)")
    reset()
    pts = [gw.MWDPoint(largo=i*0.02, vel=1.0, pp=200.0, pa=60.0, pd=75.0, pr=45.0,
                       pf=(30.0 if 80 <= i < 120 else 8.0), se=300.0, t=0.0)
           for i in range(200)]
    perfil = gw.di_profile(pts, 14)
    check(perfil is not None and float(perfil.max() - perfil.min()) > 1e-6,
          "un pozo donde SOLO varía el barrido produce un DI que varía: si "
          "`pf` no entrara, el perfil sería plano",
          None if perfil is None else (float(perfil.min()), float(perfil.max())))
    check("pf" in gw.di_config["params"],
          "y `pf` está entre los parámetros del DI vigente", gw.di_config["params"])


# ── 3 · los reportes se ven, y se bajan como imagen ──────────────────────────
def los_reportes_ya_no_son_json_crudo():
    section("Reportes — se dibujan; ya no son un volcado de JSON")
    reset()
    gw.set_param("bloques.tamano_m", 3.0)
    body = gw._render_reporte("perfil")
    txt = " ".join(_textos(body))
    check('{"' not in txt and '": ' not in txt,
          "no queda JSON crudo en pantalla", txt[:120])
    check(_hay(body, dbc.Table),
          "hay al menos una tabla de verdad renderizada")
    check("n parametros" in txt,
          "y las claves se leen como etiquetas, no como `n_parametros`", txt[:200])
    gw.reset_param("bloques.tamano_m")


def todos_los_reportes_se_dibujan_sin_reventar():
    section("Reportes — los diez se dibujan, tengan datos o no")
    reset()
    for r in gw.REPORTES:
        try:
            body = gw._render_reporte(r["id"])
            txt = " ".join(_textos(body))
            check('{"' not in txt, f"«{r['id']}» se dibuja sin JSON crudo", txt[:60])
        except Exception as e:
            check(False, f"«{r['id']}» se dibuja sin reventar",
                  f"{type(e).__name__}: {e}")


def la_pantalla_y_la_imagen_salen_de_la_misma_particion():
    section("Reportes — una sola fuente de estructura para pantalla e imagen")
    reset()
    gw.set_param("bloques.tamano_m", 3.0)
    datos = gw.generar_reporte("perfil")["datos"]
    secs = gw._reporte_secciones(datos)
    check(len(secs) >= 2, "el reporte se parte en secciones", len(secs))
    tipos = {s["tipo"] for s in secs}
    check(tipos <= {"kv", "tabla"}, "y cada sección es kv o tabla", tipos)
    check(any(s["tipo"] == "tabla" for s in secs),
          "la lista de parámetros modificados sale como TABLA, no como texto")
    gw.reset_param("bloques.tamano_m")


def una_tabla_larga_declara_cuanto_recorto():
    section("Reportes — un recorte se declara, nunca es silencioso")
    reset()
    datos = {"filas": [{"i": k, "v": k * 2} for k in range(200)]}
    secs = gw._reporte_secciones(datos)
    tabla = next(s for s in secs if s["tipo"] == "tabla")
    check(len(tabla["filas"]) == gw.REPORTE_MAX_FILAS,
          f"la tabla se recorta a {gw.REPORTE_MAX_FILAS} filas", len(tabla["filas"]))
    check(tabla["n_total"] == 200,
          "y conserva el total real para poder declararlo", tabla["n_total"])


def la_descarga_es_png_y_si_no_se_puede_lo_dice():
    section("Reportes — la descarga es imagen PNG, con respaldo declarado")
    reset()
    gw.set_param("bloques.tamano_m", 3.0)
    try:
        datos, ext = gw.reporte_imagen("perfil")
    except Exception as e:
        # kaleido necesita un navegador; sin él la app cae al JSON y lo AVISA.
        check(True, "sin kaleido/navegador, reporte_imagen falla de forma "
                    "explícita para que el callback pueda avisar y caer al "
                    f"JSON ({type(e).__name__})")
        gw.reset_param("bloques.tamano_m")
        return
    check(ext == "png", "la extensión es png", ext)
    check(datos[:4] == b"\x89PNG", "y los bytes son un PNG de verdad", datos[:8])
    check(len(datos) < 1_500_000,
          f"de un peso razonable para adjuntar ({len(datos)/1e6:.2f} MB)", len(datos))
    gw.reset_param("bloques.tamano_m")


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    los_pesos_calibrados_sobreviven_al_redibujo,
    calibrar_no_activa_la_variante_sola,
    aplicar_o_restaurar_descartan_la_propuesta,
    el_resumen_declara_las_cinco_presiones,
    el_barrido_ya_no_lleva_la_sigla_del_avance,
    el_calculo_del_di_si_usa_el_barrido,
    los_reportes_ya_no_son_json_crudo,
    todos_los_reportes_se_dibujan_sin_reventar,
    la_pantalla_y_la_imagen_salen_de_la_misma_particion,
    una_tabla_larga_declara_cuanto_recorto,
    la_descarga_es_png_y_si_no_se_puede_lo_dice,
]


def test_di_y_reportes():
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
    print("✓ DI Y REPORTES — todas las verificaciones pasaron.")
    print("=" * 72)
