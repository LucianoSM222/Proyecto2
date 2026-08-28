"""
cargar_caserones.py — Carga masiva de los caserones reales de Punta del Cobre
desde test_data/reales/, preparatoria de la sesión 5 (entrenamiento + LOCO-CV).

No es parte de la aplicación: es el guion de ingesta que toma los ~1.900 XML
IREDES y las mallas DXF entregadas por Pucobre, los cruza, y deja el estado
listo (o un .gwz guardado) para entrenar. Se ejecuta desde la raíz del repo.

    python3 cargar_caserones.py --caseron PCS_1043 --caseron PCC_0042
    python3 cargar_caserones.py --todos --guardar proyecto.gwz

Cada caserón se resuelve así:
  · DQ  test_data/reales/{PCC|PCS}/CP*/DQ/DQ{caseron}_*.xml   (fusionados)
  · MW  test_data/reales/{PCC|PCS}/CP*/MW{caseron}_*.xml
  · DXF test_data/reales/Capas {caseron}/**/*.dxf
        subcarpeta "Litología*" -> rol litologia · "Estructuras*" -> estructura
"""

import os, sys, glob, time, argparse
from typing import Dict, List

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import geomech_wizard as gw

REALES = os.path.join(HERE, "test_data", "reales")

# Los cuatro caserones del plan (CLAUDE.md). El rol entrena/prueba NO se fija
# aquí: es un parámetro de ejecución de la sesión 5, no una constante.
CASERONES = ["PCS_1043", "PCC_0042", "PCS_1059", "PCC_1541"]


def _prefijo_sitio(caseron: str) -> str:
    return caseron.split("_")[0]          # PCS_1043 -> PCS


def descubrir_archivos(caseron: str) -> Dict[str, List[str]]:
    """Rutas de DQ, MW y mallas de un caserón, sin leer nada todavía."""
    sitio = _prefijo_sitio(caseron)
    dq = sorted(p for p in glob.glob(f"{REALES}/{sitio}/CP*/DQ/*.xml")
                if os.path.basename(p).startswith(f"DQ{caseron}_"))
    mw = sorted(p for p in glob.glob(f"{REALES}/{sitio}/CP*/*.xml")
                if os.path.basename(p).startswith(f"MW{caseron}_"))
    capas = sorted(glob.glob(f"{REALES}/Capas {caseron}/**/*.dxf", recursive=True))
    # .dwg: ezdxf no los lee. Se listan aparte para poder DECLARAR que el
    # caserón queda incompleto, en vez de cargarlo a medias en silencio.
    dwg = sorted(glob.glob(f"{REALES}/Capas {caseron}/**/*.dwg", recursive=True))
    return {"dq": dq, "mw": mw, "capas": capas, "dwg": dwg}


def _rol_de_ruta(path: str) -> str:
    """Rol de la malla según la subcarpeta en que Pucobre la entregó."""
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
            print(f"     {name:14s} {len(tris):7,d} tris  {rol:10s} {attr}".replace(",", "."))
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

    gw.seed_attribute_registry()
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
