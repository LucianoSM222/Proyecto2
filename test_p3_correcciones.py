"""
test_p3_correcciones.py — Validación de P3 (correcciones de uso real) para
geomech_wizard.

Cubre las nueve tareas, cada una independiente:
  3.1  Guardia contra entrenamiento degenerado (una sola etiqueta, o clases
       con muy pocas muestras)
  3.2  Reporte de composición del entrenamiento: embudo completo, incluido
       el corte de emboquillado
  3.3  Exportaciones distinguibles: nombre con sitio+caserón+fecha,
       descriptor con conteo antes de descargar
  3.4  Renombre "UCS confiable" -> "UCS matriz (sin discontinuidades)"
  3.5  Selector de variable en el perfil por pozo (antes fijo en DI)
  3.6  Histograma de SE recortado en la VISTA a percentiles 1-99
  3.7  Pesos y umbral del DI configurables desde la interfaz, con reset
  3.8  Emboquillado declarado en la lista de filtros
  3.9  Armazón del reporte de justificación de variables (correlación,
       importancia, comparación de modelos, ablación de cota con LOCO-CV)

Usa fixtures sintéticas — estas correcciones son de comportamiento general,
no dependen de los datos reales de un sitio en particular.
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


# ─────────────────────────────────────────────────────────────────────────────
class FakeWell:
    def __init__(self, points, caseron=None, plan_id=""):
        self.points = points
        self.caseron = caseron
        self.plan_id = plan_id


def reset():
    gw.wells.clear()
    gw.domains.clear()
    gw.layers.clear()
    gw.attribute_exclusions.clear()
    gw.clean_filters.clear()
    gw.inicio_cut_m = 2.0
    gw.di_config["window"] = gw.DI_DEFAULTS["window"]
    gw.di_config["weights"] = dict(gw.DI_DEFAULTS["weights"])
    gw.di_threshold = gw.DI_DEFAULTS["threshold"]
    gw.rf_model = None
    gw.rf_stats = None
    gw.ucs_range["ucs_min"] = gw.UCS_CONFIG["default_min"]
    gw.ucs_range["ucs_max"] = gw.UCS_CONFIG["default_max"]


def mk_point(largo, dominio="Kfa", cota=0.0, di=0.5, entrenable=True,
             ambiguo=False, **feat):
    defaults = dict(vel=5.0, pp=5.0, pa=5.0, pd=5.0, pr=5.0, pf=5.0, se=5.0)
    defaults.update(feat)
    p = gw.MWDPoint(largo=largo, t=0.0, **defaults)
    p.dominio = dominio
    p.entrenable = entrenable
    p.ambiguo = ambiguo
    p.di = di
    p.cota = cota
    return p


def add_domain(dom_id, ucs_lab, atributo_id=None):
    gw.domains[dom_id] = {"ucs_lab": ucs_lab, "atributo_id": atributo_id or dom_id,
                          "nombre": dom_id}


# ─────────────────────────────────────────────────────────────────────────────
def t31_guardia_degenerado():
    section("3.1 — Guardia contra entrenamiento degenerado")
    reset()
    add_domain("Kfa", 120.0)
    check(gw._degenerate_training_check(np.array([120.0]*20)) is not None,
          "una sola etiqueta distinta se detecta como degenerado")
    check("variabilidad" in gw._degenerate_training_check(np.array([120.0]*20)),
          "el motivo explica la falta de variabilidad")

    pocas = np.array([120.0]*8 + [140.0]*2)
    motivo = gw._degenerate_training_check(pocas)
    check(motivo is not None, "clase con menos del mínimo de muestras se detecta")
    check("140" in motivo, "el motivo nombra la etiqueta con pocas muestras", motivo)

    ok = np.array([120.0]*10 + [140.0]*10)
    check(gw._degenerate_training_check(ok) is None,
          "dos etiquetas con muestras suficientes NO se marca degenerado")

    # train_rf end-to-end: mismo dominio, misma etiqueta -> bloqueado
    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa") for i in range(20)])
    stats = gw.train_rf()
    check("error" in stats and "degenerado" in stats["error"],
          "train_rf() rechaza un conjunto de una sola etiqueta de UCS",
          stats.get("error"))
    check(gw.rf_model is None, "no se deja un modelo entrenado sobre datos degenerados")

    # Dos dominios con etiquetas distintas y muestras suficientes -> entrena
    reset()
    add_domain("Kfa", 120.0)
    add_domain("Kfb", 140.0)
    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa") for i in range(15)])
    gw.wells["P1"] = FakeWell([mk_point(i, "Kfb") for i in range(15)])
    stats = gw.train_rf()
    check("error" not in stats, "train_rf() entrena normalmente con variabilidad suficiente",
          stats.get("error"))
    reset()


def t32_composicion_entrenamiento():
    section("3.2 — Reporte de composición del entrenamiento")
    reset()
    add_domain("Kfa", 120.0)
    gw.attribute_exclusions["Kfx"] = {}
    add_domain("Kfc", 999.0, atributo_id="Kfc")  # fuera de rango UCS por defecto

    pts = []
    pts += [mk_point(i, "Kfa", entrenable=False) for i in range(3)]          # corta emboquillado
    pts += [mk_point(10+i, None) for i in range(2)]                         # sin dominio
    pts += [mk_point(20+i, "Kfa", ambiguo=True) for i in range(2)]          # ambiguo
    pts += [mk_point(30+i, "Kfz") for i in range(2)]                        # dominio sin banda UCS
    pts += [mk_point(40+i, "Kfx") for i in range(2)]                        # atributo excluido
    pts += [mk_point(50+i, "Kfc") for i in range(2)]                        # fuera de rango UCS
    pts += [mk_point(60+i, "Kfa", di=5.0) for i in range(2)]                # DI sobre umbral
    pts += [mk_point(70+i, "Kfa") for i in range(12)]                       # sobreviven todo
    gw.wells["P0"] = FakeWell(pts)
    gw.domains["Kfx"] = {"ucs_lab": 100.0, "atributo_id": "Kfx"}

    rep = gw.training_composition_report()
    total = len(pts)
    check(rep["n_total"] == total, "n_total cuenta TODOS los puntos, filtrados o no",
          (rep["n_total"], total))
    check(rep["n_final"] == 12, "n_final refleja solo los puntos que sobreviven todo el embudo",
          rep["n_final"])
    etapas = {st["etapa"]: st for st in rep["funnel"]}
    check(etapas["entrenable"]["quedan"] == total - 3, "el corte de emboquillado se refleja en 'entrenable'")
    check("emboquillado" in etapas["entrenable"]["label"].lower(),
          "el corte de emboquillado está NOMBRADO en la etiqueta de la etapa (3.8)",
          etapas["entrenable"]["label"])
    check(etapas["con_dominio"]["perdidos"] == 2, "puntos sin dominio se contabilizan como perdidos")
    check(etapas["sin_ambiguedad"]["perdidos"] == 2, "puntos ambiguos se contabilizan como perdidos")
    check(etapas["banda_ucs"]["perdidos"] == 2, "dominios sin banda UCS se contabilizan como perdidos")
    check(etapas["no_excluido"]["perdidos"] == 2, "atributos excluidos se contabilizan como perdidos")
    check(etapas["rango_ucs"]["perdidos"] == 2, "etiquetas fuera del rango UCS se contabilizan como perdidas")
    check(etapas["roca_intacta"]["perdidos"] == 2, "puntos con DI sobre el umbral se contabilizan como perdidos")

    # La composición NUNCA puede divergir de lo que train_rf() realmente usa.
    X, y, groups, n_excl = gw._get_train_data(gw.ucs_range["ucs_min"], gw.ucs_range["ucs_max"])
    check(len(X) == rep["n_final"], "el reporte coincide EXACTAMENTE con lo que entrena train_rf")

    body = str(gw._step2())
    check("Emboquillado" in body, "el Paso 2 siempre lista el filtro de emboquillado (3.8)")
    reset()


def t33_exportaciones_distinguibles():
    section("3.3 — Exportaciones distinguibles")
    reset()
    fn_dom = gw.export_filename("dominios", "csv")
    fn_pred = gw.export_filename("predicciones", "csv")
    check(fn_dom != fn_pred, "nombres de exportación distintos según el tipo", (fn_dom, fn_pred))
    check(fn_dom.startswith("dominios_MPC_"), "el nombre incluye la base y el sitio", fn_dom)
    check(fn_dom.endswith(".csv"), "el nombre conserva la extensión")

    check(gw._export_descriptor("dominios") is None,
          "sin dominios cargados, el descriptor es None (nada que exportar)")
    add_domain("Kfa", 120.0)
    add_domain("Kfb", 140.0)
    desc = gw._export_descriptor("dominios")
    check(desc is not None and desc["n"] == 2, "el descriptor cuenta los registros a exportar",
          desc)
    check("filename" in desc and "desc" in desc, "el descriptor trae nombre de archivo y descripción")

    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa") for i in range(7)])
    desc_pred = gw._export_descriptor("predicciones")
    check(desc_pred is not None and desc_pred["n"] == 7,
          "descriptor de predicciones cuenta los puntos MWD", desc_pred)
    check(desc_pred["filename"] != desc["filename"],
          "predicciones y dominios producen archivos con nombre distinto")

    import pandas as pd
    df = pd.DataFrame({"a": [1, 2]})
    csv = gw._csv_with_metadata(df, ["línea de metadatos DI"])
    check(csv.startswith("# línea de metadatos DI"),
          "el CSV exportado antepone metadatos (parámetros DI vigentes)")
    check("a\n1\n2\n" in csv.replace("\r\n", "\n"), "el contenido del DataFrame sigue presente")
    reset()


def t34_rename_ucs_matriz():
    section("3.4 — Renombre UCS confiable → UCS matriz (sin discontinuidades)")
    import dataclasses
    names = {f.name for f in dataclasses.fields(gw.MWDPoint)}
    check("ucs_matriz" in names, "el campo se llama ucs_matriz")
    check("ucs_confiable" not in names, "el nombre viejo ya no existe en el dataclass")

    p = mk_point(0)
    p.ucs_matriz = 155.0
    d = gw._point_to_dict(p)
    check(d.get("ucs_matriz") == 155.0, "_point_to_dict serializa con la clave nueva")
    check("ucs_confiable" not in d, "_point_to_dict no emite la clave vieja")

    # Compatibilidad hacia atrás: un .gwz viejo con la clave "ucs_confiable".
    d_legacy = dict(d)
    del d_legacy["ucs_matriz"]
    d_legacy["ucs_confiable"] = 155.0
    p2 = gw._point_from_dict(d_legacy)
    check(p2.ucs_matriz == 155.0,
          "_point_from_dict migra un proyecto antiguo con la clave vieja (3.4)")

    label, *_ = gw.COLOR_FIELDS["ucs_matriz"]
    check("matriz" in label.lower() and "confiable" not in label.lower(),
          "el nombre en la interfaz (COLOR_FIELDS) usa el nuevo término", label)
    check("UCS matriz" in gw.REPORT_VARS["ucs_matriz"],
          "el nombre en el reporte por pozo usa el nuevo término")
    reset()


def t35_selector_variable_perfil():
    section("3.5 — Selector de variable en el perfil por pozo")
    reset()
    pts = [mk_point(i, "Kfa", pp=float(i), di=float(i) / 10.0) for i in range(20)]
    for p in pts:
        p.ucs_matriz = 100.0 + p.largo
    gw.wells["P0"] = FakeWell(pts)

    fig_pp = gw.build_well_report_figure("P0", hist_vars=["pp"], profile_var="pp")
    y_pp = list(fig_pp.data[0].y)
    check(y_pp == [p.pp for p in pts], "el perfil muestra la variable elegida (pp), no DI fijo")

    fig_ucs = gw.build_well_report_figure("P0", hist_vars=["pp"], profile_var="ucs_matriz")
    y_ucs = list(fig_ucs.data[0].y)
    check(y_ucs == [p.ucs_matriz for p in pts],
          "el perfil también funciona con una variable calculada (ucs_matriz)")

    fig_bad = gw.build_well_report_figure("P0", hist_vars=["pp"], profile_var="no_existe")
    check("DI" in fig_bad.layout.annotations[0].text,
          "una variable de perfil inválida cae de vuelta a DI, nunca revienta")

    fig_di = gw.build_well_report_figure("P0", hist_vars=["pp"], profile_var="di")
    check(len(fig_di.layout.shapes) == 1,
          "el umbral de discontinuidad (línea horizontal) solo aparece cuando el perfil es DI")
    check(len(fig_pp.layout.shapes) == 0,
          "con otra variable de perfil no se dibuja la línea de umbral de DI")
    reset()


def t36_histograma_se_recortado():
    """
    (B5) SE ahora vive bajo DOS recortes distintos, y este test los separa:

      · FÍSICO (SE_MAX_REPORTE=1000): un punto con ROP≈0 —el equipo lavando
        el bit, no perforando— dispara la SE a valores sin sentido. Ese
        punto se DESCARTA de verdad del histograma y del perfil: no es un
        percentil de la distribución, es un techo trazable a la física de
        la fórmula. Antes de este arreglo, un solo punto así (se vieron
        hasta 3,5e11 bar·min/m sobre datos reales) aplastaba la escala de
        todo el gráfico.
      · DE VISTA (P1–P99): sobre lo que SÍ es físicamente válido, el eje se
        recorta para que unos pocos puntos extremos —pero reales— no
        aplasten la lectura del grueso de la distribución. Este SÍ es
        solo de vista: los datos no se filtran ni se borran.
    """
    section("3.6 — SE: techo físico + recorte de vista (P1–P99)")
    reset()
    pts = [mk_point(i, "Kfa", se=5.0, pp=5.0) for i in range(50)]
    pts.append(mk_point(50, "Kfa", se=900.0, pp=900.0))     # válido, extremo de vista
    pts.append(mk_point(51, "Kfa", se=0.0001, pp=0.0001))
    pts.append(mk_point(52, "Kfa", se=5000.0, pp=5000.0))   # ROP≈0: descartado de verdad
    gw.wells["P0"] = FakeWell(pts)

    fig = gw.build_well_report_figure("P0", hist_vars=["se", "pp"], profile_var="di")
    xa_se = list(fig.select_xaxes(row=2, col=1))[0]
    xa_pp = list(fig.select_xaxes(row=2, col=2))[0]
    check(xa_se.range is not None, "la vista del histograma de SE queda recortada a un rango")
    if xa_se.range is not None:
        check(xa_se.range[0] > 0.0001 and xa_se.range[1] <= 900.0,
              "el recorte de vista opera sobre lo físicamente válido, no "
              "sobre el punto de 5000 que ya se descartó antes", xa_se.range)
    check(xa_pp.range is None,
          "una variable fuera de REPORT_HIST_CLIP_VARS (pp) NO se recorta")

    hist_trace = [t for t in fig.data if t.type == "histogram" and
                  t.name == gw.REPORT_VARS["se"]][0]
    n_se_fisicamente_valido = len([p for p in pts if p.se is not None
                                   and p.se <= gw.SE_MAX_REPORTE])
    check(len(hist_trace.x) == n_se_fisicamente_valido,
          "el histograma trae los puntos físicamente válidos (con el de "
          "5000 ya afuera), y el recorte P1-P99 sobre ESOS es solo de "
          "vista: no borra ninguno más", (len(hist_trace.x), n_se_fisicamente_valido))
    check(5000.0 not in hist_trace.x,
          "el punto con ROP≈0 no aparece ni disfrazado dentro del rango "
          "recortado: está fuera del histograma, no solo fuera del eje visible")

    titulo_se = fig.layout.annotations[1].text if len(fig.layout.annotations) > 1 else ""
    check("P1" in titulo_se and "P99" in titulo_se or "P1–P99" in titulo_se,
          "el subtítulo del histograma de SE declara el recorte de vista", titulo_se)
    check("1000" in titulo_se or f"{gw.SE_MAX_REPORTE:g}" in titulo_se,
          "y declara también el techo físico, por separado del de vista", titulo_se)
    reset()


def t37_pesos_di_configurables():
    section("3.7 — Pesos y umbral del DI configurables, con restauración")
    reset()
    check(gw.di_config_is_default(), "la configuración de DI arranca en los valores por defecto")
    resumen = gw.di_config_summary()
    check("Fernández" in resumen or "defecto" in resumen,
          "el resumen declara que está en valores por defecto", resumen)

    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa") for i in range(5)])
    ref, w, thr, wpp, wpd, wpf, wpr, wpa, msg, ok = gw.do_di_reset(1, 0)
    # do_di_reset solo restaura; probemos primero un cambio real vía do_di.
    # Quinta casilla (avance): las cinco presiones son candidatas del DI, no
    # solo cuatro — el descarte lo decide la calibración, no el formulario.
    ref, toast, opened = gw.do_di(1, "10", "1.2", "0.4", "0.3", "0.2", "0.1", "0", 0)
    check(gw.di_config["window"] == 10 and gw.di_threshold == 1.2,
          "do_di aplica ventana y umbral nuevos", (gw.di_config["window"], gw.di_threshold))
    check(gw.di_config["weights"] == {"pp": 0.4, "pd": 0.3, "pf": 0.2, "pr": 0.1, "pa": 0.0},
          "do_di aplica los cinco pesos nuevos, avance incluido", gw.di_config["weights"])
    check(not gw.di_config_is_default(), "tras el cambio, la configuración ya no es la de fábrica")

    # Valor no numérico: se rechaza SIN tocar la configuración vigente.
    prev = dict(gw.di_config["weights"]); prev_thr = gw.di_threshold
    ref2, toast2, ok2 = gw.do_di(1, "10", "abc", "0.4", "0.3", "0.2", "0.1", "0", 0)
    check(ref2 is gw.no_update if hasattr(gw, "no_update") else True,
          "un umbral inválido no dispara refresh (best-effort)")
    check(gw.di_threshold == prev_thr and gw.di_config["weights"] == prev,
          "un campo inválido NO modifica la configuración vigente (nunca default silencioso)")
    check("no es un número" in toast2 or "🚫" in toast2, "el mensaje de error es específico del campo",
          toast2)

    # Peso 0 explícito debe aceptarse (no confundirse con "vacío").
    ref3, toast3, ok3 = gw.do_di(1, "10", "1.2", "0", "0.3", "0.2", "0.1", "0", 0)
    check(gw.di_config["weights"]["pp"] == 0.0,
          "un peso 0 explícito se acepta (no se sustituye en silencio)")

    # El avance SÍ puede pesar: la quinta candidata no queda descartada de
    # antemano por el formulario, solo por la calibración.
    ref3b, toast3b, ok3b = gw.do_di(1, "10", "1.2", "0.2", "0.2", "0.1", "0.2", "0.3", 0)
    check(gw.di_config["weights"]["pa"] == 0.3,
          "un peso de avance explícito se aplica igual que los otros cuatro",
          gw.di_config["weights"])

    ref4, w4, thr4, wpp4, wpd4, wpf4, wpr4, wpa4, msg4, ok4 = gw.do_di_reset(1, 0)
    check(gw.di_config_is_default(), "do_di_reset vuelve a los valores de Fernández et al. 2023")
    check((w4, thr4, wpp4, wpd4, wpf4, wpr4, wpa4) ==
          (gw.DI_DEFAULTS["window"], gw.DI_DEFAULTS["threshold"],
           gw.DI_DEFAULTS["weights"]["pp"], gw.DI_DEFAULTS["weights"]["pd"],
           gw.DI_DEFAULTS["weights"]["pf"], gw.DI_DEFAULTS["weights"]["pr"], 0.0),
          "do_di_reset empuja los valores por defecto de vuelta a los 7 inputs "
          "de la UI, avance en 0")
    reset()


def t38_emboquillado_en_filtros():
    section("3.8 — Emboquillado declarado en la lista de filtros")
    reset()
    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa") for i in range(10)])
    gw.apply_inicio_filter(4.5)
    check(gw.inicio_cut_m == 4.5, "apply_inicio_filter fija el corte vigente")
    n_cortados = sum(1 for p in gw.wells["P0"].points if p.largo < 4.5)
    n_entrenables = sum(1 for p in gw.wells["P0"].points if p.entrenable)
    check(n_entrenables == 10 - n_cortados,
          "el corte de emboquillado se aplica realmente a los puntos")

    # recompute_filters NO debe resetear el corte a un default hardcodeado.
    gw.recompute_filters()
    check(gw.inicio_cut_m == 4.5,
          "recompute_filters conserva el corte del usuario, no lo pisa con 2.0 (regresión 3.8)")

    body = str(gw._step2())
    check(f"{4.5:g} m" in body, "el Paso 2 muestra el corte de emboquillado VIGENTE, no un default")

    # do_cut: rechazo explícito de valores inválidos/negativos, sin tocar el corte.
    ref, toast, ok = gw.do_cut(1, "-3", 0)
    check(gw.inicio_cut_m == 4.5, "un corte negativo se rechaza sin modificar inicio_cut_m", toast)
    ref, toast, ok = gw.do_cut(1, "no numérico", 0)
    check(gw.inicio_cut_m == 4.5, "un corte no numérico se rechaza sin modificar inicio_cut_m", toast)
    ref, toast, ok = gw.do_cut(1, "0", 0)
    check(gw.inicio_cut_m == 0.0,
          "un corte 0.0 explícito (desactivar el corte) SÍ se aplica — no es 'falsy'==default")
    reset()


def t39_reporte_justificacion_variables():
    section("3.9 — Armazón del reporte de justificación de variables")
    reset()

    # 3.9a — sin datos suficientes: cada sección declara el motivo, no inventa.
    corr_vacio = gw.correlation_matrix_report()
    check(corr_vacio["status"] == "sin_datos", "correlación: sin datos declara el estado, no un gráfico vacío")
    cmp_vacio = gw.model_comparison_report()
    check(cmp_vacio["status"] == "sin_datos", "comparación de modelos: sin datos declara el estado")
    abl_vacio = gw.cota_ablation_report()
    check(abl_vacio["status"] == "sin_datos", "ablación de cota: sin datos declara el estado")
    body_vacio = gw._varjust_panel_body()
    check(body_vacio is not None, "el panel se arma igual sin datos (armazón, no bloqueo)")

    # 3.9b — datos suficientes, un solo caserón: LOCO-CV declara por qué no corre.
    add_domain("Kfa", 120.0)
    gw.wells["P0"] = FakeWell([mk_point(i, "Kfa", pp=float(i % 7)) for i in range(30)])
    gw.wells["P1"] = FakeWell([mk_point(30+i, "Kfa", pp=float(i % 5)) for i in range(30)])
    gw.wells["P2"] = FakeWell([mk_point(60+i, "Kfa", pp=float(i % 3)) for i in range(30)])
    orig_resolve = gw._resolve_caseron
    gw._resolve_caseron = lambda lito: None
    try:
        abl_un_caseron = gw.cota_ablation_report()
        check(abl_un_caseron["status"] == "sin_caserones",
              "con un solo caserón (o ninguno resoluble), LOCO-CV se declara pendiente",
              abl_un_caseron.get("motivo"))
        check("segundo caserón" in abl_un_caseron["motivo"],
              "el motivo explica exactamente qué falta para poder correr la ablación")
    finally:
        gw._resolve_caseron = orig_resolve

    # 3.9b-bis — El caserón de un punto lo define su POZO, no su litología.
    # Una litología cruza varios caserones por definición (con los datos
    # reales, Bht está en los tres cargados), así que resolver el caserón
    # desde la litología devuelve None por ambigüedad y la ablación quedaba
    # declarada como "sin caserones" aunque hubiera tres. Un pozo, en cambio,
    # pertenece a exactamente un caserón.
    reset()
    add_domain("Kfa", 120.0)
    add_domain("Bht", 200.0)
    rng_b = np.random.default_rng(3)
    for cas in ("CAS_A", "CAS_B", "CAS_C"):
        for i in range(3):
            pts = [mk_point(j, "Kfa" if j % 2 else "Bht", pp=float(rng_b.uniform(1, 9)),
                            vel=float(rng_b.uniform(1, 9)))
                   for j in range(20)]
            gw.wells[f"{cas}_P{i}"] = FakeWell(pts, caseron=cas, plan_id=f"{cas}_PR01_TH_P{i}")
    check(gw.caseron_de_pozo(gw.wells["CAS_A_P0"]) == "CAS_A",
          "caseron_de_pozo() usa el caserón declarado del pozo",
          gw.caseron_de_pozo(gw.wells["CAS_A_P0"]))

    # La MISMA litología aparece en los tres caserones: resolverla por
    # litología daría None (ambigua), por pozo da los tres.
    check(gw._resolve_caseron("Bht") is None,
          "resolver por litología es ambiguo cuando cruza caserones (por eso no sirve)")
    abl = gw.cota_ablation_report()
    check(abl["status"] == "ok",
          "con 3 caserones agrupados POR POZO, la ablación sí corre", abl.get("motivo"))
    if abl["status"] == "ok":
        check(sorted(abl["caserones"]) == ["CAS_A", "CAS_B", "CAS_C"],
              "los tres caserones entran al LOCO-CV", abl["caserones"])
        check(abl["loco_sin_cota"][0] is not None,
              "LOCO-CV produce un R² real, no un motivo de omisión", abl["loco_sin_cota"])

    # 3.9c — correlación: par colineal detectado y sugerencia razonable.
    reset()
    add_domain("Kfa", 120.0)
    rng = np.random.default_rng(0)
    pts = []
    for i in range(60):
        base = float(rng.uniform(1, 10))
        p = mk_point(i, "Kfa", vel=base, pp=base * 2.0 + float(rng.normal(0, 0.01)),
                     pa=float(rng.uniform(1, 10)), pd=float(rng.uniform(1, 10)),
                     pr=float(rng.uniform(1, 10)), pf=float(rng.uniform(1, 10)),
                     se=float(rng.uniform(1, 10)))
        pts.append(p)
    gw.wells["P0"] = FakeWell(pts)
    corr = gw.correlation_matrix_report()
    check(corr["status"] == "ok", "con datos suficientes, la correlación se calcula de verdad")
    pares = {(pr["a"], pr["b"]) for pr in corr["pairs_flagged"]}
    check(("ROP", "PP") in pares or ("PP", "ROP") in pares,
          "la multicolinealidad ROP↔PP (vel≈pp/2 por construcción) se detecta",
          corr["pairs_flagged"])

    # 3.9d — comparación de modelos: <3 pozos etiquetados se declara, no se fuerza.
    cmp = gw.model_comparison_report()
    check(cmp["status"] == "sin_grupos",
          "con <3 pozos con etiqueta, la comparación de modelos declara el motivo", cmp)

    # 3.9e — con >=3 pozos, la comparación corre de verdad y compara los 5 modelos.
    gw.wells["P1"] = FakeWell([mk_point(200+i, "Kfa", vel=5.0, pp=10.0) for i in range(20)])
    gw.wells["P2"] = FakeWell([mk_point(300+i, "Kfa", vel=6.0, pp=12.0) for i in range(20)])
    cmp_ok = gw.model_comparison_report()
    check(cmp_ok["status"] == "ok", "con >=3 pozos, la comparación de modelos corre", cmp_ok)
    if cmp_ok["status"] == "ok":
        nombres = {r["modelo"] for r in cmp_ok["rows"]}
        check(nombres == set(gw.COMPARISON_MODELS),
              "se comparan los cinco modelos pedidos (Lineal/KNN/RF/HistGB/MLP control)", nombres)
    cmp_sin_se = gw.model_comparison_report(with_se=False)
    check(cmp_sin_se["status"] == "ok" and cmp_sin_se["with_se"] is False,
          "existe el modo de evaluación SIN el proxy SE")

    reset()


# ─────────────────────────────────────────────────────────────────────────────
ALL_TESTS = [
    t31_guardia_degenerado,
    t32_composicion_entrenamiento,
    t33_exportaciones_distinguibles,
    t34_rename_ucs_matriz,
    t35_selector_variable_perfil,
    t36_histograma_se_recortado,
    t37_pesos_di_configurables,
    t38_emboquillado_en_filtros,
    t39_reporte_justificacion_variables,
]


def test_p3_correcciones():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    for t in ALL_TESTS:
        t()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    for t in ALL_TESTS:
        t()

    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ P3 COMPLETO — todas las verificaciones pasaron.")
    print("=" * 72)
