"""
test_tronadura_coherencia_y_dxf.py — El aviso de tronadura ya no se contradice
consigo mismo, y el sólido se puede sacar de la plataforma.

LO OBSERVADO por el autor, en sus palabras:

  «El soporte de la tronadura me parece excelente, como idea, pero
  técnicamente me causa rareza pues dice que no está calibrado con RQD pero
  se supone que si lo está, pues de ahí salen los pesos del DI, con los que
  debes graficar.»

Tenía razón. `TRONADURA_ADVERTENCIA` era un texto FIJO que decía "el DI es un
índice relativo de fracturamiento que no está calibrado en puntos de RQD" sin
condición — pero el sólido se pinta con `p.di`, que sale de la variante de DI
REALMENTE activa (`di_activo()`). Si esa variante es una calibrada contra el
testigo, la frase quedaba falsa: el aviso decía una cosa, los pesos que
coloreaban el sólido decían otra. `_tronadura_advertencia_di()` construye la
frase contra la variante activa de verdad, con su veredicto de validación
cuando corresponde.

7.1 pedía además poder elegir qué UCS mostrar y exportar el sólido como .dxf
con atributos por punto (UCS, DI, litología, confianza). Se implementa:

  · `tronadura-ucs-fuente`: elige entre la UCS de matriz (con las
    discontinuidades ya restadas) y la cruda. Elegir ENTRE MODELOS —banda,
    relación, ml— sigue siendo del Paso 4: eso decide qué hay en p.ucs_ml:
    esto elige cuál de sus dos salidas colorea el sólido.
  · `exportar_bloques_dxf()`: un punto por bloque en Este/Norte/Cota —la
    convención de ejes del proyecto—, con XDATA (appid MWD_GEOMECH) llevando
    UCS_MPA, DI, LITOLOGIA, CONFIANZA, BANDA y CASERON. Un bloque sin soporte
    no se exporta, igual que no se dibuja.

NO SE TOCA en este cambio: la crítica de que el sólido (interpolado por IDW)
no capta una falla que el DI puntual sí capta es un problema de RESOLUCIÓN
del modelo de bloques, no de qué variante de DI se usa — queda fuera de
alcance de este arreglo y merece su propia investigación con los datos
reales.
"""

import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np
import ezdxf
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
    gw.layers.clear(); gw.wells.clear(); gw.domains.clear()
    gw.drillholes.clear()
    gw.set_tronadura_ucs_fuente("ucs_matriz")


E0, N0, Z0 = 376700.0, 6959000.0, 300.0


def _abanico(n_tiros=6, n_pts=160, seed=0):
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
            p.di = 2.4 if 60 <= i < 95 else float(0.4 + rng.normal(0, .05))
            p.ucs_ml = 95.0 if 60 <= i < 95 else float(128.1 + rng.normal(0, 6))
            p.ucs_matriz = float(p.ucs_ml) + 3.0   # distinto de ucs_ml, a propósito
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
    gw.ucs_modelo_vigente = "banda"


def _activar_variante_calibrada(nombre="cal_prueba", **kw):
    pesos = {"pp": 0.05, "pd": 0.70, "pf": 0.05, "pr": 0.10, "pa": 0.10}
    pesos.update(kw)
    if nombre in gw.di_variantes:
        gw.delete_di_variant(nombre)
    gw.create_di_variant(
        nombre, weights=pesos, window=14, threshold=1.5,
        fuente="Calibrado contra el RQD de 4 sondaje(s), radio 5 m, 40 par(es). "
               "rho ajuste +0.80 · rho validación +0.42.",
        notas="GENERALIZA: ajuste +0.80, validación +0.42. Los pesos "
              "transfieren al sondaje que no participó del ajuste.")
    gw.activar_di(nombre)
    return nombre


# ─────────────────────────────────────────────────────────────────────────────
def con_la_convencion_el_aviso_lo_dice():
    section("Aviso DI — con la convención, declara que NO está calibrado")
    _abanico()
    check(gw.di_activo() == gw.DI_VARIANTE_CONVENCION,
          "arranca con la convención", gw.di_activo())
    rep = gw.tronadura_resumen()
    check(rep["status"] == "ok", "el resumen corre", rep.get("motivo"))
    check("NO calibrados" in rep["advertencia_di"],
          "y el aviso dice, correctamente, que estos pesos no vienen del "
          "testigo", rep["advertencia_di"])
    check("Fernández" in rep["advertencia_di"],
          "nombrando la convención", rep["advertencia_di"])


def con_variante_calibrada_el_aviso_ya_no_se_contradice():
    section("Aviso DI — con una variante calibrada, el aviso deja de mentir")
    _abanico()
    nombre = _activar_variante_calibrada()
    rep = gw.tronadura_resumen()
    check(rep["status"] == "ok", "el resumen corre", rep.get("motivo"))
    check("NO calibrados" not in rep["advertencia_di"],
          "ya NO dice que los pesos no están calibrados: es justo la "
          "afirmación falsa que reportó el autor", rep["advertencia_di"])
    check(nombre in rep["advertencia_di"],
          "y nombra la variante que de verdad está coloreando el sólido",
          rep["advertencia_di"])
    check("GENERALIZA" in rep["advertencia_di"],
          "trayendo el veredicto de validación real de esa calibración, no "
          "una frase genérica", rep["advertencia_di"])
    check("0.7" in rep["advertencia_di"],
          "y los pesos que de verdad se están usando, no un resumen vago",
          rep["advertencia_di"])


def la_advertencia_general_ya_no_promete_lo_que_el_di_no_promete():
    section("Aviso general — deja de mezclar la reserva de UCS con la de DI")
    _abanico()
    rep = gw.tronadura_resumen()
    check("no está calibrado en puntos de RQD" not in rep["advertencia"],
          "el aviso GENERAL ya no lleva la frase sobre RQD embebida: esa "
          "declaración es del DI, condicional a la variante, y vive en su "
          "propio campo", rep["advertencia"])
    check("APROXIMACIÓN" in rep["advertencia"],
          "pero sigue siendo honesto sobre qué NO es este sólido",
          rep["advertencia"])


def se_puede_elegir_la_fuente_de_ucs():
    section("7.1 — se puede elegir qué UCS colorea el sólido")
    _abanico()
    check(gw.tronadura_ucs_fuente() == "ucs_matriz",
          "por defecto es la UCS de matriz", gw.tronadura_ucs_fuente())
    rep_matriz = gw._bloques_vigentes()
    check(rep_matriz["status"] == "ok", "corre con matriz", rep_matriz.get("motivo"))

    gw.set_tronadura_ucs_fuente("ucs_ml")
    check(gw.tronadura_ucs_fuente() == "ucs_ml", "el cambio se aplica")
    rep_ml = gw._bloques_vigentes()
    check(rep_ml["status"] == "ok", "y corre igual con la cruda", rep_ml.get("motivo"))

    ucs_matriz = sorted(b["ucs"] for b in rep_matriz["bloques"] if b.get("ucs") is not None)
    ucs_ml = sorted(b["ucs"] for b in rep_ml["bloques"] if b.get("ucs") is not None)
    check(ucs_matriz != ucs_ml,
          "y el sólido de verdad cambia: las dos fuentes se armaron "
          "distintas a propósito (ucs_matriz = ucs_ml + 3)",
          (ucs_matriz[:3], ucs_ml[:3]))


def una_fuente_invalida_se_rechaza():
    section("7.1 — una fuente que no existe se rechaza, no se acepta a medias")
    reset()
    try:
        gw.set_tronadura_ucs_fuente("no_existe")
        check(False, "una fuente inválida debía levantar ValueError")
    except ValueError as e:
        check(True, "se rechaza con mensaje", str(e))
    check(gw.tronadura_ucs_fuente() == "ucs_matriz",
          "y la fuente vigente no cambió", gw.tronadura_ucs_fuente())


def exportar_dxf_trae_un_punto_por_bloque_con_atributos():
    section("7.1 — exportar DXF: un punto por bloque, con UCS/DI/litología/confianza")
    _abanico()
    rep = gw.exportar_bloques_dxf()
    check(rep["status"] == "ok", "la exportación corre", rep.get("motivo"))
    if rep["status"] != "ok":
        return
    check(rep["n_bloques"] > 0, "con bloques adentro", rep["n_bloques"])

    doc = ezdxf.read(__import__("io").StringIO(rep["dxf"]))
    msp = doc.modelspace()
    puntos = list(msp.query("POINT"))
    check(len(puntos) == rep["n_bloques"],
          "un punto DXF por bloque exportado", (len(puntos), rep["n_bloques"]))

    p0 = puntos[0]
    # Las seis entradas SON del mismo código de grupo (1000, texto libre): un
    # dict keyed por código las colapsaría a una sola. Se guarda la lista.
    valores = [tag.value for tag in p0.get_xdata("MWD_GEOMECH")]
    check(len(valores) == 6, "el punto trae sus seis atributos, no menos",
          valores)
    for clave in ("UCS_MPA", "DI", "LITOLOGIA", "CONFIANZA", "BANDA", "CASERON"):
        check(any(v.startswith(f"{clave}=") for v in valores),
              f"cada punto lleva {clave} en su XDATA", valores)

    x, y, z = p0.dxf.location.x, p0.dxf.location.y, p0.dxf.location.z
    check(abs(x - E0) < 200 and abs(y - N0) < 200,
          "las coordenadas quedan en Este/Norte reales, no reescaladas",
          (x, y, z))


def un_bloque_sin_soporte_no_se_exporta():
    section("7.1 — un bloque sin datos no se exporta, igual que no se dibuja")
    _abanico()
    rep_bloques = gw._bloques_vigentes()
    n_con_soporte = len([b for b in rep_bloques["bloques"]
                         if b.get("ucs") is not None or b.get("di") is not None])
    rep_dxf = gw.exportar_bloques_dxf()
    check(rep_dxf["n_bloques"] == n_con_soporte,
          "el conteo exportado coincide con los bloques que sí tienen "
          "soporte de datos, no con el total del encajonado",
          (rep_dxf["n_bloques"], n_con_soporte))


def sin_modelo_de_bloques_la_exportacion_declara_por_que():
    section("7.1 — sin datos, la exportación explica en vez de generar un DXF vacío")
    reset()
    rep = gw.exportar_bloques_dxf()
    check(rep["status"] != "ok", "sin datos no hay DXF que generar", rep["status"])
    check(rep.get("motivo"), "con el motivo", rep.get("motivo"))


def el_boton_de_exportar_esta_en_el_panel():
    section("7.1 — se llega al DXF desde la pantalla")
    _abanico()
    cuerpo = gw._tronadura_panel_body()

    def _ids(x, out=None):
        out = [] if out is None else out
        if isinstance(x, (list, tuple)):
            for y in x: _ids(y, out)
            return out
        i = getattr(x, "id", None)
        if i is not None: out.append(i)
        for a in ("children",):
            v = getattr(x, a, None)
            if v is not None: _ids(v, out)
        return out
    ids = _ids(cuerpo)
    for i in ("btn-tronadura-dxf", "tronadura-ucs-fuente", "tronadura-cifras"):
        check(i in ids, f"el panel tiene {i}", ids)


def cambiar_variante_di_invalida_el_cache_de_bloques():
    section("Regresión — cambiar de variante DI se refleja en el sólido sin botón")
    _abanico()
    rep_conv = gw._bloques_vigentes()
    di_conv = sorted(b["di"] for b in rep_conv["bloques"] if b.get("di") is not None)
    _activar_variante_calibrada("cal_prueba2", pd=0.9, pp=0.025, pf=0.025, pr=0.025, pa=0.025)
    gw.compute_di()
    rep_cal = gw._bloques_vigentes()
    di_cal = sorted(b["di"] for b in rep_cal["bloques"] if b.get("di") is not None)
    check(di_conv != di_cal,
          "la firma del caché de bloques incluye la variante activa: "
          "cambiarla y recalcular produce un DI distinto, no el mismo "
          "resultado servido de memoria", (di_conv[:3], di_cal[:3]))


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    con_la_convencion_el_aviso_lo_dice,
    con_variante_calibrada_el_aviso_ya_no_se_contradice,
    la_advertencia_general_ya_no_promete_lo_que_el_di_no_promete,
    se_puede_elegir_la_fuente_de_ucs,
    una_fuente_invalida_se_rechaza,
    exportar_dxf_trae_un_punto_por_bloque_con_atributos,
    un_bloque_sin_soporte_no_se_exporta,
    sin_modelo_de_bloques_la_exportacion_declara_por_que,
    el_boton_de_exportar_esta_en_el_panel,
    cambiar_variante_di_invalida_el_cache_de_bloques,
]


def test_tronadura_coherencia_y_dxf():
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
    print("✓ TRONADURA: COHERENCIA Y EXPORTACIÓN DXF — todas pasaron.")
    print("=" * 72)
