"""
cargar_caserones.py — Carga masiva de los caserones reales de Punta del Cobre
desde test_data/reales/, preparatoria de la sesión 5 (entrenamiento + LOCO-CV).

No es parte de la aplicación: es el guion de ingesta que toma los ~1.900 XML
IREDES y las mallas DXF entregadas por Pucobre, los cruza, y deja el estado
listo (o un .gwz guardado) para entrenar. Se ejecuta desde la raíz del repo.

    python3 cargar_caserones.py --caseron PCS_1043 --caseron PCC_0042
    python3 cargar_caserones.py --todos --guardar proyecto.gwz

Cada caserón se resuelve así (datos finales para la tesis, subidos 2026-08-28):
  · DQ/MW  test_data/reales/MWD {SITIO} {número}/{DQ|MW}{caseron}_*.xml
           (mezclados en la misma carpeta; se separan por el prefijo del
           nombre, DQ se fusiona entre revisiones igual que antes)
  · DXF    test_data/reales/Capas {caseron}/*.dxf  (PLANA — sin subcarpeta
           "Litología"/"Estructuras": el rol de cada malla ya NO se adivina
           por carpeta ni por nombre, se resuelve por el vocabulario
           importado desde test_data/vocabulario_MPC_*.json, que trae un
           alias `dxf_layer` exacto para cada malla de los cuatro caserones)

El vocabulario y el perfil de faena de esta carga viven en:
  · test_data/vocabulario_MPC_*.json   (anclas de UCS + 37 alias por malla)
  · test_data/perfil_faena_MPC_*.json  (parámetros de operación de MPC)
Se importan al inicio de `main()` — YA NO se siembra `seed_attribute_registry()`
con la tabla de Karzulovic hardcodeada: el JSON exportado es la fuente única
para esta carga, y sus anclas de UCS pueden diferir de las de esa tabla (el
autor las refinó trabajando con la app).
"""

import os, sys, glob, time, argparse, zipfile
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geomech_wizard as gw

REALES = os.path.join(HERE, "test_data", "reales")
VOCABULARIO = os.path.join(HERE, "test_data", "vocabulario_MPC_20260828_1302.json")
PERFIL = os.path.join(HERE, "test_data", "perfil_faena_MPC_20260828_1236.json")

# Los cuatro caserones del plan (CLAUDE.md). El rol entrena/prueba NO se fija
# aquí: es un parámetro de ejecución de la sesión 5, no una constante.
CASERONES = ["PCS_1043", "PCC_0042", "PCS_1059", "PCC_1541"]


def _prefijo_sitio(caseron: str) -> str:
    return caseron.split("_")[0]          # PCS_1043 -> PCS


ZIPS_FINALES = [
    "Capas PCC_0042.zip", "Capas PCC_1541.zip",
    "Capas PCS_1043.zip", "Capas PCS_1059.zip",
    "MPC Sondajes.zip", "MWD MPC.zip",
]


def asegurar_datos_extraidos(verbose=True) -> bool:
    """
    Extrae los seis zips finales a test_data/reales/ si no están sueltos
    todavía. `test_data/reales/` está en .gitignore a propósito —son cientos
    de MB de DXF/XML sueltos, y el repo versiona solo los zips (~75 MB
    comprimidos)—, así que un clon limpio NO trae la carpeta y este paso es
    lo único que la repone. Sin él, `descubrir_archivos()` no encuentra nada
    y cada caserón se ve "vacío" sin que quede claro por qué.
    """
    base = os.path.join(HERE, "test_data")
    if os.path.isdir(REALES) and any(
            os.path.isdir(os.path.join(REALES, n)) for n in
            ("Capas PCC_0042", "MWD PCC 0042", "MPC Sondajes")):
        return True
    faltan = [z for z in ZIPS_FINALES if not os.path.exists(os.path.join(base, z))]
    if faltan:
        print(f"  ⛔ Faltan zips de datos en test_data/: {', '.join(faltan)}")
        return False
    if verbose:
        print(f"  test_data/reales/ vacío o incompleto: extrayendo los "
              f"{len(ZIPS_FINALES)} zips finales…")
    os.makedirs(REALES, exist_ok=True)
    for z in ZIPS_FINALES:
        with zipfile.ZipFile(os.path.join(base, z)) as zf:
            zf.extractall(REALES)
    # "MWD MPC.zip" trae una carpeta contenedora extra ("MWD MPC/") con las
    # cuatro carpetas por caserón adentro; el resto de los zips no la traen.
    # Se sube un nivel para que quede "reales/MWD {SITIO} {número}/", que es
    # lo que _carpeta_mwd() espera, y se descarta el contenedor vacío.
    contenedor = os.path.join(REALES, "MWD MPC")
    if os.path.isdir(contenedor):
        for nombre in os.listdir(contenedor):
            destino = os.path.join(REALES, nombre)
            if not os.path.exists(destino):
                os.rename(os.path.join(contenedor, nombre), destino)
        if not os.listdir(contenedor):
            os.rmdir(contenedor)
    return True


def _carpeta_mwd(caseron: str) -> str:
    """'PCC_0042' -> 'MWD PCC 0042', el nombre de carpeta que trae el zip."""
    sitio = _prefijo_sitio(caseron)
    numero = caseron.split("_", 1)[1]
    return f"{REALES}/MWD {sitio} {numero}"


def descubrir_archivos(caseron: str) -> Dict[str, List[str]]:
    """Rutas de DQ, MW y mallas de un caserón, sin leer nada todavía."""
    carpeta = _carpeta_mwd(caseron)
    dq = sorted(p for p in glob.glob(f"{carpeta}/*.xml")
                if os.path.basename(p).startswith(f"DQ{caseron}_"))
    mw = sorted(p for p in glob.glob(f"{carpeta}/*.xml")
                if os.path.basename(p).startswith(f"MW{caseron}_"))
    capas = sorted(glob.glob(f"{REALES}/Capas {caseron}/**/*.dxf", recursive=True))
    # .dwg: ezdxf no los lee. Se listan aparte para poder DECLARAR que el
    # caserón queda incompleto, en vez de cargarlo a medias en silencio.
    dwg = sorted(glob.glob(f"{REALES}/Capas {caseron}/**/*.dwg", recursive=True))
    return {"dq": dq, "mw": mw, "capas": capas, "dwg": dwg}


def _rol_de_ruta(path: str) -> str:
    """
    Rol de RESPALDO cuando la malla no tiene alias en el vocabulario. La
    carga final (2026-08-28) viene en carpeta plana —ya no hay subcarpeta
    "Litología"/"Estructuras" que declare el rol—, así que en la práctica el
    rol real lo pone `resolve_or_note(name, "dxf_layer")` en `cargar_capas()`
    contra el vocabulario importado; esto solo cubre una malla nueva sin
    alias todavía.
    """
    low = gw._norm_txt(path)
    if "estructura" in low: return "estructura"
    if "litolog" in low:    return "litologia"
    return gw.guess_kind(os.path.basename(path))


def cargar_capas(caseron: str, rutas: List[str], verbose=True) -> Dict:
    """Parsea las mallas del caserón y las registra como Layer con su rol."""
    t0 = time.time()
    ok, err = 0, []
    for p in rutas:
        fname = os.path.basename(p)
        name = os.path.splitext(fname)[0]
        try:
            tris, _ = gw.parse_dxf_cached(open(p, "rb").read(), fname)
        except Exception as e:
            err.append((fname, str(e)[:90])); continue
        bmin = tris.reshape(-1, 3).min(0); bmax = tris.reshape(-1, 3).max(0)
        # (T1.1) El guardián de sitio decide por COORDENADAS, no por el
        # nombre del archivo ni por la carpeta de la que vino.
        v = gw.site_guard(este=(bmin[0]+bmax[0])/2, norte=(bmin[1]+bmax[1])/2,
                          etiqueta=name, tipo="malla DXF", token=f"dxf:{caseron}:{name}")
        if not v["ok"]:
            err.append((fname, "fuera del sitio activo")); continue
        rol = _rol_de_ruta(p)
        # Una misma litología aparece en varios caserones (Bht.dxf está en
        # tres): la clave de capa lleva el caserón para que no se pisen.
        key = f"{caseron}:{name}"
        lay = gw.Layer(name=key, kind=rol, triangles=tris, bbox_min=bmin, bbox_max=bmax)
        lay.caseron = caseron
        m = gw.resolve_or_note(name, "dxf_layer")
        if m: gw.set_layer_attributes(lay, m)
        else: lay.kind = rol
        # Lavas Superiores vs Inferiores: Pucobre entrega ambas con el mismo
        # nombre de malla, así que la resolución por nombre no las distingue.
        # Diferenciarlas es conocimiento de quien configura — se asigna a
        # mano, por capa, en el árbol de vocabulario, no acá.
        gw.layers[key] = lay
        ok += 1
        if verbose:
            attr = ",".join(f"{k}={v}" for k, v in (lay.atributos or {}).items()) or "SIN VOCABULARIO"
            # lay.kind, no `rol`: `rol` es el respaldo adivinado ANTES de
            # resolver el vocabulario — mostrarlo aquí es lo mismo default
            # silencioso que el proyecto prohíbe, solo que en el log en vez
            # del dato. set_layer_attributes() ya corrigió lay.kind si el
            # vocabulario trajo un rol distinto (ej. FM2_0042 "adivinado"
            # litología, corregido a estructura por el alias).
            print(f"     {name:14s} {len(tris):7,d} tris  {lay.kind:10s} {attr}".replace(",", "."))
    return {"ok": ok, "errores": err, "t": round(time.time()-t0, 1)}


def cargar_xml(caseron: str, dq_paths: List[str], mw_paths: List[str],
               verbose=True) -> Dict:
    """Parsea DQ (fusionando revisiones) + MW, y coloca los pozos."""
    t0 = time.time()
    dq_list = []
    for p in dq_paths:
        try: dq_list.append(gw.parse_dq(p, os.path.basename(p)))
        except Exception: pass
    dq_results, dq_rep = gw.merge_dq_siblings(dq_list)

    mw_by_hole, n_pts, err_mw = {}, 0, 0
    for p in mw_paths:
        try:
            mw = gw.parse_mw(p, os.path.basename(p))
        except Exception:
            err_mw += 1; continue
        if not mw["puntos"]: continue
        n_pts += len(mw["puntos"])
        mw_by_hole.setdefault(f"{mw['plan_id']}_H{mw['hole_id'] or 'X'}", []).append(mw)

    antes = set(gw.wells)
    counts = gw.match_and_place_wells(dq_results, mw_by_hole)
    # El caserón se DECLARA en el pozo, no se deja derivar del nombre: es la
    # agrupación de LOCO-CV, y una litología cruza caserones pero un pozo no.
    for wn in set(gw.wells) - antes:
        gw.wells[wn].caseron = caseron
    return {"dq": dq_rep, "n_pozos_mw": len(mw_by_hole), "n_puntos": n_pts,
            "err_mw": err_mw, "match": counts, "t": round(time.time()-t0, 1)}


def cargar_caseron(caseron: str, verbose=True) -> Dict:
    print(f"\n{'='*72}\n  {caseron}\n{'='*72}")
    arch = descubrir_archivos(caseron)
    print(f"  archivos: {len(arch['dq'])} DQ · {len(arch['mw'])} MW · "
          f"{len(arch['capas'])} DXF" + (f" · {len(arch['dwg'])} DWG ⚠" if arch["dwg"] else ""))
    if arch["dwg"] and not arch["capas"]:
        # No se carga a medias: sin mallas no hay etiqueta de litología, y un
        # caserón sin etiquetas no puede entrenar ni evaluarse.
        print(f"  ⛔ BLOQUEADO: las {len(arch['dwg'])} mallas vienen en .dwg, que "
              f"ezdxf no lee.\n     Convertir a DXF antes de usar este caserón:")
        for p in arch["dwg"]:
            print(f"       · {os.path.basename(p)}")
        return {"caseron": caseron, "bloqueado": "mallas en .dwg", "arch": arch}

    print(f"  — mallas —")
    r_capas = cargar_capas(caseron, arch["capas"], verbose)
    for n, e in r_capas["errores"]:
        print(f"     ⚠ {n}: {e}")

    print(f"  — pozos —")
    r_xml = cargar_xml(caseron, arch["dq"], arch["mw"], verbose)
    d = r_xml["dq"]
    print(f"     DQ: {d['n_archivos']} archivos → {d['n_planes']} planes, "
          f"{d['n_tiros']} tiros" +
          (f" · {len(d['conflictos'])} con coordenadas distintas entre revisiones ⚠"
           if d["conflictos"] else ""))
    print(f"     MW: {r_xml['n_pozos_mw']} pozos, {r_xml['n_puntos']:,} puntos"
          .replace(",", ".") + (f" · {r_xml['err_mw']} ilegibles ⚠" if r_xml["err_mw"] else ""))
    print(f"     match: {r_xml['match']}")
    print(f"     ({r_capas['t']}s mallas + {r_xml['t']}s XML)")
    return {"caseron": caseron, "capas": r_capas, "xml": r_xml, "arch": arch}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--caseron", action="append", default=[],
                    help="caserón a cargar (repetible). Por defecto: los cuatro del plan.")
    ap.add_argument("--todos", action="store_true")
    ap.add_argument("--guardar", default=None, help="ruta .gwz donde guardar el proyecto")
    ap.add_argument("--cruzar", action="store_true",
                    help="correr el cruce geométrico y el índice de dominios al terminar")
    args = ap.parse_args()

    objetivo = args.caseron or (CASERONES if args.todos else CASERONES)

    if not asegurar_datos_extraidos():
        print("\n  ⛔ No se puede continuar sin los datos. Faltan zips en test_data/.")
        return []

    # El vocabulario exportado por el autor es la fuente ÚNICA para esta
    # carga (anclas de UCS + 37 alias `dxf_layer`, uno por malla real de los
    # cuatro caserones); reemplaza a seed_attribute_registry(), que sembraba
    # la tabla de Karzulovic hardcodeada y no conocía estos nombres de malla.
    with open(VOCABULARIO, encoding="utf-8") as fh:
        rep_vocab = gw.import_vocabulary(fh.read())
    if rep_vocab["errores"]:
        print(f"  ⚠ vocabulario: {len(rep_vocab['errores'])} error(es) al importar:")
        for e in rep_vocab["errores"]:
            print(f"     · {e}")
    print(f"  vocabulario importado: {rep_vocab['atributos']} atributos, "
          f"{rep_vocab['alias']} alias.")
    if os.path.exists(PERFIL):
        gw.seed_param_registry()   # el perfil se aplica SOBRE el registro, no lo reemplaza
        with open(PERFIL, encoding="utf-8") as fh:
            rep_perfil = gw.import_site_profile(fh.read())
        print(f"  perfil de faena aplicado: {rep_perfil.get('n_aplicados', 0)} "
              f"parámetro(s)" +
              (f" · {len(rep_perfil['rechazados'])} rechazado(s)"
               if rep_perfil.get("rechazados") else ""))

    t0 = time.time()
    resultados = [cargar_caseron(c) for c in objetivo]

    print(f"\n{'='*72}\n  RESUMEN DE CARGA\n{'='*72}")
    print(f"  pozos cargados : {len(gw.wells)}")
    print(f"  puntos MWD     : {sum(len(w.points) for w in gw.wells.values()):,}".replace(",", "."))
    print(f"  mallas         : {len(gw.layers)}")
    bloqueados = [r["caseron"] for r in resultados if r.get("bloqueado")]
    if bloqueados:
        print(f"  ⛔ bloqueados  : {', '.join(bloqueados)}")
    pend = gw.pending_alias_count()
    if pend:
        print(f"  ⚠ vocabulario  : {pend} texto(s) sin atributo canónico asignado")
    print(f"  tiempo total   : {time.time()-t0:.1f}s")

    if args.cruzar:
        print(f"\n  cruzando geometría…")
        t1 = time.time()
        gw.classify_all_wells_cached()
        gw.build_domain_index()
        print(f"  cruce: {time.time()-t1:.1f}s · overlap_stats={gw.overlap_stats}")

    if args.guardar:
        gw.save_project(args.guardar)
        print(f"\n  proyecto guardado en {args.guardar} "
              f"({os.path.getsize(args.guardar)/1e6:.1f} MB)")
    return resultados


if __name__ == "__main__":
    main()
