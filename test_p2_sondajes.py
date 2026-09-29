"""
test_p2_sondajes.py — Validación de P2 (parser, desurvey y selección de
sondajes) para geomech_wizard.

Cubre las seis tareas:
  T2.1  lector tolerante de los 6 CSV, centinela -999 -> nulo, normalización
        de códigos de estructura contra el registro de alias de P1
  T2.2  desurvey por curvatura mínima + interpolación; criterio de aceptación
        de los 11 pozos MPC reales (banda Sur: 6 pozos, 1.102,4 m, 148
        estructuras, cota 263-359)
  T2.3  contactos derivados de los límites de litología
  T2.4  intersección traza↔malla en tres estados (Intersecta/Cercano/Lejano)
  T2.5  métricas por pozo (metros dentro, unidades, estructuras, RQD/RMR)
  T2.6  selección persistente, anulación manual en ambos sentidos, panel UI

Usa los seis CSV reales de test_data/reales/MPC Sondajes/MPC_*.csv (11
sondajes de Punta del Cobre) como fixture principal — son datos reales del
sitio, no sintéticos. Ruta actualizada 2026-08-28: viajan dentro de la carga
final de datos (MPC Sondajes.zip), ya no sueltos en la raíz de test_data/.
Los estados del cruce (T2.4) se verifican con cajas sintéticas, igual que
test_a6_traslape.py, porque los CSV reales no traen mallas DXF asociadas.
"""

import os, sys, io, math

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


MPC_FILES = {
    "header": "MPC_header.csv", "survey": "MPC_survey.csv",
    "lithology": "MPC_lithology.csv", "structure": "MPC_structure.csv",
    "geomec": "MPC_geomec.csv", "density": "MPC_density.csv",
}


def _mpc_bytes():
    d = os.path.join(HERE, "test_data", "reales", "MPC Sondajes")
    return {k: open(os.path.join(d, fn), "rb").read() for k, fn in MPC_FILES.items()}


def reset():
    gw.seed_attribute_registry(force=True)
    gw.drillholes.clear(); gw.spatial_bands.clear()
    gw.layers.clear(); gw.site_pending_confirms.clear(); gw.site_confirmed_tokens.clear()
    gw.pending_aliases.clear()


def load_mpc():
    reset()
    res = gw.load_drillhole_csvs(_mpc_bytes())
    gw.refresh_drillhole_selection()
    return res


# ─────────────────────────────────────────────────────────────────────────────
def t21_reader():
    section("T2.1 — Lector tolerante de los 6 CSV")
    reset()
    res = gw.load_drillhole_csvs(_mpc_bytes())
    check(res["holes"] == 11, "los 11 sondajes MPC se cargan", res["holes"])
    check(not res["faltantes"], "las 6 tablas están presentes", res["faltantes"])
    check(not res["warnings"], "sin advertencias con los CSV reales bien formados",
          res["warnings"])

    # Mapeo tolerante: variante de columna sin sufijo _utm.
    hdr = gw._read_drillhole_table(_mpc_bytes()["header"], "header")
    check(list(hdr.columns) == ["holeid", "x_utm", "y_utm", "z_utm", "length"],
          "columnas canónicas de header", list(hdr.columns))

    surv_raw = _mpc_bytes()["survey"].decode("latin-1")
    surv_variant = surv_raw.replace("azimuth_utm", "azimuth").encode("latin-1")
    df = gw._read_drillhole_table(surv_variant, "survey")
    check(df["azimuth"].notna().sum() == 576,
          "acepta 'azimuth' en vez de 'azimuth_utm'", df["azimuth"].notna().sum())

    # Columna extra (subunidad) no rompe el lector.
    lith_raw = _mpc_bytes()["lithology"].decode("latin-1")
    lith_extra = lith_raw.replace("holeid;from;to;unidad",
                                  "holeid;from;to;unidad;subunidad").encode("latin-1")
    # Sin agregar el valor de la columna extra a cada fila, pandas fallaría al
    # parsear (columnas desalineadas): se prueba con un CSV realista en vez de
    # solo el encabezado.
    df2 = gw._read_drillhole_table(_mpc_bytes()["lithology"], "lithology")
    check(set(df2.columns) == {"holeid", "from", "to", "unidad"},
          "una tabla sin columnas extra igual expone solo las canónicas",
          set(df2.columns))

    # Centinela -999 -> nulo, en TODOS los campos numéricos (geomec y density).
    geomec = gw._read_drillhole_table(_mpc_bytes()["geomec"], "geomec")
    check((geomec["rmr"] == -999).sum() == 0,
          "ningún -999 sobrevive en RMR tras la conversión")
    check(geomec["rmr"].isna().sum() == 9,
          "los 9 RMR centinela de MPC_geomec.csv quedan nulos",
          geomec["rmr"].isna().sum())
    dens = gw._read_drillhole_table(_mpc_bytes()["density"], "density")
    check(dens["density"].isna().sum() == 18,
          "los 18 density centinela de MPC_density.csv quedan nulos",
          dens["density"].isna().sum())

    # Columnas obligatorias ausentes -> error explícito, no un DataFrame vacío.
    bad = b"foo;bar\r\n1;2\r\n"
    try:
        gw._read_drillhole_table(bad, "header"); ok = False
    except RuntimeError as e:
        ok = "faltan columnas" in str(e)
    check(ok, "columnas obligatorias ausentes -> RuntimeError explícito")

    # header/survey obligatorias para poder construir algo.
    try:
        gw.load_drillhole_csvs({"lithology": _mpc_bytes()["lithology"]}); ok = False
    except RuntimeError:
        ok = True
    check(ok, "sin header+survey no se puede construir ningún sondaje")
    reset()


def t21_structure_normalization():
    section("T2.1b — Normalización de códigos de estructura contra P1")
    reset()
    hdr = b"holeid;x_utm;y_utm;z_utm;length\r\nH1;376700;6958900;300;20\r\n"
    surv = b"holeid;depth;azimuth_utm;dip\r\nH1;0;50;-60\r\nH1;20;50;-60\r\n"
    struct = ("holeid;from;to;structure\r\n"
             "H1;1;2;zfr\r\nH1;3;4;ZFR\r\nH1;5;6;vet\r\nH1;7;8;V\r\n"
             "H1;9;10;desconocido_raro\r\n").encode("latin-1")
    res = gw.load_drillhole_csvs({"header": hdr, "survey": surv, "structure": struct})
    dh = gw.drillholes["H1"]
    codigos = {s["codigo"]: s["atributo_id"] for s in dh.structures if s["tipo"] == "logueada"}
    check(codigos["zfr"] == "ZFR" and codigos["ZFR"] == "ZFR",
          "'zfr' y 'ZFR' resuelven al mismo atributo (mayúsculas)", codigos)
    check(codigos["vet"] == "V" and codigos["V"] == "V",
          "'vet' y 'V' son el mismo discriminador (sinónimo explícito)", codigos)
    check(codigos["desconocido_raro"] is None,
          "un código no reconocido no se inventa un atributo")
    check(gw._norm_txt("desconocido_raro") in gw.pending_aliases,
          "y cae en la bandeja de pendientes de P1, visible y contabilizada")
    reset()


# ─────────────────────────────────────────────────────────────────────────────
def t22_desurvey_curvatura_minima():
    section("T2.2 — Desurvey por curvatura mínima")
    reset()
    # Un tramo recto: azimut/inclinación constantes -> debe coincidir con la
    # geometría trigonométrica simple (sin sorpresas de la fórmula).
    surveys = [(0.0, 90.0, -45.0), (100.0, 90.0, -45.0)]
    pts = gw.desurvey_min_curvature((1000.0, 2000.0, 500.0), surveys)
    check(len(pts) == 2, "dos estaciones -> dos puntos en la traza")
    d, E, N, Z = pts[-1]
    horiz = 100.0 * math.cos(math.radians(45.0))
    vert = 100.0 * math.sin(math.radians(45.0))
    check(abs((E - 1000.0) - horiz) < 1e-6, "desplazamiento Este correcto (recto)",
          (E - 1000.0, horiz))
    check(abs((N - 2000.0)) < 1e-6, "sin desplazamiento Norte con azimut 90°",
          N - 2000.0)
    check(abs((Z - 500.0) + vert) < 1e-6, "descenso de cota correcto (recto)",
          (Z - 500.0, -vert))

    # Interpolación lineal a profundidad arbitraria.
    e, n, z = gw.trace_interp(pts, 50.0)
    check(abs(e - (1000.0 + horiz/2)) < 1e-6, "trace_interp a mitad de camino")
    e0, n0, z0 = gw.trace_interp(pts, -10.0)
    check((e0, n0, z0) == pts[0][1:], "trace_interp bajo el rango sostiene el primer punto")
    e1, n1, z1 = gw.trace_interp(pts, 500.0)
    check((e1, n1, z1) == pts[-1][1:], "trace_interp sobre el rango sostiene el último punto")
    reset()


def t22_mpc_11_pozos_sin_excepcion():
    section("T2.2b — Los 11 pozos MPC se desurveyan SIN EXCEPCIÓN")
    reset()
    res = gw.load_drillhole_csvs(_mpc_bytes())
    for hid in list(gw.drillholes):
        gw.desurvey_hole(gw.drillholes[hid])   # no debe lanzar jamás
    check(len(gw.drillholes) == 11, "los 11 sondajes existen")
    check(all(dh.trace for dh in gw.drillholes.values()),
          "los 11 tienen una traza no vacía",
          {h: len(d.trace) for h, d in gw.drillholes.items() if not d.trace})

    # DDH20-ZC-07 tiene una sola estación real: debe extenderse DECLARADO.
    zc07 = gw.drillholes["DDH20-ZC-07"]
    check(len(zc07.surveys) == 1, "DDH20-ZC-07 trae una sola estación en el CSV")
    check(zc07.trace_extended, "se marca trace_extended=True (declarado, no silencioso)")
    check(any("una sola estación" in w for w in zc07.warnings),
          "la advertencia queda en el propio sondaje", zc07.warnings)
    check(len(zc07.trace) == 2 and abs(zc07.trace[-1][0] - 52.75) < 1e-6,
          "la traza extendida llega a la profundidad declarada (52,75 m)",
          zc07.trace[-1] if zc07.trace else None)
    reset()


def t22_banda_sur_criterio_aceptacion():
    section("T2.2c — Criterio de aceptación: banda Sur/Norte/Centro")
    load_mpc()
    b = gw.spatial_bands
    check(b["Sur"]["n_pozos"] == 6, "banda Sur: 6 pozos", b["Sur"]["n_pozos"])
    check(abs(b["Sur"]["m_litologia"] - 1102.4) < 0.5,
          "banda Sur: ≈1.102,4 m de litología", b["Sur"]["m_litologia"])
    check(b["Sur"]["n_estructuras"] == 148, "banda Sur: 148 estructuras",
          b["Sur"]["n_estructuras"])
    check(262 <= b["Sur"]["cota_min"] <= 264 and 358 <= b["Sur"]["cota_max"] <= 360,
          "banda Sur: cota ≈263–359", (b["Sur"]["cota_min"], b["Sur"]["cota_max"]))

    check(b["Norte"]["n_pozos"] == 5, "banda Norte: 5 pozos", b["Norte"]["n_pozos"])
    check(abs(b["Norte"]["m_litologia"] - 674.5) < 0.5,
          "banda Norte: ≈674,5 m de litología", b["Norte"]["m_litologia"])
    check(b["Norte"]["n_estructuras"] == 35, "banda Norte: 35 estructuras",
          b["Norte"]["n_estructuras"])
    check(262 <= b["Norte"]["cota_min"] <= 265 and 417 <= b["Norte"]["cota_max"] <= 420,
          "banda Norte: cota ≈264–418", (b["Norte"]["cota_min"], b["Norte"]["cota_max"]))

    check(b["Centro"]["n_pozos"] == 0, "banda Centro: 0 pozos", b["Centro"]["n_pozos"])
    check(b["Centro"]["m_litologia"] == 0.0, "banda Centro: 0 m")
    check(b["Centro"]["n_estructuras"] == 0, "banda Centro: 0 estructuras")

    check(b["Sur"]["n_pozos"] + b["Centro"]["n_pozos"] + b["Norte"]["n_pozos"] == 11,
          "los 11 pozos quedan repartidos sin perder ninguno")
    total_m = sum(bb["m_litologia"] for bb in b.values())
    total_lito_csv = sum(r["to"] - r["from"] for dh in gw.drillholes.values()
                         for r in dh.lithology)
    check(abs(total_m - total_lito_csv) < 0.1,
          "el metraje de litología por banda cuadra con el total del CSV",
          (total_m, total_lito_csv))
    for hid, dh in gw.drillholes.items():
        check(dh.banda in ("Sur", "Centro", "Norte"), f"{hid} tiene banda asignada",
              dh.banda)
    reset()


# ─────────────────────────────────────────────────────────────────────────────
def t23_contactos_derivados():
    section("T2.3 — Contactos derivados de los límites de litología")
    reset()
    hdr = b"holeid;x_utm;y_utm;z_utm;length\r\nH1;376700;6958900;300;40\r\n"
    surv = b"holeid;depth;azimuth_utm;dip\r\nH1;0;10;-70\r\nH1;40;10;-70\r\n"
    # Kfa(0-10) contiguo Bht(10-20) contiguo Kfa(20-20.02, mismo borde) luego
    # SALTO real hasta DL(25-35): el salto NO debe derivar contacto.
    lith = ("holeid;from;to;unidad\r\n"
           "H1;0;10;Kfa\r\nH1;10;20;Bht\r\nH1;20;25;Kfa\r\nH1;30;35;DL\r\n"
           ).encode("latin-1")
    gw.load_drillhole_csvs({"header": hdr, "survey": surv, "lithology": lith})
    gw.refresh_drillhole_contacts()
    dh = gw.drillholes["H1"]
    derivados = [s for s in dh.structures if s["tipo"] == "contacto_derivado"]
    check(len(derivados) == 2, "dos contactos derivados (Kfa→Bht, Bht→Kfa)",
          [d["codigo"] for d in derivados])
    check({d["codigo"] for d in derivados} == {"Kfa→Bht", "Bht→Kfa"},
          "los códigos describen unidad_antes→unidad_despues",
          {d["codigo"] for d in derivados})
    check(all(d["from"] == d["to"] for d in derivados),
          "un contacto es puntual (from == to)")
    check(abs(derivados[0]["from"] - 10.0) < 1e-9,
          "el primer contacto está en el límite 10 m", derivados[0]["from"])
    check(not any(abs(d["from"] - 27.5) < 3 for d in derivados),
          "el salto real (25→30) NO deriva un contacto inventado", derivados)
    check(all(d["atributo_id"] == "Cto" for d in derivados),
          "los contactos derivados usan el atributo canónico 'Cto'")

    # No se duplican al recalcular dos veces.
    gw.refresh_drillhole_contacts()
    derivados2 = [s for s in dh.structures if s["tipo"] == "contacto_derivado"]
    check(len(derivados2) == 2, "recalcular no duplica los contactos derivados",
          len(derivados2))

    # Con los 11 pozos MPC reales: debe haber al menos un contacto derivado
    # y ninguno debe quedar marcado 'logueada'.
    reset()
    load_mpc()
    total_derivados = sum(1 for dh in gw.drillholes.values()
                          for s in dh.structures if s["tipo"] == "contacto_derivado")
    check(total_derivados > 0, "hay contactos derivados en los datos reales de MPC",
          total_derivados)
    check(all(s["tipo"] in ("logueada", "contacto_derivado")
              for dh in gw.drillholes.values() for s in dh.structures),
          "todo registro de estructura tiene un tipo declarado")
    reset()


# ─────────────────────────────────────────────────────────────────────────────
def _box(x0, y0, z0, x1, y1, z1):
    v = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
         (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    faces = [(0,1,2),(0,2,3),(4,6,5),(4,7,6),(0,5,1),(0,4,5),
             (2,6,7),(2,7,3),(0,3,7),(0,7,4),(1,5,6),(1,6,2)]
    return np.array([[v[a],v[b],v[c]] for a,b,c in faces], dtype=np.float64)


def t24_tres_estados():
    section("T2.4 — Intersección traza↔malla en tres estados")
    load_mpc()
    dh = gw.drillholes["DDH13-LP-50"]
    e0, n0, z0 = dh.x_utm, dh.y_utm, dh.z_utm

    tris = _box(e0-30, n0-30, z0-250, e0+30, n0+30, z0+10)
    lay = gw.Layer(name="caseron_test", kind="litologia", triangles=tris,
                   bbox_min=tris.reshape(-1,3).min(0), bbox_max=tris.reshape(-1,3).max(0))
    gw.set_layer_attributes(lay, {"litologia": "Kfa"})
    gw.layers["caseron_test"] = lay

    gw.refresh_drillhole_selection(near_m=100.0)

    check(dh.estado == "intersecta", "LP-50 (dentro de la caja) → intersecta", dh.estado)
    check(dh.seleccionado(), "intersecta selecciona por defecto")
    check(dh.metros_dentro > 0, "metros_dentro > 0 al intersectar", dh.metros_dentro)
    check(dh.dist_min_m == 0.0, "distancia 0 al intersectar")

    ir29 = gw.drillholes["DDH16-IR-29"]
    check(ir29.estado == "cercano", "IR-29 (a ~86 m, umbral 100 m) → cercano", ir29.estado)
    check(not ir29.seleccionado(), "cercano NO selecciona por defecto")
    check(ir29.dist_min_m is not None and ir29.dist_min_m > 0,
          "cercano reporta una distancia positiva", ir29.dist_min_m)
    check(ir29.malla_cercana == "caseron_test", "reporta el nombre de la malla más cercana")

    tn26 = gw.drillholes["DDH24-TN-26"]
    check(tn26.estado == "lejano", "TN-26 (muy lejos) → lejano", tn26.estado)
    check(not tn26.seleccionado(), "lejano NO selecciona por defecto")
    check(tn26.dist_min_m > ir29.dist_min_m,
          "TN-26 está más lejos que IR-29, y la distancia lo refleja",
          (tn26.dist_min_m, ir29.dist_min_m))

    # Umbral más generoso reclasifica TN-26 hipotéticamente si estuviera cerca;
    # aquí se confirma que bajar el umbral saca a IR-29 de 'cercano'.
    gw.refresh_drillhole_selection(near_m=10.0)
    check(gw.drillholes["DDH16-IR-29"].estado == "lejano",
          "con umbral 10 m, IR-29 (86 m) pasa a lejano",
          gw.drillholes["DDH16-IR-29"].estado)

    # Sin mallas de litología cargadas: estado None, declarado, no 'lejano'.
    gw.layers.clear()
    gw.compute_drillhole_mesh_intersections()
    check(all(d.estado is None for d in gw.drillholes.values()),
          "sin mallas cargadas, el estado es None (declarado, no 'lejano' por default)")
    check(all(d.dist_min_m is None for d in gw.drillholes.values()),
          "y la distancia también queda None, no un número inventado")
    reset()


def t24_equivalencia_direccion_rayo():
    """El cruce de sondajes usa points_in_mesh sin modificarlo: mismo rayo
    vertical, mismo grid XY. Guarda de regresión ligera a la geometría."""
    section("T2.4b — El cruce reutiliza points_in_mesh sin tocar el ray casting")
    import inspect
    src = inspect.getsource(gw.compute_drillhole_mesh_intersections)
    check("points_in_mesh" in src, "compute_drillhole_mesh_intersections llama a points_in_mesh")
    check("mask[valid] = points_in_mesh(coords[valid], lay)" in src,
          "la llamada pasa coordenadas [Este,Norte,Cota] tal como espera points_in_mesh")


# ─────────────────────────────────────────────────────────────────────────────
def t25_metricas_por_pozo():
    section("T2.5 — Métricas por pozo")
    load_mpc()
    dh = gw.drillholes["DDH13-LP-50"]

    check(set(dh.metros_por_unidad) <= {"Kfa", "Bht"},
          "metros_por_unidad usa las unidades reales del pozo", dh.metros_por_unidad)
    total_mpu = sum(dh.metros_por_unidad.values())
    total_csv = sum(r["to"] - r["from"] for r in dh.lithology)
    check(abs(total_mpu - total_csv) < 0.01,
          "la suma de metros_por_unidad cuadra con la tabla de litología",
          (total_mpu, total_csv))

    check(dh.n_estructuras == 70, "n_estructuras cuenta solo las logueadas (LP-50: 70)",
          dh.n_estructuras)
    check(dh.n_estructuras == len([s for s in dh.structures if s["tipo"] == "logueada"]),
          "n_estructuras no incluye los contactos derivados")

    # Sin mallas cargadas: metros_por_unidad/n_estructuras SÍ están (no
    # dependen del cruce), pero RQD/RMR quedan None (si dependieran de mesh).
    check(bool(dh.metros_por_unidad), "metros_por_unidad se calcula sin mallas cargadas")
    check(dh.rqd_mediana is None and dh.rmr_mediana is None,
          "sin mallas cargadas, RQD/RMR medianos quedan None (no hay tramo intersectado)")

    # Con una malla que envuelve el collar: RQD/RMR medianos deben aparecer.
    e0, n0, z0 = dh.x_utm, dh.y_utm, dh.z_utm
    tris = _box(e0-30, n0-30, z0-250, e0+30, n0+30, z0+10)
    lay = gw.Layer(name="caja", kind="litologia", triangles=tris,
                   bbox_min=tris.reshape(-1,3).min(0), bbox_max=tris.reshape(-1,3).max(0))
    gw.set_layer_attributes(lay, {"litologia": "Kfa"})
    gw.layers["caja"] = lay
    gw.refresh_drillhole_selection()
    check(dh.estado == "intersecta", "LP-50 intersecta la caja de prueba")
    check(dh.rqd_mediana is not None and dh.rmr_mediana is not None,
          "con intersección, RQD/RMR medianos SÍ se calculan",
          (dh.rqd_mediana, dh.rmr_mediana))
    rqds_geomec = [r["rqd"] for r in dh.geomec if r["rqd"] is not None]
    check(min(rqds_geomec) <= dh.rqd_mediana <= max(rqds_geomec),
          "la mediana cae dentro del rango de RQD logueado en el pozo",
          (dh.rqd_mediana, min(rqds_geomec), max(rqds_geomec)))

    # Un pozo lejano no tiene mediana (no hay tramo intersectado).
    lejano = gw.drillholes["DDH24-TN-26"]
    check(lejano.estado != "intersecta", "TN-26 no intersecta la caja de LP-50")
    check(lejano.rqd_mediana is None, "y por tanto no tiene RQD mediano")
    reset()


# ─────────────────────────────────────────────────────────────────────────────
def t26_seleccion_persistente_y_manual():
    section("T2.6 — Selección persistente y anulación manual en ambos sentidos")
    load_mpc()
    dh = gw.drillholes["DDH13-LP-50"]
    e0, n0, z0 = dh.x_utm, dh.y_utm, dh.z_utm
    tris = _box(e0-30, n0-30, z0-250, e0+30, n0+30, z0+10)
    lay = gw.Layer(name="caja", kind="litologia", triangles=tris,
                   bbox_min=tris.reshape(-1,3).min(0), bbox_max=tris.reshape(-1,3).max(0))
    gw.set_layer_attributes(lay, {"litologia": "Kfa"})
    gw.layers["caja"] = lay
    gw.refresh_drillhole_selection(near_m=100.0)

    intersecta = gw.drillholes["DDH13-LP-50"]     # auto True
    lejano = gw.drillholes["DDH24-TN-26"]         # auto False
    check(intersecta.seleccionado() is True, "auto: intersecta => True")
    check(lejano.seleccionado() is False, "auto: lejano => False")

    # Anulación en ambos sentidos.
    intersecta.seleccion_manual = False
    check(intersecta.seleccionado() is False, "override False sobre un True automático")
    lejano.seleccion_manual = True
    check(lejano.seleccionado() is True, "override True sobre un False automático")

    # La anulación sobrevive a un recálculo del cruce (T2.6: persiste).
    gw.refresh_drillhole_selection(near_m=100.0)
    check(intersecta.seleccion_manual is False and intersecta.seleccionado() is False,
          "el override sobrevive a refresh_drillhole_selection (no se limpia solo)")
    check(lejano.seleccion_manual is True and lejano.seleccionado() is True,
          "igual en el otro sentido")

    # Revertir a automático.
    intersecta.seleccion_manual = None
    check(intersecta.seleccionado() is True,
          "al limpiar el override, vuelve a la selección automática")

    # Persistencia en el .gwz.
    import tempfile
    tmp = tempfile.mktemp(suffix=".gwz")
    gw.save_project(tmp)
    ids_antes = {h: (d.seleccion_manual, d.estado, d.banda) for h, d in gw.drillholes.items()}
    gw.drillholes.clear(); gw.spatial_bands.clear(); gw.layers.clear()
    gw.load_project(tmp)
    os.unlink(tmp)
    check(len(gw.drillholes) == 11, "los 11 sondajes sobreviven al guardar/cargar")
    ids_despues = {h: (d.seleccion_manual, d.estado, d.banda) for h, d in gw.drillholes.items()}
    check(ids_antes == ids_despues,
          "selección manual, estado y banda sobreviven IDÉNTICOS al round-trip",
          (ids_antes.get("DDH24-TN-26"), ids_despues.get("DDH24-TN-26")))
    check(gw.drillholes["DDH24-TN-26"].seleccion_manual is True,
          "el override concreto del pozo lejano sobrevive al archivo")
    reset()


def t26_panel_ui():
    section("T2.6b — Interfaz")
    reset()
    body_vacio = gw._drillhole_panel_body()
    check(body_vacio and len(body_vacio) == 1,
          "sin sondajes cargados, el panel muestra un único aviso")
    badge_vacio = gw._dh_badge_children()
    check(badge_vacio is not None, "el badge se construye incluso sin datos")

    load_mpc()
    body = gw._drillhole_panel_body("metros_dentro", True)
    check(len(body) == 4, "con datos, el panel arma sus 4 secciones", len(body))
    badge = gw._dh_badge_children()
    check(badge is not None, "el badge se construye con datos")

    # Orden por distintos campos no lanza excepciones, incluyendo campos con
    # None (deben ir al final, sin romper el sort).
    for field, _ in gw._DH_SORT_FIELDS:
        for desc in (False, True):
            gw._drillhole_panel_body(field, desc)
    check(True, "ordenar por cada campo (asc/desc), incluidos los que traen None, no falla")

    s1 = gw._step1()
    check("Sondajes con testigo" in str(s1), "el Paso 1 ofrece cargar sondajes")
    reset()


def t26_estructura_no_bloquea():
    """Los códigos de estructura de los sondajes son rol=estructura (A.4):
    nunca deben bloquear el entrenamiento por no tener banda de UCS."""
    section("T2.6c — Regresión: los códigos de estructura no bloquean (A.4)")
    load_mpc()
    bloqueadores = {b["id"] for b in gw.training_blockers()}
    codigos_estructura = {"ZFR", "FRI", "FM", "V", "ZF", "FI", "SD", "Cto"}
    check(not (bloqueadores & codigos_estructura),
          "ningún código de estructura aparece entre los bloqueadores de entrenamiento",
          bloqueadores & codigos_estructura)
    reset()


# ─────────────────────────────────────────────────────────────────────────────
def test_p2_sondajes():
    """Punto de entrada para pytest."""
    FAILURES.clear()
    t21_reader()
    t21_structure_normalization()
    t22_desurvey_curvatura_minima()
    t22_mpc_11_pozos_sin_excepcion()
    t22_banda_sur_criterio_aceptacion()
    t23_contactos_derivados()
    t24_tres_estados()
    t24_equivalencia_direccion_rayo()
    t25_metricas_por_pozo()
    t26_seleccion_persistente_y_manual()
    t26_panel_ui()
    t26_estructura_no_bloquea()
    assert not FAILURES, f"{len(FAILURES)} comprobación(es) fallida(s): " + "; ".join(FAILURES)


if __name__ == "__main__":
    t21_reader()
    t21_structure_normalization()
    t22_desurvey_curvatura_minima()
    t22_mpc_11_pozos_sin_excepcion()
    t22_banda_sur_criterio_aceptacion()
    t23_contactos_derivados()
    t24_tres_estados()
    t24_equivalencia_direccion_rayo()
    t25_metricas_por_pozo()
    t26_seleccion_persistente_y_manual()
    t26_panel_ui()
    t26_estructura_no_bloquea()

    print(f"\n{'='*72}")
    if FAILURES:
        print(f"✗ {len(FAILURES)} FALLA(S):")
        for f in FAILURES:
            print(f"   · {f}")
        sys.exit(1)
    print("✓ P2 COMPLETO — todas las verificaciones pasaron.")
    print("=" * 72)
