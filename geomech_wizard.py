"""
╔══════════════════════════════════════════════════════════════════════════════╗
║       MWD GEOMECH WIZARD — v1.1  (port fiel del HTML de referencia)         ║
║       Autor: Luciano Poblete Vergara — USACH 2026                            ║
║                                                                              ║
║  Cambios v1.1 (respecto a v1.0) — corrige los MWD que no aparecían:         ║
║    · Se replica utm2t() con globalCenter                                     ║
║    · Matching MW↔DQ con fallback laxo (por hole_id si plan_id no coincide) ║
║    · Sistema de coordenadas: DXF nativo (X=Este, Y=Norte, Z=Cota)           ║
║    · wz_state['step1']['xml_loaded'] se actualiza al terminar la carga      ║
║    · Diagnóstico visual de calce MWD↔DXF                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, json, time, base64, tempfile, re, warnings, threading, traceback
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
import ezdxf, ezdxf.recover
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import cross_val_score, KFold
from sklearn.inspection import permutation_importance
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import dash
from dash import dcc, html, Input, Output, State, callback_context, no_update, ALL
import dash_bootstrap_components as dbc

warnings.filterwarnings("ignore")
IN_COLAB = "google.colab" in sys.modules

APP_TITLE, APP_VERSION, PORT = "MWD GeoMech Wizard", "1.1", 8050
NS_IR = "http://www.iredes.org/xml"
NS_DR = "http://www.iredes.org/xml/DrillRig"
IR, DR = f"{{{NS_IR}}}", f"{{{NS_DR}}}"

ML_FEATURES = ["vel","pp","pa","pd","pr","pf","se"]
ML_LABELS   = ["ROP","PP","AP","DP","RP","FP","SE"]
UCS_CONFIG = {"physical_min":25.0,"physical_max":280.0,"warning_min":50.0,"warning_max":230.0,"default_min":60.0,"default_max":210.0}
PALETTE = ["#3B8BD4","#D05538","#5DCAA5","#EF9F27","#D4537E","#7F77DD","#2ECC71","#E74C3C","#F39C12","#1ABC9C","#9B59B6","#F1C40F","#E67E22","#BDC3C7"]
EPS = 1e-9
PARSE_BUDGET_S = 12.0

@dataclass
class Layer:
    name: str; kind: str; triangles: np.ndarray
    bbox_min: np.ndarray; bbox_max: np.ndarray
    ucs_lab: Optional[float] = None; folder: str = "Litología"
    # Etiquetado caserón×litología (T2): el caserón se asigna por dropdown en
    # el árbol de capas; lito_alias permite matchear la litología del Excel
    # cuando el nombre de la capa DXF no coincide literal. ucs_lo/hi/mid son la
    # banda de laboratorio autocompletada desde geomech_bands (el usuario puede
    # sobrescribir ucs_lab manualmente sin perder la banda).
    caseron: Optional[str] = None; lito_alias: Optional[str] = None
    ucs_lo: Optional[float] = None; ucs_hi: Optional[float] = None
    ucs_mid: Optional[float] = None

@dataclass
class MWDPoint:
    largo: float; vel: float; pp: float; pa: float
    pd: float; pr: float; pf: float; se: float; t: float
    este: float = 0.0; norte: float = 0.0; cota: float = 0.0
    raw_vel: float = 0.0; raw_pp: float = 0.0; raw_pa: float = 0.0
    raw_pd: float = 0.0; raw_pr: float = 0.0; raw_pf: float = 0.0
    entrenable: bool = True; norm_excluded: bool = False
    dominio: Optional[str] = None; lito: Optional[str] = None; estructura: Optional[str] = None
    ucs_ml: Optional[float] = None; ucs_confiable: Optional[float] = None
    ucs_ml_prelim: bool = False
    # Intervalo de predicción del RF (percentiles 10/90 sobre los árboles).
    ucs_ml_p10: Optional[float] = None; ucs_ml_p90: Optional[float] = None
    di: Optional[float] = None; grupo: Optional[str] = None
    lito_inferida: Optional[str] = None; estructura_inferida: Optional[str] = None
    grupo_confianza: Optional[float] = None
    # Verificación de consistencia banda-laboratorio vs intervalo ML (T3):
    # "compatible" / "incompatible" / "ambiguo" / None (no evaluable).
    band_check: Optional[str] = None

@dataclass
class Well:
    well_name: str; plan_id: str; hole_id: str
    points: List[MWDPoint] = field(default_factory=list)
    collar: Optional[Dict] = None; final_pt: Optional[Dict] = None
    origin: str = "matched"
    # Candidatos DQ×hole disponibles para este pozo (mismo hole_id, distintos
    # planes hermanos), cada uno con su error de coherencia de largo. Se usa
    # para poblar el dropdown de reasignación manual de pozos ambiguos.
    dq_candidates: List[Dict] = field(default_factory=list)

# Estado global
layers: Dict[str, Layer] = {}
wells: Dict[str, Well] = {}
domains: Dict[str, Dict] = {}
domain_groups: List[Dict] = []
clean_filters: List[Dict] = []
excel_data: List[Dict] = []
# Bandas geomecánicas de laboratorio (T2): registros por caserón×litología.
#   by_pair    : {(caseron_norm, lito_norm): band}
#   by_lito    : {lito_norm: [band, ...]}          (misma litología, varios caserones)
#   by_caseron : {caseron_norm: [band, ...]}       (mismo caserón, varias litologías)
#   records    : lista completa de bandas parseadas
geomech_bands: Dict[str, Dict] = {"by_pair": {}, "by_lito": {}, "by_caseron": {}, "records": []}
parse_warnings: List[str] = []
rf_model = None
rf_stats: Optional[Dict] = None
prelim_model = None
di_config = {"params":["pp","pr","pd","pf"],"weights":{"pp":0.35,"pr":0.20,"pd":0.25,"pf":0.20},"window":14}
di_threshold: float = 1.5
group_interval_m: float = 2.0
ucs_range = dict(ucs_min=UCS_CONFIG["default_min"], ucs_max=UCS_CONFIG["default_max"])
cal_factors = {k: 1.0 for k in ("vel","pp","pa","pd","pr","pf","se")}
global_center: Optional[Dict[str, float]] = None

wz_state = {
    'step1':{'dxf_loaded':False,'xml_loaded':False},
    'step2':{'calibrated':False,'cleaned':False},
    'step3':{'di_computed':False},
    'step4':{'model_trained':False},
    'step5':{'grouped':False,'predicted':False},
}

# ─── SISTEMA DE TAREAS EN SEGUNDO PLANO (progreso + log para operaciones largas) ─
# Permite ejecutar operaciones potencialmente largas (cruce geométrico + ML)
# en un hilo aparte, con progreso y log consultables desde el navegador
# mediante polling (dcc.Interval), en vez de bloquear el callback de Dash
# (que dejaría la UI congelada sin ningún feedback, como reportó el usuario).
task_state = {
    "running": False,      # True mientras el hilo de fondo trabaja
    "progress": 0,         # 0-100
    "stage": "",            # descripción de la etapa actual
    "log": [],              # lista de líneas de log con timestamp
    "error": None,           # mensaje de error si algo falló
    "result": None,          # resultado final (stats del modelo) si terminó OK
    "done": False,           # True cuando la tarea terminó (con o sin error)
}
task_lock = threading.Lock()

def task_log(msg, stage=None, progress=None):
    with task_lock:
        ts = time.strftime("%H:%M:%S")
        task_state["log"].append(f"[{ts}] {msg}")
        if len(task_state["log"]) > 300:
            task_state["log"].pop(0)
        if stage is not None: task_state["stage"] = stage
        if progress is not None: task_state["progress"] = progress
    print(f"[TASK] {msg}")

def run_ml_task(ucs_min, ucs_max):
    """
    Ejecuta el pipeline completo (cruce geométrico + índice de dominios +
    entrenamiento RF) en un hilo de fondo, reportando avance a task_state.
    """
    with task_lock:
        task_state.update(running=True, progress=0, stage="Iniciando…",
                           log=[], error=None, result=None, done=False)
    try:
        task_log("Iniciando cruce geométrico DXF ↔ MWD...", "Cruce geométrico (Möller-Trumbore)", 5)
        t0 = time.time()
        classify_all_wells()
        task_log(f"Cruce geométrico completado en {time.time()-t0:.1f}s.", progress=45)

        task_log("Construyendo índice de dominios...", "Índice de dominios", 50)
        build_domain_index()
        all_pts = list(all_points())
        n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio,{}).get("ucs_lab"))
        task_log(f"Índice construido: {n_ucs}/{len(all_pts)} puntos con UCS asignado.", progress=55)

        task_log("Entrenando Random Forest...", "Entrenamiento Random Forest", 60)
        t0 = time.time()
        stats = train_rf(ucs_min, ucs_max)
        task_log(f"Entrenamiento completado en {time.time()-t0:.1f}s.", progress=85)

        if "error" in stats:
            task_log(f"⚠ {stats['error']}", progress=100)
            with task_lock:
                task_state.update(running=False, done=True, error=stats["error"])
            return

        task_log("Generando predicciones UCS para todos los pozos...", "Prediciendo UCS", 90)
        predict_all_wells()
        wz_state['step4']['model_trained'] = True
        task_log(f"✅ Listo. R²={stats['r2_train']} RMSE={stats['rmse_train']} MPa N={stats['n_train']}", "Completado", 100)
        with task_lock:
            task_state.update(running=False, done=True, result=stats)
    except Exception as e:
        tb = traceback.format_exc()
        task_log(f"❌ ERROR: {e}\n{tb}", "Error", 100)
        with task_lock:
            task_state.update(running=False, done=True, error=str(e))


def log_warn(msg):
    parse_warnings.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    if len(parse_warnings) > 500: parse_warnings.pop(0)
    print(f"⚠  {msg}")

def set_center(norte, este, cota):
    global global_center
    if global_center is None:
        global_center = {'norte':float(norte),'este':float(este),'cota':float(cota)}
        log_warn(f'globalCenter fijado: N={norte:.1f} E={este:.1f} Z={cota:.1f}')

def all_points():
    for w in wells.values():
        yield from w.points

# ─── COHERENCIA MW↔DQ (matching robusto con multi-DQ hermanos) ─────────────────
# Tolerancia de coherencia de largo: |largo_max_MWD − dist(collar,final)| / largo
# Validado con pozo real H5: 0.09 m sobre 36.07 m (0.3%). Un DQ del plan
# equivocado (abanico hermano desplazado) normalmente rompe esta coherencia.
COHERENCE_TOL = 0.05

def _dist3d(a, b):
    """Distancia euclidiana 3D entre dos puntos {norte,este,cota}."""
    return float(np.sqrt(
        (a["este"]  - b["este"]) **2 +
        (a["norte"] - b["norte"])**2 +
        (a["cota"]  - b["cota"]) **2))

def _coherence_err(largo_max, collar, final_pt):
    """
    Error relativo entre el largo máximo del MWD y la distancia euclidiana
    collar→final del DQ candidato. Un match correcto lo cumple (~0.3%); un DQ
    del plan hermano equivocado suele violarlo (collar desplazado).
    """
    if largo_max is None or largo_max <= 0:
        return float("inf")
    return abs(largo_max - _dist3d(collar, final_pt)) / largo_max

def _plan_short(pid):
    """Etiqueta corta del plan_id (ej. 'MGN_3025_PR01_TH_P40' → 'P40')."""
    m = re.findall(r"P\d+", pid or "")
    return m[-1] if m else (pid or "?")

def _plan_prefix_sim(pid_a, pid_b):
    """Largo del prefijo común entre dos plan_id (similitud para ordenar)."""
    s = 0
    for c1, c2 in zip(pid_a or "", pid_b or ""):
        if c1 == c2: s += 1
        else: break
    return s

def match_and_place_wells(dq_results, mw_by_hole):
    """
    Matching robusto MW↔DQ con multi-DQ hermanos + colocación espacial.

    Para cada pozo MWD elige el DQ×hole cuyo collar/final CUMPLE la coherencia
    de largo (|largo_max − dist(collar,final)|/largo_max < COHERENCE_TOL),
    probando candidatos en orden: match exacto de plan_id primero, luego DQ
    hermanos ordenados por similitud de prefijo de plan_id. Si ningún candidato
    cumple, el pozo queda origin="ambiguous" en posición ficticia (para
    reasignar a mano). Puebla el dict global `wells` e interpola las coordenadas
    de cada punto por su parámetro t (largo/largo_max). Devuelve un dict con los
    contadores {matched, fallback, ambiguous, no_dq}.

    Aislada de on_xml para poder testear el matching sin la capa Dash.
    """
    # Índice por hole_id de todos los DQ (fallback por hole)
    all_holes = {}
    for pid, dq in dq_results.items():
        for hid, tiro in dq["tiros"].items():
            all_holes.setdefault(hid, []).append((pid, tiro))

    counts = {"matched": 0, "fallback": 0, "ambiguous": 0, "no_dq": 0}
    for key, mw_list in mw_by_hole.items():
        best = max(mw_list, key=lambda m: m["largo_max"])
        pid = best["plan_id"]; hid = best["hole_id"]; largo_max = best["largo_max"]

        # ── Lista ORDENADA de candidatos DQ para este hole_id ──
        # 1º el match exacto de plan_id (si existe), luego los DQ hermanos
        # ordenados por similitud de prefijo de plan_id (descendente). Se
        # deduplica por plan_id (cada plan aporta a lo más un tiro por hole).
        candidates = []  # [(pid_dq, tiro)]
        seen_pids = set()
        if pid in dq_results and hid in dq_results[pid].get("tiros", {}):
            candidates.append((pid, dq_results[pid]["tiros"][hid]))
            seen_pids.add(pid)
        if hid in all_holes:
            for pid_dq, tiro in sorted(all_holes[hid],
                                       key=lambda x: -_plan_prefix_sim(pid, x[0])):
                if pid_dq in seen_pids: continue
                candidates.append((pid_dq, tiro))
                seen_pids.add(pid_dq)

        # Metadatos de todos los candidatos (para el dropdown de reasignación)
        cand_info = [{
            "plan_id": pid_dq, "hole_id": hid or "",
            "collar": tiro["collar"], "final_pt": tiro["final_pt"],
            "err_pct": round(_coherence_err(largo_max, tiro["collar"], tiro["final_pt"]) * 100, 2),
        } for pid_dq, tiro in candidates]

        # ── Elegir el primer candidato que cumpla la coherencia de largo ──
        collar = final_pt = None; origin = "no_dq"
        chosen_pid = None; discarded = []
        for pid_dq, tiro in candidates:
            err = _coherence_err(largo_max, tiro["collar"], tiro["final_pt"])
            if err < COHERENCE_TOL:
                collar, final_pt = tiro["collar"], tiro["final_pt"]
                chosen_pid = pid_dq
                break
            discarded.append((pid_dq, err))

        if chosen_pid is not None:
            if chosen_pid == pid:
                origin = "matched"; counts["matched"] += 1
            else:
                origin = "fallback_hole"; counts["fallback"] += 1
                log_warn(f'MW "{key}" plan="{pid}" hole={hid}: usado DQ hermano '
                         f'"{chosen_pid}" (coherencia OK).')
        elif candidates:
            # Había candidatos por hole_id pero NINGUNO cumple coherencia:
            # pozo ambiguo → posición ficticia + registro de descartados.
            origin = "ambiguous"; counts["ambiguous"] += 1
            det = ", ".join(f'{_plan_short(p)} (err {e*100:.1f}%)' for p, e in discarded)
            log_warn(f'MW "{key}" plan="{pid}" hole={hid}: AMBIGUO, ningún DQ '
                     f'cumple coherencia <{COHERENCE_TOL*100:.0f}%. Descartados: {det}. '
                     f'Posición ficticia; reasignar manualmente en el árbol de capas.')
        else:
            counts["no_dq"] += 1
            log_warn(f'MW "{key}": sin DQ. Posición ficticia.')

        pts = best["puntos"]
        if not pts:
            log_warn(f'MW "{key}": 0 puntos, omitido.'); continue
        if collar and final_pt:
            if global_center is None:
                set_center(collar["norte"], collar["este"], collar["cota"])
            for p in pts:
                p.este  = collar["este"]  + p.t*(final_pt["este"]  - collar["este"])
                p.norte = collar["norte"] + p.t*(final_pt["norte"] - collar["norte"])
                p.cota  = collar["cota"]  + p.t*(final_pt["cota"]  - collar["cota"])
        else:
            cx = global_center["este"] if global_center else 0
            cy = global_center["norte"] if global_center else 0
            cz = global_center["cota"] if global_center else 0
            for p in pts:
                p.este = cx; p.norte = cy; p.cota = cz - p.largo
        wells[key] = Well(well_name=key, plan_id=pid, hole_id=hid or "",
                          points=pts, collar=collar, final_pt=final_pt, origin=origin,
                          dq_candidates=cand_info)
    return counts

# ─── PARSERS ──────────────────────────────────────────────────────────────────
def parse_dxf(path, fname):
    try:
        doc, _ = ezdxf.recover.readfile(path)
    except Exception as e:
        raise RuntimeError(f"DXF ilegible: {e}")
    tris, skipped = [], 0
    for ent in doc.modelspace().query("3DFACE"):
        try:
            v0 = np.array(ent.dxf.vtx0, dtype=np.float64)
            v1 = np.array(ent.dxf.vtx1, dtype=np.float64)
            v2 = np.array(ent.dxf.vtx2, dtype=np.float64)
            v3 = np.array(ent.dxf.vtx3 if ent.dxf.hasattr("vtx3") else ent.dxf.vtx2, dtype=np.float64)
            if not all(np.isfinite(v).all() for v in (v0,v1,v2,v3)):
                skipped += 1; continue
            tris.append([v0,v1,v2])
            if not np.allclose(v3, v2): tris.append([v0,v2,v3])
        except: skipped += 1
    if not tris: raise RuntimeError("sin caras 3DFACE válidas")
    if skipped: log_warn(f'DXF "{fname}": {skipped} caras omitidas.')
    return np.array(tris, dtype=np.float64), skipped

def _fval(elem, tag, ns=""):
    node = elem.find(f"{ns}{tag}") if elem is not None else None
    if node is None or not node.text: return None
    try: return float(node.text.strip())
    except: return None

def parse_dq(path, fname):
    """Parsea DQ IREDES. TMatrix: row 0→Norte, row 1→Este, row 2→Cota."""
    try: root = ET.parse(path).getroot()
    except Exception as e: raise RuntimeError(f"XML ilegible: {e}")
    tmat = np.zeros((4,4))
    tmn = root.find(f".//{IR}TMatrix")
    if tmn is not None:
        for i, col in enumerate(tmn.findall(f"{IR}Col")[:4]):
            try:
                for j, ax in enumerate(["x","y","z","w"]):
                    n = col.find(f"{IR}{ax}")
                    tmat[j,i] = float(n.text) if n is not None and n.text else 0.0
            except: pass
    def lu(lx, ly, lz):
        return {
            "norte": tmat[0,0]*lx + tmat[0,1]*ly + tmat[0,2]*lz + tmat[0,3],
            "este":  tmat[1,0]*lx + tmat[1,1]*ly + tmat[1,2]*lz + tmat[1,3],
            "cota":  tmat[2,0]*lx + tmat[2,1]*ly + tmat[2,2]*lz + tmat[2,3],
        }
    pn = root.find(f".//{IR}PlanIdRef")
    plan_id = (pn.text or "").strip() if pn is not None else ""
    tiros, skipped, t0 = {}, 0, time.time()
    hq_list = root.findall(f".//{DR}HoleQualityData")
    for h, hq in enumerate(hq_list):
        if h % 256 == 0 and time.time() - t0 > PARSE_BUDGET_S:
            log_warn(f'DQ "{fname}": timeout, omitidos {len(hq_list)-h} tiros.'); break
        try:
            hole = hq.find(f"{DR}Hole")
            if hole is None: skipped += 1; continue
            hid = (hole.findtext(f"{DR}HoleId") or "").strip()
            sp, ep = hole.find(f"{DR}StartPoint"), hole.find(f"{DR}EndPoint")
            if not hid or sp is None or ep is None: skipped += 1; continue
            coords = [_fval(sp,"PointX",IR),_fval(sp,"PointY",IR),_fval(sp,"PointZ",IR),
                      _fval(ep,"PointX",IR),_fval(ep,"PointY",IR),_fval(ep,"PointZ",IR)]
            if any(v is None or not np.isfinite(v) for v in coords): skipped+=1; continue
            tiros[hid] = {"collar":lu(*coords[:3]), "final_pt":lu(*coords[3:])}
        except: skipped += 1
    if skipped: log_warn(f'DQ "{fname}": {skipped} tiros omitidos.')
    return {"plan_id": plan_id, "tiros": tiros}

def parse_mw(path, fname):
    """Val = LT | ROP | PP | FP(Feed=AP) | DP | RP | FLP(Flush=FP). Simba COPROD."""
    try: root = ET.parse(path).getroot()
    except Exception as e: raise RuntimeError(f"XML ilegible: {e}")
    pn = root.find(f".//{IR}PlanIdRef")
    plan_id = (pn.text or "").strip() if pn is not None else ""
    hn = root.find(f".//{DR}MWDholeId")
    hole_id = (hn.text or "").strip() if hn is not None else None
    if not hole_id:
        m = re.search(r"H(\d+)_", fname, re.I)
        if m: hole_id = m.group(1)
    if not plan_id:
        m2 = re.search(r"MW(.+?)H\d+_", fname, re.I)
        if m2: plan_id = m2.group(1)
    samples = root.findall(f".//{DR}Sample")
    puntos, largo_max, skipped, t0 = [], 0.0, 0, time.time()
    for i, s in enumerate(samples):
        if i % 512 == 0 and time.time() - t0 > PARSE_BUDGET_S:
            log_warn(f'MWD "{fname}": timeout, omitidas {len(samples)-i} muestras.'); break
        try:
            vn = s.find(f"{DR}Val")
            if vn is None or not vn.text: skipped += 1; continue
            parts = [float(x) for x in vn.text.strip().split()]
            if len(parts) < 7: skipped += 1; continue
            lt, rop, pp, ap, dp, rp, flp = parts[:7]
            if not all(np.isfinite(v) for v in (lt,rop,pp,ap,dp,rp,flp)):
                skipped += 1; continue
            se = (pp + rp + ap) / (rop + EPS)
            puntos.append(MWDPoint(
                largo=lt, vel=rop, pp=pp, pa=ap, pd=dp, pr=rp, pf=flp, se=se, t=0.0,
                raw_vel=rop, raw_pp=pp, raw_pa=ap, raw_pd=dp, raw_pr=rp, raw_pf=flp,
            ))
            if lt > largo_max: largo_max = lt
        except: skipped += 1
    if skipped: log_warn(f'MWD "{fname}": {skipped} muestras omitidas.')
    for p in puntos: p.t = p.largo/largo_max if largo_max > 0 else 0.0
    return {"plan_id": plan_id, "hole_id": hole_id, "largo_max": largo_max, "puntos": puntos}

def is_dq(fname, root_tag=""):
    return "DRPQual" in root_tag or fname.upper().startswith("DQ")

def guess_kind(fname):
    fl = fname.lower()
    return "estructura" if any(x in fl for x in ("falla","fault","struct","fractura")) else "litologia"

def parse_excel(path):
    try:
        df = pd.read_excel(path, header=0)
        df.columns = [str(c).strip().lower() for c in df.columns]
    except Exception as e:
        raise RuntimeError(f"Excel ilegible: {e}")
    col_map = {
        "caseron":["caseron","caserón","sector"],"perfil":["perfil","nivel","galeria"],
        "tiro":["tiro","hole","id","nro","numero"],
        "vel":["vel","rop","velocidad"],"pp":["pp","percusion","percusión"],
        "pr":["pr","rp","rotacion","rotación"],"pa":["pa","ap","avance"],
        "pd":["pd","dp","damper"],"pf":["pf","fp","flujo"],
        "ucs_excel":["ucs","resistencia","mpa","ucs_prom"],
    }
    def find_col(cands):
        for c in cands:
            hits = [col for col in df.columns if c in col]
            if hits: return hits[0]
        return None
    mapping = {k: find_col(v) for k,v in col_map.items()}
    rows = []
    for _, row in df.iterrows():
        r = {}
        for k, col in mapping.items():
            if col and col in df.columns:
                v = row[col]
                if k in ("caseron","perfil","tiro"):
                    r[k] = str(v).strip() if pd.notna(v) else None
                else:
                    try: r[k] = float(v) if pd.notna(v) else None
                    except: r[k] = None
            else: r[k] = None
        if r.get("tiro") is None: continue
        ucs = r.get("ucs_excel")
        if ucs is not None and (ucs < UCS_CONFIG["physical_min"] or ucs > UCS_CONFIG["physical_max"]):
            log_warn(f'Excel: UCS={ucs} MPa fuera físico, tiro {r.get("tiro")} omitido.')
            continue
        rows.append(r)
    return rows

# ─── EXCEL GEOMECÁNICO caserón×litología (T2) ─────────────────────────────────
# Columnas por índice (fila de encabezados = índice 2, datos desde índice 3):
#   2=Caserón · 3=Nivel · 23=Litología · 24=UCS[MPa] · 25=RMR · 26=RQD · 27=GSI
GEO_COL = {"caseron":2, "nivel":3, "litologia":23, "ucs":24, "rmr":25, "rqd":26, "gsi":27}
GEO_SHEET = "BUDGET_S_2026_V02"
GEO_HEADER_ROW = 2   # 0-indexado; datos desde GEO_HEADER_ROW+1

def _norm_txt(s):
    """Normaliza texto para matching: minúsculas, sin acentos, sin espacios extra."""
    if s is None: return ""
    s = str(s).strip().lower()
    trans = str.maketrans("áàäâãéèëêíìïîóòöôõúùüûñ", "aaaaaeeeeiiiiooooouuuun")
    return " ".join(s.translate(trans).split())

def _parse_band(raw):
    """
    Parsea un rango geomecánico tolerante a 'lo - hi', 'lo a hi' o valor único.
    Devuelve (lo, mid, hi) o None si no hay número. UCS/RMR/RQD/GSI son no
    negativos, así que se ignoran signos (un '-' es separador, no negativo).
    """
    if raw is None: return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none", "-", "—", "s/i", "sin dato"):
        return None
    nums = re.findall(r"\d+(?:[.,]\d+)?", s)
    if not nums: return None
    vals = [float(n.replace(",", ".")) for n in nums]
    lo, hi = (vals[0], vals[0]) if len(vals) == 1 else (min(vals[0], vals[1]), max(vals[0], vals[1]))
    return lo, (lo + hi) / 2.0, hi

def parse_geomech_excel(path, sheet=GEO_SHEET):
    """
    Parsea el Excel geomecánico caserón×litología. Devuelve una lista de
    registros {caseron, litologia, ucs_lo, ucs_mid, ucs_hi, rmr_raw,
    rqd_lo, rqd_mid, rqd_hi, gsi_raw}. Salta filas sin litología.
    Lee por índice de columna (header=None) para no depender de los nombres.
    """
    try:
        xls = pd.ExcelFile(path)
        sh = sheet if sheet in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(path, sheet_name=sh, header=None)
    except Exception as e:
        raise RuntimeError(f"Excel geomecánico ilegible: {e}")

    def cell(row, key):
        j = GEO_COL[key]
        if j >= df.shape[1]: return None
        v = row.iloc[j]
        return v if pd.notna(v) else None

    records = []
    for i in range(GEO_HEADER_ROW + 1, df.shape[0]):
        row = df.iloc[i]
        lito = cell(row, "litologia")
        caseron = cell(row, "caseron")
        if lito is None or not str(lito).strip():
            continue  # fila sin litología → se salta
        ucs_b = _parse_band(cell(row, "ucs"))
        rqd_b = _parse_band(cell(row, "rqd"))
        rec = {
            "caseron": str(caseron).strip() if caseron is not None else "",
            "litologia": str(lito).strip(),
            "ucs_lo":  ucs_b[0] if ucs_b else None,
            "ucs_mid": ucs_b[1] if ucs_b else None,
            "ucs_hi":  ucs_b[2] if ucs_b else None,
            "rmr_raw": None if cell(row, "rmr") is None else str(cell(row, "rmr")).strip(),
            "rqd_lo":  rqd_b[0] if rqd_b else None,
            "rqd_mid": rqd_b[1] if rqd_b else None,
            "rqd_hi":  rqd_b[2] if rqd_b else None,
            "gsi_raw": None if cell(row, "gsi") is None else str(cell(row, "gsi")).strip(),
        }
        records.append(rec)
    return records

def index_geomech_bands(records):
    """Reconstruye los índices globales geomech_bands a partir de los registros."""
    geomech_bands["by_pair"].clear()
    geomech_bands["by_lito"].clear()
    geomech_bands["by_caseron"].clear()
    geomech_bands["records"] = list(records)
    for rec in records:
        cn, ln = _norm_txt(rec["caseron"]), _norm_txt(rec["litologia"])
        geomech_bands["by_pair"][(cn, ln)] = rec
        geomech_bands["by_lito"].setdefault(ln, []).append(rec)
        if cn:
            geomech_bands["by_caseron"].setdefault(cn, []).append(rec)

def excel_caserones():
    """Lista ordenada de caserones presentes en el Excel geomecánico."""
    seen = []
    for rec in geomech_bands["records"]:
        c = rec["caseron"]
        if c and c not in seen: seen.append(c)
    return sorted(seen)

def excel_litologias():
    """Lista ordenada de litologías presentes en el Excel geomecánico."""
    seen = []
    for rec in geomech_bands["records"]:
        l = rec["litologia"]
        if l and l not in seen: seen.append(l)
    return sorted(seen)

def lookup_band(caseron, litologia):
    """
    Banda de una caserón×litología. Requiere caserón (decisión D1: la unidad de
    etiquetado es la intersección, no la litología global). Devuelve el record
    o None. Matching por texto normalizado (sin acentos/mayúsculas).
    """
    if not caseron or not litologia: return None
    return geomech_bands["by_pair"].get((_norm_txt(caseron), _norm_txt(litologia)))

def bands_for_caseron(caseron):
    """Todas las bandas (por litología) de un caserón dado."""
    if not caseron: return []
    return geomech_bands["by_caseron"].get(_norm_txt(caseron), [])

def apply_layer_band(layer):
    """
    Autocompleta la banda [ucs_lo, ucs_hi] y ucs_mid de una Layer si tiene
    caserón asignado y su nombre (o lito_alias) matchea una litología del Excel.
    Solo fija ucs_lab = ucs_mid si el usuario no lo había puesto a mano
    (comportamiento manual intacto). Devuelve True si autocompletó.
    """
    lito = layer.lito_alias or layer.name
    band = lookup_band(layer.caseron, lito)
    if band is None or band.get("ucs_mid") is None:
        return False
    layer.ucs_lo, layer.ucs_mid, layer.ucs_hi = band["ucs_lo"], band["ucs_mid"], band["ucs_hi"]
    if layer.ucs_lab is None:
        layer.ucs_lab = round(float(band["ucs_mid"]), 1)
    return True

# ─── MOTOR GEOMECÁNICO ────────────────────────────────────────────────────────
def _moller_trumbore_batch(origins, direction, tris, eps=1e-7):
    v0, v1, v2 = tris[:,0,:], tris[:,1,:], tris[:,2,:]
    e1 = v1 - v0; e2 = v2 - v0
    pvec = np.cross(direction, e2)
    det = np.einsum("ti,ti->t", e1, pvec)
    valid = np.abs(det) > eps
    inv = np.where(valid, 1.0/np.where(valid, det, 1.0), 0.0)
    tvec = origins[:,None,:] - v0[None,:,:]
    u = np.einsum("nti,ti->nt", tvec, pvec) * inv
    qvec = np.cross(tvec, e1[None,:,:])
    v = np.einsum("nti,i->nt", qvec, direction) * inv
    t = np.einsum("nti,ti->nt", qvec, e2) * inv
    hit = valid[None,:] & (u>=0) & (u<=1) & (v>=0) & ((u+v)<=1) & (t>eps)
    return hit.sum(axis=1)

def _layer_grid(layer, target_tris_per_cell=8):
    """
    Grid espacial 2D (Este/Norte) cacheado en la Layer, válido SOLO para rayo
    VERTICAL (0,0,1). Con rayo vertical, un triángulo solo puede ser cruzado
    por un punto cuya proyección XY caiga dentro del bbox XY del triángulo —
    el rayo nunca "sale" del tubo XY de su celda de origen, a diferencia de un
    rayo oblicuo (que sí cruza celdas vecinas y por tanto invalidaría un grid
    2D simple). Este es el motivo por el que se fuerza rayo vertical en
    points_in_mesh: permite la aceleración espacial sin perder intersecciones.
    """
    if not hasattr(layer, "_grid"):
        tris = layer.triangles
        tri_bmin = tris.min(axis=1); tri_bmax = tris.max(axis=1)
        span = layer.bbox_max[:2] - layer.bbox_min[:2]
        n_tris = max(len(tris), 1)
        area = max(float(span[0]) * float(span[1]), 1.0)
        cell = max(float(np.sqrt(area * target_tris_per_cell / n_tris)), 0.5)
        layer._grid_cell = cell
        gx0 = np.floor((tri_bmin[:,0]-layer.bbox_min[0])/cell).astype(np.int32)
        gy0 = np.floor((tri_bmin[:,1]-layer.bbox_min[1])/cell).astype(np.int32)
        gx1 = np.floor((tri_bmax[:,0]-layer.bbox_min[0])/cell).astype(np.int32)
        gy1 = np.floor((tri_bmax[:,1]-layer.bbox_min[1])/cell).astype(np.int32)
        grid = {}
        for ti in range(n_tris):
            for cx in range(gx0[ti], gx1[ti]+1):
                for cy in range(gy0[ti], gy1[ti]+1):
                    grid.setdefault((cx,cy), []).append(ti)
        layer._grid = {k: np.array(v, dtype=np.int64) for k,v in grid.items()}
    return layer._grid_cell, layer._grid

def points_in_mesh(points, layer, batch=256):
    """
    points (N,3) [Este, Norte, Cota] → bool (N,). Triángulos en el mismo sistema.

    IMPORTANTE: usa rayo estrictamente VERTICAL (0,0,1), no oblicuo. Esto es
    lo que permite acotar candidatos con un grid espacial 2D en XY sin perder
    intersecciones (ver _layer_grid). Una versión anterior usaba un rayo
    oblicuo (0.577,0.577,0.577) combinado con este mismo grid, lo cual es
    matemáticamente inválido: el rayo oblicuo cruza celdas vecinas en su
    trayectoria, así que acotar candidatos por la celda de origen del punto
    perdía la mayoría de las intersecciones reales (bug que causó que solo
    ~7% de los puntos se detectaran dentro de la malla, en vez del ~82% real).
    """
    n = len(points)
    inside = np.zeros(n, dtype=bool)
    lo = layer.bbox_min - 1.0; hi = layer.bbox_max + 1.0
    cand = np.where(np.all((points >= lo) & (points <= hi), axis=1))[0]
    if cand.size == 0: return inside

    cell, grid = _layer_grid(layer)
    ray = np.array([0.0, 0.0, 1.0], dtype=np.float64)   # vertical: requisito para que el grid XY sea válido

    pts_c = points[cand]
    gx = np.floor((pts_c[:,0] - layer.bbox_min[0]) / cell).astype(np.int32)
    gy = np.floor((pts_c[:,1] - layer.bbox_min[1]) / cell).astype(np.int32)
    cell_keys = {}
    for local_i, (cx, cy) in enumerate(zip(gx, gy)):
        cell_keys.setdefault((int(cx), int(cy)), []).append(local_i)

    for (cx, cy), local_idxs in cell_keys.items():
        tri_idx = grid.get((cx, cy))
        if tri_idx is None or tri_idx.size == 0:
            continue
        sub_tris = layer.triangles[tri_idx]
        local_idxs = np.array(local_idxs, dtype=np.int64)
        sub_pts = pts_c[local_idxs]
        for start in range(0, len(sub_pts), batch):
            chunk = sub_pts[start:start+batch]
            cnt = _moller_trumbore_batch(chunk, ray, sub_tris)
            hit = (cnt % 2) == 1
            global_idx = cand[local_idxs[start:start+batch]]
            inside[global_idx] = hit
    return inside

def classify_all_wells():
    layer_items = list(layers.items())
    for wn, well in wells.items():
        pts = well.points
        if not pts: continue
        try:
            coords = np.array([[p.este, p.norte, p.cota] for p in pts], dtype=np.float64)
            valid = np.all(np.isfinite(coords), axis=1)
            lito_hit = [None]*len(pts)
            estruct_hit = [None]*len(pts)
            for name, layer in layer_items:
                try:
                    mask = np.zeros(len(pts), dtype=bool)
                    if valid.any():
                        mask[valid] = points_in_mesh(coords[valid], layer)
                    for i in np.where(mask)[0]:
                        if layer.kind == "estructura": estruct_hit[i] = name
                        else: lito_hit[i] = name
                except Exception as e:
                    log_warn(f'Clasificación "{name}" en "{wn}": {e}')
            for i, p in enumerate(pts):
                lh, eh = lito_hit[i], estruct_hit[i]
                p.lito, p.estructura = lh, eh
                if lh and eh: p.dominio = f"{lh}::{eh}"
                elif lh: p.dominio = lh
                elif eh: p.dominio = f"::{eh}"
                else: p.dominio = None
        except Exception as e:
            log_warn(f'Clasificación pozo "{wn}": {e}')

def build_domain_index():
    domains.clear()
    for p in all_points():
        d = p.dominio or "(sin dominio)"
        if d not in domains: domains[d] = {"count":0, "ucs_lab":None}
        domains[d]["count"] += 1
    for name, layer in layers.items():
        if layer.ucs_lab is None: continue
        for d in domains:
            if d == name or d.startswith(name+"::") or d.endswith("::"+name):
                domains[d]["ucs_lab"] = layer.ucs_lab

def apply_calibration():
    cf = cal_factors
    for p in all_points():
        for k in ("vel","pp","pa","pd","pr","pf"):
            setattr(p, k, getattr(p, f"raw_{k}") * cf[k])
        p.se = (p.pp + p.pr + p.pa) / (p.vel + EPS) * cf.get("se", 1.0)

def derive_cal_factors_from_excel():
    var_map = {"vel":"vel","pp":"pp","pr":"pr","pa":"pa","pd":"pd","pf":"pf"}
    esums = {k:0.0 for k in var_map}; rsums = {k:0.0 for k in var_map}; counts = {k:0 for k in var_map}
    for ex in excel_data:
        wkey = next((k for k in wells if str(ex.get("perfil","")) in k and str(ex.get("tiro","")) in k), None)
        if not wkey: continue
        pts = wells[wkey].points
        if not pts: continue
        for k in var_map:
            v_excel = ex.get(k)
            if v_excel is None or not np.isfinite(v_excel): continue
            raw_vals = [getattr(p, f"raw_{k}") for p in pts if np.isfinite(getattr(p, f"raw_{k}", 0))]
            if not raw_vals: continue
            rmean = np.mean(raw_vals)
            if rmean == 0: continue
            esums[k] += v_excel; rsums[k] += rmean; counts[k] += 1
    return {k: round(esums[k]/rsums[k], 4) for k in var_map if counts[k] > 0 and rsums[k] > 0}

def apply_inicio_filter(cut_m):
    for well in wells.values():
        for p in well.points:
            if p.largo < cut_m: p.entrenable = False
            elif not p.norm_excluded: p.entrenable = True

def add_norm_filter(var_name, method):
    all_pts = list(all_points())
    vals = np.array([getattr(p, var_name) for p in all_pts
                     if getattr(p, var_name, None) is not None and
                     np.isfinite(getattr(p, var_name))], dtype=np.float64)
    if vals.size == 0: return None
    q25, q75 = np.percentile(vals, [25, 75]); iqr = q75-q25
    lmap = {
        "outliers_iqr":("IQR 1.5×", q25-1.5*iqr, q75+1.5*iqr),
        "q25_q75":("Q25-Q75", q25, q75),
        "whisker5":("5%-95%", *np.percentile(vals,[5,95])),
        "quantile_reg":("Q10-Q90", *np.percentile(vals,[10,90])),
    }
    label, lo, hi = lmap.get(method, ("rango", float(vals.min()), float(vals.max())))
    before = sum(1 for p in all_pts if p.entrenable)
    for well in wells.values():
        for p in well.points:
            v = getattr(p, var_name, None)
            if v is not None and (v < lo or v > hi):
                p.entrenable = False; p.norm_excluded = True
    after = sum(1 for p in all_points() if p.entrenable)
    filt = {"varName":var_name,"method":method,"label":label,
            "lo":round(float(lo),3),"hi":round(float(hi),3),
            "removed":before-after,"after":after,"total":len(all_pts)}
    clean_filters.append(filt)
    return filt

def _moving_variance(arr, half):
    n = len(arr); kernel = np.ones(2*half+1)
    counts = np.convolve(np.ones(n), kernel, mode="same")
    sums = np.convolve(arr, kernel, mode="same")
    sums2 = np.convolve(arr**2, kernel, mode="same")
    mean = sums/counts
    return np.maximum(sums2/counts - mean**2, 0.0)

def compute_di():
    cfg = di_config; half = cfg["window"]//2
    params = cfg["params"]
    total_w = sum(cfg["weights"].get(k,0) for k in params) or 1.0
    norm_w = {k: cfg["weights"].get(k,0)/total_w for k in params}
    for wn, well in wells.items():
        pts = well.points; n = len(pts)
        if n < cfg["window"]:
            log_warn(f'DI "{wn}": {n} pts, mín={cfg["window"]}.'); continue
        try:
            total = np.zeros(n)
            for k in params:
                arr = np.array([getattr(p, k) for p in pts], dtype=np.float64)
                mv = _moving_variance(arr, half)
                std = mv.std() or 1e-9
                z = (mv - mv.mean())/std
                total += norm_w[k] * z**2
            di = np.sqrt(total)
            for i, p in enumerate(pts): p.di = float(di[i])
        except Exception as e:
            log_warn(f'DI "{wn}": {e}')

def _get_train_data(ucs_min, ucs_max):
    X, y, n_excl = [], [], 0
    for p in all_points():
        if not p.entrenable or not p.dominio: continue
        dom = domains.get(p.dominio)
        if not dom or dom.get("ucs_lab") is None: continue
        ucs = dom["ucs_lab"]
        if ucs < ucs_min or ucs > ucs_max: continue
        if p.di is not None and p.di > di_threshold: n_excl += 1; continue
        X.append([getattr(p, k) for k in ML_FEATURES])
        y.append(ucs)
    return np.array(X, dtype=np.float64), np.array(y, dtype=np.float64), n_excl

def train_rf(ucs_min=None, ucs_max=None):
    global rf_model, rf_stats
    ucs_min = ucs_min or ucs_range["ucs_min"]
    ucs_max = ucs_max or ucs_range["ucs_max"]
    X, y, n_excl = _get_train_data(ucs_min, ucs_max)
    if len(X) < 10:
        return {"error": f"Insuficientes puntos ({len(X)} < 10)."}
    model = RandomForestRegressor(n_estimators=200, max_depth=8, min_samples_split=6,
                                    min_samples_leaf=3, max_features="sqrt", n_jobs=-1, random_state=42)
    model.fit(X, y)
    rf_model = model
    y_pred = model.predict(X)
    rmse_tr = float(np.sqrt(np.mean((y-y_pred)**2)))
    ss_tot = np.sum((y-y.mean())**2) or 1
    r2_tr = float(1 - np.sum((y-y_pred)**2)/ss_tot)
    rmsea = float(rmse_tr/np.sqrt(len(X)))
    k = max(2, min(5, len(X)//10))
    cv_scores = np.array([])
    if k >= 2:
        try:
            kf = KFold(n_splits=k, shuffle=True, random_state=42)
            cv_scores = cross_val_score(model, X, y, cv=kf, scoring="r2")
        except: pass
    n_tr = int(len(X)*0.7); rmse_te = None
    if n_tr >= 5 and len(X)-n_tr >= 3:
        m2 = RandomForestRegressor(n_estimators=100, max_depth=8, n_jobs=-1, random_state=0)
        m2.fit(X[:n_tr], y[:n_tr])
        rmse_te = float(np.sqrt(np.mean((y[n_tr:] - m2.predict(X[n_tr:]))**2)))
    feat_imp = {}
    try:
        n_samp = min(len(X), 300)
        idx = np.random.choice(len(X), n_samp, replace=False)
        perm = permutation_importance(model, X[idx], y[idx], n_repeats=10, random_state=42, n_jobs=-1)
        feat_imp = {ML_LABELS[i]: round(float(perm.importances_mean[i]), 4) for i in range(len(ML_FEATURES))}
    except: pass
    stats = {
        "n_train": len(X), "n_excl_disc": n_excl,
        "r2_train": round(r2_tr, 3), "rmse_train": round(rmse_tr, 1),
        "rmsea": round(rmsea, 4),
        "cv_r2_mean": round(float(cv_scores.mean()), 3) if cv_scores.size else None,
        "cv_r2_std": round(float(cv_scores.std()), 3) if cv_scores.size else None,
        "rmse_test": round(rmse_te, 1) if rmse_te else None,
        "overfit": round(rmse_te-rmse_tr, 1) if rmse_te else None,
        "feat_imp": feat_imp,
    }
    rf_stats = stats
    return stats

def predict_all_wells():
    if rf_model is None: return
    pts = list(all_points())
    if not pts: return
    X = np.array([[getattr(p, k) for k in ML_FEATURES] for p in pts], dtype=np.float64)
    # Intervalo de predicción a partir de los árboles individuales del RF:
    # matriz (n_arboles, n_puntos) y percentiles por columna (VECTORIZADO, sin
    # loop por punto). ucs_ml pasa a ser la MEDIANA de los árboles (p50).
    all_tree = np.stack([est.predict(X) for est in rf_model.estimators_])  # (T, N)
    p10 = np.percentile(all_tree, 10, axis=0)
    p50 = np.percentile(all_tree, 50, axis=0)
    p90 = np.percentile(all_tree, 90, axis=0)
    for i, p in enumerate(pts):
        p.ucs_ml     = round(float(p50[i]), 1)
        p.ucs_ml_p10 = round(float(p10[i]), 1)
        p.ucs_ml_p90 = round(float(p90[i]), 1)
        p.ucs_ml_prelim = False
    for well in wells.values():
        last_stable = None
        for p in well.points:
            is_drop = p.di is not None and p.di > di_threshold
            if not is_drop:
                last_stable = p.ucs_ml
                p.ucs_confiable = p.ucs_ml
            else:
                p.ucs_confiable = last_stable
    # Verificación de consistencia banda↔intervalo (si hay bandas cargadas).
    band_consistency()

# ─── VERIFICACIÓN DE BANDA (consistencia laboratorio ↔ intervalo ML) (T3) ─────
def _resolve_caseron(lito):
    """
    Resuelve el caserón de una litología a partir de la Layer DXF que la
    representa (por nombre o lito_alias). Si varias capas comparten esa
    litología con distinto caserón, es ambiguo y se devuelve None.
    """
    if not lito: return None
    ln = _norm_txt(lito)
    caserones = set()
    for layer in layers.values():
        lay_lito = _norm_txt(layer.lito_alias or layer.name)
        if lay_lito == ln and layer.caseron:
            caserones.add(layer.caseron)
    if len(caserones) == 1:
        return next(iter(caserones))
    return None  # 0 → sin caserón asignado; ≥2 → ambiguo, no resoluble

def band_consistency():
    """
    Para cada punto con litología (DXF o inferida) y caserón resoluble, compara
    su intervalo [p10, p90] contra la banda [ucs_lo, ucs_hi] de laboratorio de
    esa caserón×litología. Guarda p.band_check ∈ {compatible, incompatible,
    ambiguo} o None si no evaluable. No lanza excepciones por punto.
    """
    if not geomech_bands["records"]:
        for p in all_points(): p.band_check = None
        return
    for p in all_points():
        p.band_check = None
        try:
            lito = p.lito or p.lito_inferida
            if not lito or p.ucs_ml is None:
                continue
            caseron = _resolve_caseron(lito)
            band = lookup_band(caseron, lito)
            if band is None or band.get("ucs_lo") is None or band.get("ucs_hi") is None:
                continue
            lo, hi = band["ucs_lo"], band["ucs_hi"]
            med = p.ucs_ml
            p10 = p.ucs_ml_p10 if p.ucs_ml_p10 is not None else med
            p90 = p.ucs_ml_p90 if p.ucs_ml_p90 is not None else med
            intersecta = not (p90 < lo or p10 > hi)
            dentro = lo <= med <= hi
            # ¿La mediana cae en ≥2 bandas de litologías del mismo caserón?
            n_contienen = sum(1 for b in bands_for_caseron(caseron)
                              if b.get("ucs_lo") is not None and b.get("ucs_hi") is not None
                              and b["ucs_lo"] <= med <= b["ucs_hi"])
            if not intersecta:
                p.band_check = "incompatible"
            elif dentro and n_contienen < 2:
                p.band_check = "compatible"
            else:
                p.band_check = "ambiguo"
        except Exception:
            p.band_check = None

def run_cross_ml(ucs_min=None, ucs_max=None):
    classify_all_wells()
    build_domain_index()
    stats = train_rf(ucs_min, ucs_max)
    if "error" not in stats:
        predict_all_wells()
        wz_state['step4']['model_trained'] = True
    return stats

def train_prelim_from_excel():
    global prelim_model
    X, y = [], []
    for ex in excel_data:
        ucs = ex.get("ucs_excel")
        if ucs is None or not np.isfinite(ucs): continue
        vel,pp,pr,pa,pd,pf = [ex.get(k) for k in ("vel","pp","pr","pa","pd","pf")]
        if any(v is None or not np.isfinite(v) for v in (vel,pp,pr,pa,pd,pf)): continue
        se = (pp+pr+pa)/(vel+EPS)
        X.append([vel,pp,pa,pd,pr,pf,se]); y.append(ucs)
    if len(X) < 5: return {"error": f"Solo {len(X)} tiros válidos"}
    X, y = np.array(X), np.array(y)
    m = RandomForestRegressor(n_estimators=100, max_depth=6, n_jobs=-1, random_state=42)
    m.fit(X, y); prelim_model = m
    preds = m.predict(X)
    rmse = float(np.sqrt(np.mean((y-preds)**2)))
    r2 = float(1-np.sum((y-preds)**2)/(np.sum((y-y.mean())**2) or 1))
    pts = list(all_points())
    if pts:
        Xall = np.array([[getattr(p,k) for k in ML_FEATURES] for p in pts])
        pall = m.predict(Xall)
        for p, v in zip(pts, pall):
            p.ucs_ml = round(float(v),1); p.ucs_ml_prelim = True
    return {"n_train": len(X), "r2": round(r2,3), "rmse": round(rmse,1)}

def recompute_filters(cut_m=2.0):
    """
    Resetea 'entrenable' de todos los puntos y reaplica: corte de emboquillado
    + todos los filtros de clean_filters vigentes (en orden). Se usa al borrar
    un filtro individual, ya que los filtros son acumulativos y no se puede
    simplemente "des-marcar" un punto sin saber si otro filtro también lo
    excluía.
    """
    for p in all_points():
        p.entrenable = True
        p.norm_excluded = False
    apply_inicio_filter(cut_m)
    filters_copy = list(clean_filters)
    clean_filters.clear()
    for f in filters_copy:
        add_norm_filter(f["varName"], f["method"])

def remove_filter(idx):
    """Elimina el filtro en la posición idx y recalcula entrenable desde cero."""
    if 0 <= idx < len(clean_filters):
        clean_filters.pop(idx)
        recompute_filters()
        return True
    return False

def _split_dominio(d):
    if not d or d == "(sin dominio)": return None, None
    parts = d.split("::")
    return (parts[0] or None, parts[1] or None) if len(parts)==2 else (parts[0] or None, None)

def compute_domain_groups(tol_ucs=20.0, tol_di=0.15, interval_m=2.0):
    domain_groups.clear()
    intervals = []
    for wn, well in wells.items():
        try:
            gr = {}
            for p in well.points:
                if not p.entrenable or not p.dominio or p.ucs_ml is None: continue
                if p.di is None or not np.isfinite(p.di): continue
                gr.setdefault(int(p.largo//interval_m), []).append(p)
            for grp in gr.values():
                cnt = {}
                for p in grp: cnt[p.dominio] = cnt.get(p.dominio, 0) + 1
                dom_key = max(cnt, key=cnt.get)
                lito, est = _split_dominio(dom_key)
                if not lito and not est: continue
                intervals.append({
                    "lito":lito,"estructura":est,
                    "ucsMean":float(np.mean([p.ucs_ml for p in grp])),
                    "diMean":float(np.mean([p.di for p in grp])),
                    "pts":grp
                })
        except Exception as e: log_warn(f'Agrup "{wn}": {e}')
    for iv in intervals:
        found = next((g for g in domain_groups
                     if g["lito"]==iv["lito"] and g["estructura"]==iv["estructura"]
                     and abs(g["ucsMean"]-iv["ucsMean"])<=tol_ucs
                     and abs(g["diMean"]-iv["diMean"])<=tol_di), None)
        if found:
            n = found["n"]
            found["ucsMean"] = (found["ucsMean"]*n + iv["ucsMean"])/(n+1)
            found["diMean"] = (found["diMean"]*n + iv["diMean"])/(n+1)
            found["n"] += 1; found["count"] += len(iv["pts"])
            for p in iv["pts"]: p.grupo = found["id"]
            found["pts"].extend(iv["pts"])
        else:
            gid = f"G{len(domain_groups)+1}"
            g = {"id":gid,"lito":iv["lito"],"estructura":iv["estructura"],
                 "ucsMean":iv["ucsMean"],"diMean":iv["diMean"],
                 "n":1,"count":len(iv["pts"]),"pts":list(iv["pts"])}
            for p in iv["pts"]: p.grupo = gid
            domain_groups.append(g)
    wz_state['step5']['grouped'] = True
    return len(domain_groups)

def predict_unclassified(tol_ucs=20.0, tol_di=0.15, interval_m=2.0):
    if not domain_groups: return {"assigned":0,"total":0,"no_model":0}
    assigned = total = no_model = 0
    for well in wells.values():
        gr = {}
        for p in well.points:
            if p.dominio: continue
            total += 1
            if not p.entrenable or p.di is None or not np.isfinite(p.di): continue
            if p.ucs_ml is None: no_model += 1; continue
            gr.setdefault(int(p.largo//interval_m), []).append(p)
        for grp in gr.values():
            um = float(np.mean([p.ucs_ml for p in grp]))
            dm = float(np.mean([p.di for p in grp]))
            best, best_d = None, float("inf")
            for g in domain_groups:
                d = ((um-g["ucsMean"])/(tol_ucs or 1))**2 + ((dm-g["diMean"])/(tol_di or 1))**2
                if d < best_d: best_d, best = d, g
            if best:
                for p in grp:
                    p.grupo = best["id"]; p.lito_inferida = best["lito"]
                    p.estructura_inferida = best["estructura"]
                    p.grupo_confianza = float(1/(1+best_d**0.5))
                    assigned += 1
    wz_state['step5']['predicted'] = True
    # Reevaluar consistencia de banda incluyendo litologías inferidas.
    band_consistency()
    return {"assigned":assigned,"total":total,"no_model":no_model}

def _segments_by_domain(group_id, min_len=5):
    """
    Reconstruye segmentos continuos (mismo dominio, sin cortes de entrenable
    ni caídas DI) dentro de un dominio, atravesando todos los pozos. Cada
    segmento agrupa >= min_len muestras consecutivas.
    """
    segments = []
    for wn, well in wells.items():
        seg = []
        for p in well.points:
            ok = (p.grupo == group_id and p.entrenable
                  and p.vel is not None and np.isfinite(p.vel)
                  and p.se is not None and np.isfinite(p.se) and p.se < 800
                  and (p.di is None or p.di <= di_threshold))
            if ok:
                seg.append(p)
            else:
                if len(seg) >= min_len: segments.append((wn, seg))
                seg = []
        if len(seg) >= min_len: segments.append((wn, seg))
    return segments

def top_drilling(group_id, n=5, method="min_se_cv"):
    """
    Recomienda los N mejores segmentos de perforación de un dominio, según 3
    métodos posibles:

    - "min_se_cv": minimiza la VARIACIÓN INTERNA de SE dentro del segmento
      (coeficiente de variación dato a dato, cm a cm). Prioriza perforación
      MÁS ESTABLE/consistente, aunque su SE medio no sea el mínimo absoluto.
    - "min_se": minimiza directamente la SE media del segmento (menor energía
      específica = perforación más eficiente energéticamente).
    - "max_rop": maximiza la ROP media del segmento (mayor velocidad de
      penetración = mayor productividad).

    En los 3 casos, los segmentos candidatos pertenecen al MISMO dominio
    predicho por el modelo ML (grupo geomecánico), no se mezclan dominios.
    """
    segments = _segments_by_domain(group_id)
    if not segments:
        return []
    candidates = []
    for wn, seg in segments:
        se_arr = np.array([p.se for p in seg])
        vel_arr = np.array([p.vel for p in seg])
        se_cv = float(se_arr.std() / (se_arr.mean() or 1e-9))
        candidates.append({
            "well": wn, "largo": seg[len(seg)//2].largo, "n_pts": len(seg),
            "vel": float(vel_arr.mean()), "se": float(se_arr.mean()), "se_cv": round(se_cv, 4),
            "pp": float(np.mean([p.pp for p in seg])), "pr": float(np.mean([p.pr for p in seg])),
            "pa": float(np.mean([p.pa for p in seg])), "pd": float(np.mean([p.pd for p in seg])),
            "pf": float(np.mean([p.pf for p in seg])),
        })
    if not candidates: return []

    if method == "min_se_cv":
        ranked = sorted(candidates, key=lambda c: c["se_cv"])
    elif method == "min_se":
        ranked = sorted(candidates, key=lambda c: c["se"])
    elif method == "max_rop":
        ranked = sorted(candidates, key=lambda c: -c["vel"])
    else:
        ranked = candidates

    return ranked[:n]

def export_domain_csv():
    rows = []
    for d, info in domains.items():
        pts = [p for p in all_points() if p.dominio == d]
        ucs_ml_v = [p.ucs_ml for p in pts if p.ucs_ml]
        di_v = [p.di for p in pts if p.di is not None]
        rows.append({"dominio":d,"n":info["count"],"ucs_lab":info.get("ucs_lab"),
                     "ucs_ml_media":round(np.mean(ucs_ml_v),1) if ucs_ml_v else None,
                     "di_media":round(np.mean(di_v),3) if di_v else None,
                     "grupo": pts[0].grupo if pts else None})
    return pd.DataFrame(rows)

def export_predictions_csv():
    rows = []
    for wn, well in wells.items():
        for p in well.points:
            rows.append({
                "pozo":wn,"largo":p.largo,"este":p.este,"norte":p.norte,"cota":p.cota,
                "vel":p.vel,"pp":p.pp,"pr":p.pr,"pa":p.pa,"pd":p.pd,"pf":p.pf,"se":p.se,
                "dominio":p.dominio or "","lito":p.lito or p.lito_inferida or "",
                "estructura":p.estructura or p.estructura_inferida or "",
                "ucs_ml":p.ucs_ml,"ucs_ml_p10":p.ucs_ml_p10,"ucs_ml_p90":p.ucs_ml_p90,
                "ucs_confiable":p.ucs_confiable,"di":p.di,
                "grupo":p.grupo or "","entrenable":int(p.entrenable),
                "band_check":p.band_check or "",
            })
    return pd.DataFrame(rows)

# ─── VISOR 3D ─────────────────────────────────────────────────────────────────
COLOR_FIELDS = {
    "se":("SE [bar·min/m]",0,500,False),"vel":("ROP [m/min]",0,2.5,False),
    "pp":("Percusión [bar]",0,230,False),"pa":("Avance [bar]",0,150,False),
    "pr":("Rotación [bar]",0,100,False),"pd":("Damper [bar]",0,150,False),
    "pf":("Flujo [bar]",0,25,False),"ucs_ml":("UCS ML [MPa]",0,270,False),
    "ucs_confiable":("UCS confiable [MPa]",0,270,False),"di":("DI",0,3,False),
    "lito":("Litología DXF",None,None,True),"grupo":("Dominio agrupado",None,None,True),
    "lito_inferida":("Litología inferida",None,None,True),
    "band_check":("Consistencia de banda",None,None,True),
}

# Colores fijos para la consistencia de banda (categórico con semántica).
BAND_COLORS = {"compatible":"#2ECC71", "incompatible":"#E74C3C",
               "ambiguo":"#F1C40F", "—":"#7F8C8D"}

def _fmt_ucs_interval(p):
    """'182 [155–213] MPa' si hay intervalo; '182 MPa' o 'sin calcular'."""
    if p.ucs_ml is None:
        return "sin calcular"
    if p.ucs_ml_p10 is not None and p.ucs_ml_p90 is not None:
        return f"{p.ucs_ml:.0f} [{p.ucs_ml_p10:.0f}–{p.ucs_ml_p90:.0f}] MPa"
    return f"{p.ucs_ml:.0f} MPa"

REPORT_VARS = {
    "vel": "ROP [m/min]", "pp": "Percusión [bar]", "pa": "Avance [bar]",
    "pr": "Rotación [bar]", "pd": "Damper [bar]", "pf": "Flujo [bar]",
    "se": "SE [bar·min/m]", "di": "DI (discontinuidad)",
    "ucs_ml": "UCS ML [MPa]",
}

def well_basic_stats(well_name):
    """Estadísticas descriptivas básicas de un pozo: media, mediana, std, min, max por variable."""
    well = wells.get(well_name)
    if not well or not well.points: return {}
    stats = {}
    for k, label in REPORT_VARS.items():
        vals = np.array([getattr(p, k) for p in well.points
                         if getattr(p, k, None) is not None and np.isfinite(getattr(p, k))])
        if vals.size == 0: continue
        stats[k] = {
            "label": label, "media": float(np.mean(vals)), "mediana": float(np.median(vals)),
            "std": float(np.std(vals)), "min": float(np.min(vals)), "max": float(np.max(vals)),
            "n": int(vals.size),
        }
    return stats

def build_well_report_figure(well_name, hist_vars=None):
    """
    Reporte gráfico de un pozo: perfil DI vs profundidad (con línea de umbral) +
    histogramas de hasta 3 variables MWD seleccionadas por el usuario.
    """
    well = wells.get(well_name)
    if not well or not well.points:
        return go.Figure()
    hist_vars = hist_vars or ["se", "pp", "vel"]
    hist_vars = [v for v in hist_vars if v in REPORT_VARS][:3]
    n_hist = len(hist_vars)

    specs = [[{"colspan": max(n_hist,1)}] + [None]*(max(n_hist,1)-1)]
    if n_hist:
        specs.append([{"type":"xy"}]*n_hist)
    titles = ["DI vs. Profundidad"] + [f"Histograma {REPORT_VARS[v]}" for v in hist_vars]
    fig = make_subplots(
        rows=2 if n_hist else 1, cols=max(n_hist,1),
        specs=specs, subplot_titles=titles,
        row_heights=[0.55,0.45] if n_hist else [1.0], vertical_spacing=0.14,
    )

    largos = [p.largo for p in well.points]
    dis = [p.di if p.di is not None else None for p in well.points]
    fig.add_trace(go.Scatter(x=largos, y=dis, mode="lines", name="DI",
                              line=dict(color="#3B8BD4", width=1.5)), row=1, col=1)
    fig.add_hline(y=di_threshold, line_dash="dash", line_color="#E74C3C",
                  annotation_text=f"Umbral={di_threshold}", row=1, col=1)
    fig.update_xaxes(title_text="Profundidad [m]", row=1, col=1)
    fig.update_yaxes(title_text="DI", row=1, col=1)

    for i, v in enumerate(hist_vars):
        vals = [getattr(p, v) for p in well.points
                if getattr(p, v, None) is not None and np.isfinite(getattr(p, v))]
        fig.add_trace(go.Histogram(x=vals, marker_color=PALETTE[i % len(PALETTE)],
                                     name=REPORT_VARS[v], nbinsx=30), row=2, col=i+1)
        fig.update_xaxes(title_text=REPORT_VARS[v], row=2, col=i+1)

    fig.update_layout(
        template="plotly_dark", paper_bgcolor="#0d0d1a", plot_bgcolor="#0d0d1a",
        showlegend=False, margin=dict(l=40,r=20,t=50,b=40), height=520,
    )
    return fig

def build_3d_figure(color_by="se", hidden_layers=None, hidden_wells=None):
    """
    hidden_layers / hidden_wells: sets de nombres a OCULTAR (checkbox destildado).
    Se usa 'visible' (no se omite la traza) para que Plotly conserve el índice
    de trazas estable entre renders y uirevision funcione correctamente.
    """
    hidden_layers = hidden_layers or set()
    hidden_wells  = hidden_wells or set()
    fig = go.Figure()
    label, cmin, cmax, categorical = COLOR_FIELDS.get(color_by, ("",0,1,False))
    cat_map = {}
    if categorical:
        all_cats = sorted({getattr(p, color_by) or "—" for well in wells.values() for p in well.points})
        if color_by == "band_check":
            # Colores semánticos fijos (verde/rojo/amarillo/gris), no la paleta.
            cat_map = {c: BAND_COLORS.get(c, "#7F8C8D") for c in all_cats}
        else:
            cat_map = {c: PALETTE[i%len(PALETTE)] for i,c in enumerate(all_cats)}
    for idx, (name, layer) in enumerate(layers.items()):
        tris = layer.triangles
        if len(tris) == 0: continue
        x = tris[:,:,0].ravel(); y = tris[:,:,1].ravel(); z = tris[:,:,2].ravel()
        ii = list(range(0, len(tris)*3, 3))
        jj = list(range(1, len(tris)*3, 3))
        kk = list(range(2, len(tris)*3, 3))
        ucs_txt = f"UCS={layer.ucs_lab} MPa" if layer.ucs_lab else "sin UCS"
        col = PALETTE[idx % len(PALETTE)]
        fig.add_trace(go.Mesh3d(x=x,y=y,z=z,i=ii,j=jj,k=kk,opacity=0.28,name=name,color=col,
            hoverinfo="name+text",text=[f"{name} | {ucs_txt}"]*len(ii),
            showlegend=True,legendgroup="dxf",
            visible=True if name not in hidden_layers else "legendonly"))
    for wn, well in wells.items():
        pts = well.points
        if not pts: continue
        is_visible = True if wn not in hidden_wells else "legendonly"
        xs = [p.este for p in pts]; ys = [p.norte for p in pts]; zs = [p.cota for p in pts]
        # collar
        fig.add_trace(go.Scatter3d(x=[xs[0]],y=[ys[0]],z=[zs[0]],mode="markers",
            marker=dict(size=6,color="#111"),showlegend=False,
            hovertext=f"Collar {wn}: E={xs[0]:.1f} N={ys[0]:.1f} Z={zs[0]:.1f}",hoverinfo="text",
            visible=is_visible))
        if categorical:
            vals = [getattr(p, color_by) or "—" for p in pts]
            colors = [cat_map.get(v, "#888") for v in vals]
            hover = [f"<b>{wn}</b><br>{p.largo:.2f}m<br>{label}: {v}"
                     f"<br>UCS ML: {_fmt_ucs_interval(p)}"
                     f"<br>E={p.este:.1f} N={p.norte:.1f} Z={p.cota:.1f}"
                     for p,v in zip(pts,vals)]
            fig.add_trace(go.Scatter3d(x=xs,y=ys,z=zs,mode="lines+markers",name=wn,
                hovertext=hover,hoverinfo="text",line=dict(color="#333",width=1.5),
                marker=dict(size=2.5,color=colors,opacity=0.85),legendgroup="wells",
                visible=is_visible))
        else:
            # None (dato aún no calculado, ej. UCS antes de entrenar el ML) se
            # muestra explícito en el hover como "sin calcular" en vez de "0",
            # para no confundir "no hay dato" con "el valor real es 0".
            raw_vals_display = [getattr(p, color_by) for p in pts]
            raw_vals = [v if v is not None else 0 for v in raw_vals_display]
            hover = [f"<b>{wn}</b><br>{p.largo:.2f}m<br>{label}: "
                     f"{f'{vd:.2f}' if vd is not None else 'sin calcular'}"
                     f"<br>DI: {f'{p.di:.2f}' if p.di is not None else '—'}"
                     f"<br>UCS ML: {_fmt_ucs_interval(p)}"
                     f"<br>E={p.este:.1f} N={p.norte:.1f} Z={p.cota:.1f}"
                     for p,vd in zip(pts,raw_vals_display)]
            fig.add_trace(go.Scatter3d(x=xs,y=ys,z=zs,mode="lines+markers",name=wn,
                hovertext=hover,hoverinfo="text",line=dict(color="rgba(150,150,150,0.4)",width=1),
                marker=dict(size=2.5,color=raw_vals,colorscale="Plasma",cmin=cmin,cmax=cmax,
                            opacity=0.85,showscale=True,
                            colorbar=dict(title=dict(text=label,font=dict(size=10)),
                                          thickness=14,len=0.55,x=1.02)),legendgroup="wells",
                visible=is_visible))
    fig.update_layout(paper_bgcolor="#0d0d1a",
        scene=dict(
            xaxis=dict(title=dict(text="Este (UTM m)",font=dict(size=11)),gridcolor="#222"),
            yaxis=dict(title=dict(text="Norte (UTM m)",font=dict(size=11)),gridcolor="#222"),
            zaxis=dict(title=dict(text="Cota (m.s.n.m.)",font=dict(size=11)),gridcolor="#222"),
            bgcolor="#070711",aspectmode="data",camera=dict(eye=dict(x=1.6,y=1.6,z=0.9))),
        margin=dict(l=0,r=0,t=0,b=0),
        legend=dict(font=dict(size=10),bgcolor="rgba(0,0,0,0.5)",x=0.01,y=0.99,
                    bordercolor="#333",borderwidth=1),
        uirevision="viewport")
    return fig

# ─── APP DASH ─────────────────────────────────────────────────────────────────
app = dash.Dash(__name__, external_stylesheets=[dbc.themes.SLATE],
                title=f"{APP_TITLE} v{APP_VERSION}", suppress_callback_exceptions=True)

def card(title, body):
    return dbc.Card([
        dbc.CardHeader([html.B(title)], style={"fontSize":"12px","padding":"7px 12px"}),
        dbc.CardBody(body, style={"padding":"10px 12px"}),
    ], className="mb-2", color="dark", outline=True)

def wz_prereq(step):
    """
    Determina si se puede NAVEGAR a `step`. Se calcula el "techo" (máximo
    paso desbloqueado según los datos actuales) y se permite cualquier paso
    <= techo, incluyendo retroceder libremente a pasos ya visitados.

    IMPORTANTE: el prerequisito de cada paso N es lo que se necesita para
    ENTRAR a N, no lo que se logra completando N. Por ejemplo, el Paso 3 (DI)
    solo requiere tener pozos cargados —el DI se calcula DENTRO del paso 3,
    así que exigir 'DI ya calculado' para entrar sería una contradicción que
    deja al usuario atrapado sin poder nunca alcanzar ese paso.
    """
    reached = 1
    if bool(wells): reached = 3          # con pozos ya se puede ir a Calibración (2) y DI (3)
    if any(p.di is not None for p in all_points()): reached = 4   # con DI calculado, se desbloquea ML (4)
    if rf_model is not None: reached = 5  # con modelo entrenado, se desbloquea Dominios (5)
    return step <= reached

def step_pills(active):
    labels = ["1·Datos","2·Calibración","3·DI","4·ML","5·Dominios"]
    done = [wz_state['step1']['xml_loaded'],wz_state['step2']['cleaned'],
            wz_state['step3']['di_computed'],wz_state['step4']['model_trained'],
            wz_state['step5']['grouped']]
    pills = []
    for i, (lbl, d) in enumerate(zip(labels, done)):
        step_n = i+1
        pills.append(dbc.Button(("✓ " if d else "") + lbl,
            id={"type":"pill","index":step_n}, n_clicks=0,
            color="info" if step_n == active else ("success" if d else "secondary"),
            outline=step_n != active, size="sm", className="me-1", disabled=not wz_prereq(step_n)))
    return pills

app.layout = dbc.Container(fluid=True, style={"height":"100vh","padding":0,"overflow":"hidden"}, children=[
    dbc.Toast(id="toast", header="Notificación", is_open=False, duration=5500,
              style={"position":"fixed","top":10,"right":10,"zIndex":9999,"minWidth":"350px"}),
    dbc.Navbar(dbc.Container(fluid=True, children=[
        html.Span([f"⛏ {APP_TITLE} v{APP_VERSION}"],
                  style={"fontSize":"13px","fontWeight":700,"color":"#e0e0e0","marginRight":"12px"}),
        html.Div(id="pills-bar", className="d-flex align-items-center gap-1 flex-wrap flex-grow-1"),
        html.Div([html.Label("Color:", style={"fontSize":"11px","color":"#aaa","marginRight":"4px"}),
                  dcc.Dropdown(id="color-by",
                    options=[{"label":v[0],"value":k} for k,v in COLOR_FIELDS.items()],
                    value="se", clearable=False, style={"width":"155px","fontSize":"11px"})],
                 className="d-flex align-items-center"),
    ]), color="dark", dark=True, style={"minHeight":"46px","padding":"4px 12px"}),
    dbc.Row(style={"height":"calc(100vh - 46px)","margin":0}, children=[
        dbc.Col(width=4, style={"height":"100%","padding":0,"borderRight":"1px solid #222",
                                 "display":"flex","flexDirection":"column","background":"#0d0d1a"}, children=[
            html.Div(id="wz-content", style={"flex":1,"overflowY":"auto","padding":"10px"}),
            html.Div(style={"borderTop":"1px solid #222","padding":"8px","maxHeight":"210px",
                             "overflowY":"auto","background":"#0a0a14"}, children=[
                html.Small("CAPAS DXF Y POZOS", style={"color":"#555","letterSpacing":"1px","fontSize":"10px"}),
                html.Div(id="layer-tree"),
            ]),
        ]),
        dbc.Col(width=8, style={"height":"100%","padding":0,"position":"relative"}, children=[
            dcc.Loading(dcc.Graph(id="viewport-3d", figure=build_3d_figure(),
                                    style={"height":"100%"},
                                    config={"displayModeBar":"hover","scrollZoom":True}),
                        type="circle", color="#3B8BD4"),
            html.Div(id="center-info", style={"position":"absolute","top":"10px","left":"10px",
                "background":"rgba(0,0,0,0.6)","color":"#aaa","padding":"4px 10px",
                "fontSize":"10px","borderRadius":"4px","fontFamily":"monospace","zIndex":100}),
        ]),
    ]),
    dcc.Upload(id="up-dxf", multiple=True, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-xml", multiple=True, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-excel", multiple=False, children=html.Div(), style={"display":"none"}),
    dcc.Upload(id="up-geomech", multiple=False, children=html.Div(), style={"display":"none"}),
    dcc.Download(id="download"),
    dcc.Store(id="refresh", data=0),
    dcc.Store(id="active-step", data=1),
    dcc.Interval(id="ml-task-poll", interval=500, disabled=True),
    dcc.Store(id="report-well-name", data=None),
    dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle(id="well-report-title", children="Reporte de pozo")),
        dbc.ModalBody([
            html.Div([
                html.Small("Variables para histograma (máx. 3):", style={"color":"#aaa","marginRight":"8px"}),
                dcc.Dropdown(id="well-report-vars", options=[{"label":v,"value":k} for k,v in REPORT_VARS.items()],
                             value=["se","pp","vel"], multi=True, style={"fontSize":"11px","width":"420px","display":"inline-block"}),
            ], className="mb-2 d-flex align-items-center"),
            dcc.Graph(id="well-report-graph", config={"displayModeBar":False}),
            html.Div(id="well-report-stats-table"),
        ]),
        dbc.ModalFooter(dbc.Button("Cerrar", id="close-well-report", size="sm", color="secondary")),
    ], id="well-report-modal", size="xl", is_open=False),
])

@app.callback(
    Output("wz-content","children"), Output("pills-bar","children"),
    Input("active-step","data"), Input("refresh","data"),
)
def render_wizard(step, _):
    """
    Contenido del wizard y barra de pasos. Deliberadamente SEPARADO del
    callback de la figura 3D: cambiar de paso (o cargar datos) NO debe
    reconstruir el viewport, así la cámara y el estado de visibilidad de
    capas/pozos permanecen intactos.
    """
    renderers = {1:_step1,2:_step2,3:_step3,4:_step4,5:_step5}
    content = renderers.get(step, _step1)()
    pills = step_pills(step)
    return content, pills

@app.callback(
    Output("layer-tree","children"),
    Output("center-info","children"),
    Input("refresh","data"),
)
def render_layer_tree(_):
    """
    Árbol de capas/pozos con sus checkboxes de visibilidad. Se regenera solo
    cuando cambian los datos (nueva capa, nuevo pozo, UCS asignado) — NO cada
    vez que se togglea un checkbox, para no perder el estado del propio
    checkbox que el usuario acaba de clickear.
    """
    tree = _layer_tree()
    ct = f"Centro: N={global_center['norte']:.0f} E={global_center['este']:.0f} Z={global_center['cota']:.0f}" if global_center else ""
    return tree, ct

@app.callback(
    Output("viewport-3d","figure"),
    Input("refresh","data"), Input("color-by","value"),
    Input({"type":"vis-layer","index":ALL},"value"),
    Input({"type":"vis-well","index":ALL},"value"),
    State({"type":"vis-layer","index":ALL},"id"),
    State({"type":"vis-well","index":ALL},"id"),
)
def render_viewport(_, color_by, layer_vis_vals, well_vis_vals, layer_ids, well_ids):
    """
    Único callback que toca la figura 3D. Se dispara solo cuando cambian datos
    (refresh), el color, o los checkboxes de visibilidad — nunca al navegar
    entre pasos del wizard. uirevision="viewport" (fijo) preserva cámara.
    """
    hidden_layers = {lid["index"] for lid, v in zip(layer_ids, layer_vis_vals) if not v}
    hidden_wells  = {wid["index"] for wid, v in zip(well_ids,  well_vis_vals)  if not v}
    fig = build_3d_figure(color_by, hidden_layers, hidden_wells)
    return fig

def _layer_tree():
    items = []
    caseron_opts = [{"label": c, "value": c} for c in excel_caserones()]
    lito_opts = [{"label": l, "value": l} for l in excel_litologias()]
    for i, (name, layer) in enumerate(layers.items()):
        ucs_badge = dbc.Badge(f"{layer.ucs_lab} MPa", color="success", className="ms-1") \
                    if layer.ucs_lab else dbc.Badge("sin UCS", color="secondary", className="ms-1")
        band_badge = dbc.Badge(f"banda {layer.ucs_lo:.0f}–{layer.ucs_hi:.0f}", color="info",
                               className="ms-1") if layer.ucs_lo is not None and layer.ucs_hi is not None else None
        layer_children = [
            html.Div([
                dbc.Checkbox(id={"type":"vis-layer","index":name}, value=True,
                             style={"display":"inline-block","marginRight":"6px"}),
                html.Small([html.Span("●",style={"color":PALETTE[i%len(PALETTE)],"marginRight":"4px"}),
                            f"{layer.kind[:4]}: ", name, ucs_badge, band_badge], style={"fontSize":"11px"}),
            ], style={"display":"flex","alignItems":"center"}),
            dbc.Input(id={"type":"ucs-in","index":name}, type="number", placeholder="UCS [MPa]",
                      value=layer.ucs_lab, min=UCS_CONFIG["physical_min"], max=UCS_CONFIG["physical_max"],
                      step=1, size="sm", debounce=True, style={"fontSize":"10px","marginTop":"3px"}),
        ]
        # Etiquetado caserón×litología (T2). Los dropdowns solo se muestran si
        # hay Excel geomecánico cargado. Ids pattern-matching (contenido
        # regenerado) → nunca ids fijos.
        if caseron_opts:
            layer_children.append(dbc.Row([
                dbc.Col(dcc.Dropdown(id={"type":"caseron-sel","index":name}, options=caseron_opts,
                        value=layer.caseron, placeholder="Caserón…", clearable=True,
                        style={"fontSize":"10px"}), width=6),
                dbc.Col(dcc.Dropdown(id={"type":"lito-alias","index":name}, options=lito_opts,
                        value=layer.lito_alias, placeholder="Litología (alias)…", clearable=True,
                        style={"fontSize":"10px"}), width=6),
            ], className="g-1", style={"marginTop":"3px"}))
        items.append(dbc.ListGroupItem(layer_children,
            style={"padding":"5px 8px","background":"transparent","border":"none","borderBottom":"1px solid #222"}))
    for wn, well in wells.items():
        badge = ""
        if well.origin == "fallback_hole": badge = " ⚠ collar por fallback"
        elif well.origin == "no_dq": badge = " ⚠ sin DQ (ficticio)"
        elif well.origin == "ambiguous": badge = " ⚠ ambiguo (asignar DQ)"
        elif well.origin == "manual": badge = " ✎ DQ asignado manualmente"
        row = html.Div([
            dbc.Checkbox(id={"type":"vis-well","index":wn}, value=True,
                         style={"display":"inline-block","marginRight":"6px"}),
            html.Small([html.Span("○",style={"color":"#5DCAA5","marginRight":"4px"}), wn,
                        html.Span(badge, style={"color":"#F39C12","fontSize":"10px","marginLeft":"4px"})],
                       style={"fontSize":"11px"}),
            dbc.Button("📊", id={"type":"open-well-report","index":wn}, size="sm",
                       color="link", style={"fontSize":"12px","padding":"0 0 0 8px","marginLeft":"auto"}),
        ], style={"display":"flex","alignItems":"center"})
        item_children = [row]
        # Pozos ambiguos: dropdown de reasignación manual del DQ×hole (id
        # pattern-matching, sin ids fijos, para sobrevivir a la regeneración
        # del árbol). Al elegir se reinterpola y el origin pasa a "manual".
        if well.origin == "ambiguous" and well.dq_candidates:
            opts = [{"label": f"{_plan_short(c['plan_id'])} / hole {c['hole_id']} (err {c['err_pct']}%)",
                     "value": i} for i, c in enumerate(well.dq_candidates)]
            item_children.append(dcc.Dropdown(
                id={"type":"assign-dq","index":wn}, options=opts,
                placeholder="Asignar DQ×hole…", clearable=False,
                style={"fontSize":"10px","marginTop":"4px"}))
        items.append(dbc.ListGroupItem(
            item_children,
            style={"padding":"3px 8px","background":"transparent","border":"none","borderBottom":"1px solid #1a1a1a"}))
    return dbc.ListGroup(items, flush=True) if items else \
           html.Small("Sin datos.", style={"color":"#444","fontSize":"10px"})

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Input({"type":"ucs-in","index":ALL},"value"),
    State({"type":"ucs-in","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def update_ucs(values, ids, ref):
    changed = False
    for val, id_d in zip(values, ids):
        name = id_d["index"]
        if name in layers and val is not None:
            ucs = float(val)
            if UCS_CONFIG["physical_min"] <= ucs <= UCS_CONFIG["physical_max"]:
                layers[name].ucs_lab = ucs; changed = True
    if changed:
        build_domain_index()
        return ref+1
    return no_update

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"caseron-sel","index":ALL},"value"),
    Input({"type":"lito-alias","index":ALL},"value"),
    State({"type":"caseron-sel","index":ALL},"id"),
    State({"type":"lito-alias","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_layer_meta(caseron_vals, alias_vals, caseron_ids, alias_ids, ref):
    """
    Asigna caserón / alias de litología a las capas DXF y autocompleta su banda
    UCS desde el Excel geomecánico. Ids pattern-matching → sobrevive a la
    regeneración del árbol; no toca la figura 3D (eso es de render_viewport).
    """
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    # Solo actuar ante un cambio REAL de valor. Al regenerarse el árbol los
    # dropdowns se remontan y este callback se dispara con los mismos valores;
    # si no filtramos, cada disparo devolvería ref+1 y entraría en bucle.
    changed = False
    for val, id_d in zip(caseron_vals, caseron_ids):
        name = id_d["index"]
        if name in layers and layers[name].caseron != (val or None):
            layers[name].caseron = val or None; changed = True
    for val, id_d in zip(alias_vals, alias_ids):
        name = id_d["index"]
        if name in layers and layers[name].lito_alias != (val or None):
            layers[name].lito_alias = val or None; changed = True
    if not changed:
        return no_update, no_update, no_update
    filled = []
    for name, layer in layers.items():
        if layer.caseron and apply_layer_band(layer):
            filled.append(f"{name}→{layer.ucs_lo:.0f}–{layer.ucs_hi:.0f}")
    build_domain_index()
    if filled:
        return ref+1, "✅ Banda autocompletada: " + ", ".join(filled), True
    return ref+1, "Caserón/litología actualizado (sin banda coincidente).", True

@app.callback(
    Output("active-step","data"),
    Input({"type":"pill","index":ALL},"n_clicks"),
    State("active-step","data"),
    prevent_initial_call=True,
)
def nav(pill_clicks, current):
    """
    Navegación robusta con pattern-matching (ALL). Tanto los pills de la barra
    superior como los botones "Siguiente →" / "← Atrás" de cada paso usan el
    mismo id={"type":"pill","index":N}. Esto es inmune a que wz-content se
    regenere en cada refresh: Dash resuelve el callback por el patrón, no por
    un id fijo que podría no existir todavía en el layout.
    """
    ctx = callback_context
    if not ctx.triggered: return no_update
    # Ignorar disparos donde n_clicks es None (componente recién montado)
    triggered_id = ctx.triggered_id
    if triggered_id is None or not isinstance(triggered_id, dict):
        return no_update
    triggered_value = ctx.triggered[0]["value"]
    if not triggered_value:
        return no_update
    target = triggered_id["index"]
    if not wz_prereq(target): return no_update
    return target

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-dxf","contents"), State("up-dxf","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_dxf(contents_list, filenames, ref):
    if not contents_list: return no_update, no_update, no_update
    loaded, errs = [], []
    for content, fname in zip(contents_list, filenames):
        try:
            _, b64 = content.split(",", 1)
            raw = base64.b64decode(b64)
            with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as f:
                f.write(raw); tmp = f.name
            tris, _ = parse_dxf(tmp, fname)
            os.unlink(tmp)
            name = Path(fname).stem
            bmin = tris.reshape(-1,3).min(0)
            bmax = tris.reshape(-1,3).max(0)
            layers[name] = Layer(name=name, kind=guess_kind(fname), triangles=tris,
                                  bbox_min=bmin, bbox_max=bmax)
            if global_center is None:
                cx = (bmin[0]+bmax[0])/2; cy = (bmin[1]+bmax[1])/2; cz = (bmin[2]+bmax[2])/2
                set_center(norte=cy, este=cx, cota=cz)
            loaded.append(f"{name} ({len(tris)} tri)")
        except Exception as e:
            errs.append(f"{fname}: {e}")
    wz_state['step1']['dxf_loaded'] = bool(layers)
    msg = f"✅ DXF: {', '.join(loaded)}" + (f" | Err: {'; '.join(errs)}" if errs else "")
    return ref+1, msg, True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-xml","contents"), State("up-xml","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_xml(contents_list, filenames, ref):
    if not contents_list: return no_update, no_update, no_update
    dq_results, mw_by_hole, errs = {}, {}, []
    for content, fname in zip(contents_list, filenames):
        try:
            _, b64 = content.split(",", 1)
            raw = base64.b64decode(b64)
            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(raw); tmp = f.name
            try:
                root = ET.parse(tmp).getroot()
                root_tag = root.tag
            except: root_tag = ""
            if is_dq(fname, root_tag):
                dq = parse_dq(tmp, fname)
                dq_results[dq["plan_id"]] = dq
            else:
                mw = parse_mw(tmp, fname)
                key = f"{mw['plan_id']}_H{mw['hole_id'] or 'X'}"
                mw_by_hole.setdefault(key, []).append(mw)
            os.unlink(tmp)
        except Exception as e:
            errs.append(f"{fname}: {e}")
    counts = match_and_place_wells(dq_results, mw_by_hole)
    if wells:
        wz_state['step1']['xml_loaded'] = True
    parts = [f"✅ {len(mw_by_hole)} pozos MWD"]
    if counts["matched"]:   parts.append(f"{counts['matched']} matcheados")
    if counts["fallback"]:  parts.append(f"{counts['fallback']} por hermano ⚠")
    if counts["ambiguous"]: parts.append(f"{counts['ambiguous']} ambiguos ⚠ (reasignar)")
    if counts["no_dq"]:     parts.append(f"{counts['no_dq']} sin DQ ⚠")
    if errs: parts.append(f"Err: {'; '.join(errs)}")
    return ref+1, " · ".join(parts), True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-excel","contents"), State("up-excel","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_excel(content, fname, ref):
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        raw = base64.b64decode(b64)
        with tempfile.NamedTemporaryFile(suffix=Path(fname).suffix, delete=False) as f:
            f.write(raw); tmp = f.name
        rows = parse_excel(tmp); os.unlink(tmp)
        excel_data.clear(); excel_data.extend(rows)
        return ref+1, f"✅ Excel: {len(rows)} tiros.", True
    except Exception as e:
        return no_update, f"❌ Excel: {e}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("up-geomech","contents"), State("up-geomech","filename"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_geomech(content, fname, ref):
    """Carga el Excel geomecánico caserón×litología y reconstruye geomech_bands."""
    if not content: return no_update, no_update, no_update
    try:
        _, b64 = content.split(",", 1)
        raw = base64.b64decode(b64)
        with tempfile.NamedTemporaryFile(suffix=Path(fname).suffix, delete=False) as f:
            f.write(raw); tmp = f.name
        records = parse_geomech_excel(tmp); os.unlink(tmp)
        index_geomech_bands(records)
        # Reaplicar bandas a las capas que ya tengan caserón asignado.
        for layer in layers.values():
            if layer.caseron: apply_layer_band(layer)
        build_domain_index()
        n_cas, n_lit = len(excel_caserones()), len(excel_litologias())
        return ref+1, (f"✅ Excel geomecánico: {len(records)} bandas "
                       f"({n_cas} caserones, {n_lit} litologías)."), True
    except Exception as e:
        return no_update, f"❌ Excel geomecánico: {e}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-preview-cross","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_preview_cross(n, ref):
    """
    Ejecuta el cruce geométrico DXF↔MWD sin entrenar el modelo, para que el
    usuario vea de inmediato cuántos puntos MWD caen dentro de cada sólido y
    reciben UCS, antes de avanzar a los pasos de calibración/DI/ML.
    """
    if not n: return no_update, no_update, no_update
    if not layers:
        return no_update, "⚠ Carga al menos una malla DXF con UCS asignado primero.", True
    if not wells:
        return no_update, "⚠ Carga al menos un XML MWD primero.", True
    classify_all_wells()
    build_domain_index()
    all_pts = list(all_points())
    n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_dom = sum(1 for p in all_pts if p.dominio)
    return ref+1, f"✅ Cruce ejecutado: {n_dom}/{len(all_pts)} pts dentro de alguna malla, {n_ucs} con UCS asignado.", True

for btn_id, upload_id in [("btn-dxf","up-dxf"),("btn-xml","up-xml"),("btn-excel","up-excel"),
                          ("btn-geomech","up-geomech")]:
    app.clientside_callback(
        f"""function(n){{if(n){{var e=document.querySelector('#{upload_id} input[type=file]');if(e)e.click();}}return window.dash_clientside.no_update;}}""",
        Output(btn_id,"n_clicks"), Input(btn_id,"n_clicks"), prevent_initial_call=True,
    )

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-cal-apply","n_clicks"),
    [State(f"cal-{k}","value") for k in ("vel","pp","pa","pd","pr","pf")],
    State("refresh","data"), prevent_initial_call=True,
)
def do_cal(n, *args):
    if not n: return no_update, no_update, no_update
    vals = args[:6]; ref = args[6]
    for k, v in zip(("vel","pp","pa","pd","pr","pf"), vals):
        cal_factors[k] = float(v or 1.0)
    apply_calibration()
    wz_state['step2']['calibrated'] = True
    return ref+1, "✅ Calibración aplicada.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-cal-derive","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_derive(n, ref):
    if not n: return no_update, no_update, no_update
    derived = derive_cal_factors_from_excel()
    if not derived:
        return no_update, "⚠ Sin tiros comunes.", True
    cal_factors.update(derived); apply_calibration()
    return ref+1, f"✅ Factores: {derived}", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-prelim","n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_prelim(n, ref):
    if not n: return no_update, no_update, no_update
    s = train_prelim_from_excel()
    if "error" in s: return no_update, f"⚠ {s['error']}", True
    return ref+1, f"✅ Prelim: R²={s['r2']}, RMSE={s['rmse']} MPa", True

@app.callback(Output("refresh","data",allow_duplicate=True),
    Input("btn-cut","n_clicks"), State("val-cut","value"),
    State("refresh","data"), prevent_initial_call=True)
def do_cut(n, cut, ref):
    if not n: return no_update
    apply_inicio_filter(float(cut or 2.0))
    wz_state['step2']['cleaned'] = True
    return ref+1

@app.callback(Output("refresh","data",allow_duplicate=True),
    Input("btn-add-filt","n_clicks"),
    State("sel-norm-var","value"), State("sel-norm-method","value"),
    State("refresh","data"), prevent_initial_call=True)
def do_add_filt(n, var, method, ref):
    if not n: return no_update
    add_norm_filter(var, method)
    wz_state['step2']['cleaned'] = True
    return ref+1

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"rm-filt","index":ALL},"n_clicks"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_remove_filt(n_clicks_list, ref):
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict): return no_update, no_update, no_update
    triggered_value = ctx.triggered[0]["value"]
    if not triggered_value: return no_update, no_update, no_update
    idx = triggered_id["index"]
    ok = remove_filter(idx)
    if ok:
        return ref+1, "✅ Filtro eliminado, puntos recalculados.", True
    return no_update, "⚠ No se pudo eliminar el filtro.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input({"type":"assign-dq","index":ALL},"value"),
    State({"type":"assign-dq","index":ALL},"id"),
    State("refresh","data"), prevent_initial_call=True,
)
def on_assign_dq(values, ids, ref):
    """
    Reasigna manualmente el DQ×hole de un pozo ambiguo. El dropdown vive dentro
    del árbol de capas regenerado, por eso usa id pattern-matching
    {"type":"assign-dq","index":well_name} (no un id fijo). Al elegir un
    candidato se reinterpolan las coordenadas de los puntos con la MISMA
    interpolación lineal por p.t que usa on_xml, el origin pasa a "manual" y
    se dispara refresh.
    """
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if not isinstance(triggered_id, dict): return no_update, no_update, no_update
    triggered_value = ctx.triggered[0]["value"]
    if triggered_value is None: return no_update, no_update, no_update
    well_name = triggered_id["index"]
    well = wells.get(well_name)
    if not well: return no_update, no_update, no_update
    try:
        cand = well.dq_candidates[int(triggered_value)]
    except (IndexError, ValueError, TypeError):
        return no_update, "⚠ Candidato DQ inválido.", True
    collar, final_pt = cand["collar"], cand["final_pt"]
    well.collar, well.final_pt = collar, final_pt
    for p in well.points:
        p.este  = collar["este"]  + p.t*(final_pt["este"]  - collar["este"])
        p.norte = collar["norte"] + p.t*(final_pt["norte"] - collar["norte"])
        p.cota  = collar["cota"]  + p.t*(final_pt["cota"]  - collar["cota"])
    well.origin = "manual"
    log_warn(f'Pozo "{well_name}" reasignado manualmente a DQ '
             f'"{cand["plan_id"]}" hole={cand["hole_id"]} (err {cand["err_pct"]}%).')
    return ref+1, (f"✅ {well_name}: reasignado a {_plan_short(cand['plan_id'])} / "
                   f"hole {cand['hole_id']} (err {cand['err_pct']}%)."), True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-di","n_clicks"),
    State("di-window","value"), State("di-thresh","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_di(n, window, thresh, ref):
    if not n: return no_update, no_update, no_update
    di_config["window"] = int(window or 14)
    global di_threshold
    di_threshold = float(thresh or 1.5)
    compute_di()
    wz_state['step3']['di_computed'] = True
    all_pts = list(all_points())
    n_di = sum(1 for p in all_pts if p.di is not None)
    n_disc = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    return ref+1, f"✅ DI: {n_di} pts · {n_disc} discontinuidades", True

@app.callback(
    Output("ml-task-poll","disabled"),
    Input("btn-ml","n_clicks"),
    State("ucs-min","value"), State("ucs-max","value"),
    prevent_initial_call=True,
)
def do_ml(n, ucs_min_v, ucs_max_v):
    """
    Lanza el pipeline (cruce + índice + RF) en un hilo de fondo y activa el
    polling (dcc.Interval) que consulta task_state cada 500ms para actualizar
    la barra de progreso y el log en vivo, sin bloquear la UI de Dash.
    """
    if not n or task_state["running"]:
        return no_update
    ucs_range["ucs_min"] = float(ucs_min_v or UCS_CONFIG["default_min"])
    ucs_range["ucs_max"] = float(ucs_max_v or UCS_CONFIG["default_max"])
    th = threading.Thread(target=run_ml_task, args=(ucs_range["ucs_min"], ucs_range["ucs_max"]), daemon=True)
    th.start()
    return False  # habilita el Interval de polling

@app.callback(
    Output("ml-progress-bar","value"), Output("ml-progress-bar","label"),
    Output("ml-stage-label","children"), Output("ml-log-box","children"),
    Output("ml-task-poll","disabled",allow_duplicate=True),
    Output("refresh","data",allow_duplicate=True),
    Output("ml-result","children"),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("ml-task-poll","n_intervals"),
    State("refresh","data"), prevent_initial_call=True,
)
def poll_ml_task(_, ref):
    with task_lock:
        running = task_state["running"]
        progress = task_state["progress"]
        stage = task_state["stage"]
        log_lines = list(task_state["log"])
        done = task_state["done"]
        error = task_state["error"]
        result = task_state["result"]

    log_box = html.Div([
        html.Div(line, style={"fontFamily":"monospace","fontSize":"10px","color":"#8f8" if "✅" in line else ("#f88" if "❌" in line or "⚠" in line else "#aaa")})
        for line in log_lines[-40:]
    ], style={"maxHeight":"140px","overflowY":"auto","background":"#050508",
              "padding":"6px 8px","borderRadius":"4px","border":"1px solid #222"})

    if not done:
        return progress, f"{progress}%", stage, log_box, False, no_update, no_update, no_update, no_update

    # Tarea terminada (con o sin error): detener polling y refrescar la UI
    if error:
        return progress, f"{progress}%", stage, log_box, True, no_update, \
               dbc.Alert(error, color="warning"), f"⚠ {error}", True

    cv_display = f"{result['cv_r2_mean']}±{result['cv_r2_std']}" if result.get('cv_r2_mean') is not None else "—"
    badges = html.Div([
        dbc.Row([
            dbc.Col(dbc.Card(dbc.CardBody([html.Div(str(v),style={"fontSize":"17px","fontWeight":700}),
                html.Small(k,style={"color":"#aaa","fontSize":"10px"})], style={"padding":"6px 10px"}),
                color="dark"), width="auto")
            for k,v in [("R² in-sample",result["r2_train"]),("RMSE in-sample",f"{result['rmse_train']} MPa"),
                        ("RMSEA",result["rmsea"]),
                        ("R² CV (5-fold)",cv_display),
                        ("N",result["n_train"]),("Excl. caídas",result["n_excl_disc"])]
        ], className="g-1 mt-2"),
        dbc.Alert([
            html.Small([
                html.B("R² in-sample"), " mide el ajuste sobre los mismos datos usados para entrenar ",
                "(equivalente a evaluar con predict(X) sobre el 100% de los datos, sin holdout separado). ",
                html.B("R² CV (5-fold)"), " es la métrica honesta de generalización: cada fold se evalúa ",
                "con datos que el modelo nunca vio en ese pliegue. Para reportar en la memoria, usar la métrica CV.",
            ], style={"color":"#aaa","lineHeight":"1.5"})
        ], color="dark", style={"fontSize":"10px","padding":"6px 10px","marginTop":"6px"}),
    ])
    msg = f"✅ R² in-sample={result['r2_train']} | R² CV={cv_display} | RMSE={result['rmse_train']} MPa | N={result['n_train']}"
    return progress, f"{progress}%", stage, log_box, True, ref+1, badges, msg, True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-group","n_clicks"),
    State("tol-ucs","value"), State("tol-di","value"), State("tol-int","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_group(n, tucs, tdi, tint, ref):
    if not n: return no_update, no_update, no_update
    n_g = compute_domain_groups(float(tucs or 20), float(tdi or 0.15), float(tint or 2))
    return ref+1, f"✅ {n_g} grupos.", True

@app.callback(
    Output("refresh","data",allow_duplicate=True),
    Output("toast","children",allow_duplicate=True),
    Output("toast","is_open",allow_duplicate=True),
    Input("btn-pred","n_clicks"),
    State("tol-ucs","value"), State("tol-di","value"), State("tol-int","value"),
    State("refresh","data"), prevent_initial_call=True,
)
def do_pred(n, tucs, tdi, tint, ref):
    if not n: return no_update, no_update, no_update
    res = predict_unclassified(float(tucs or 20), float(tdi or 0.15), float(tint or 2))
    return ref+1, f"✅ {res['assigned']}/{res['total']} pts asignados.", True

@app.callback(
    Output("topn-result","children"),
    Input("btn-topn","n_clicks"),
    State("topn-domain","value"), State("topn-method","value"),
    prevent_initial_call=True,
)
def do_topn(n, group_id, method):
    if not n or not group_id: return no_update
    results = top_drilling(group_id, n=5, method=method)
    if not results:
        return dbc.Alert("Sin segmentos candidatos suficientes en este dominio (mín. 5 muestras continuas).",
                          color="warning", style={"fontSize":"11px","padding":"6px 10px"})
    method_labels = {"min_se_cv":"Mínima variación interna de SE","min_se":"Mínima SE","max_rop":"Máxima ROP"}
    header = dbc.Row([
        dbc.Col(html.Small("Pozo", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("Prof. [m]", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("ROP", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("SE", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("CV(SE)", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PP", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PR", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PA", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PD", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("PF", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("N", style={"color":"#888","fontWeight":700}), width=1),
    ], className="mb-1")
    body = [dbc.Row([
        dbc.Col(html.Small(r["well"], style={"color":"#3B8BD4"}), width=2),
        dbc.Col(html.Small(f"{r['largo']:.1f}", style={"color":"#ccc"}), width=1),
        dbc.Col(html.Small(f"{r['vel']:.2f}", style={"color":"#2ECC71"}), width=1),
        dbc.Col(html.Small(f"{r['se']:.1f}", style={"color":"#EF9F27"}), width=1),
        dbc.Col(html.Small(f"{r['se_cv']:.3f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pp']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pr']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pa']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pd']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(f"{r['pf']:.1f}", style={"color":"#aaa"}), width=1),
        dbc.Col(html.Small(str(r["n_pts"]), style={"color":"#666"}), width=1),
    ], className="mb-1 py-1", style={"borderBottom":"1px solid #1a1a1a"}) for r in results]
    return html.Div([
        dbc.Badge(f"Criterio: {method_labels.get(method,method)}", color="info", className="mb-2"),
        header, *body,
    ])

@app.callback(
    Output("download","data"),
    Input("btn-exp-dom","n_clicks"), Input("btn-exp-pred","n_clicks"),
    prevent_initial_call=True,
)
def do_export(*args):
    ctx = callback_context
    if not ctx.triggered: return no_update
    tid = ctx.triggered[0]["prop_id"].split(".")[0]
    if tid == "btn-exp-dom":
        return dcc.send_data_frame(export_domain_csv().to_csv, "dominios.csv", index=False)
    elif tid == "btn-exp-pred":
        return dcc.send_data_frame(export_predictions_csv().to_csv, "predicciones.csv", index=False)
    return no_update

@app.callback(
    Output("well-report-modal","is_open"),
    Output("report-well-name","data"),
    Output("well-report-title","children"),
    Input({"type":"open-well-report","index":ALL},"n_clicks"),
    Input("close-well-report","n_clicks"),
    State("well-report-modal","is_open"),
    prevent_initial_call=True,
)
def toggle_well_report(open_clicks, close_click, is_open):
    ctx = callback_context
    if not ctx.triggered: return no_update, no_update, no_update
    triggered_id = ctx.triggered_id
    if triggered_id == "close-well-report":
        return False, no_update, no_update
    if isinstance(triggered_id, dict) and triggered_id.get("type") == "open-well-report":
        val = ctx.triggered[0]["value"]
        if not val: return no_update, no_update, no_update
        wn = triggered_id["index"]
        return True, wn, f"Reporte de pozo — {wn}"
    return no_update, no_update, no_update

@app.callback(
    Output("well-report-graph","figure"),
    Output("well-report-stats-table","children"),
    Input("report-well-name","data"),
    Input("well-report-vars","value"),
)
def update_well_report(well_name, hist_vars):
    if not well_name or well_name not in wells:
        return go.Figure(), html.Div()
    fig = build_well_report_figure(well_name, hist_vars)
    stats = well_basic_stats(well_name)
    rows = [dbc.Row([
        dbc.Col(html.Small(s["label"], style={"color":"#ccc"}), width=3),
        dbc.Col(html.Small(f"media={s['media']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"mediana={s['mediana']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"std={s['std']:.2f}", style={"color":"#aaa"}), width=2),
        dbc.Col(html.Small(f"[{s['min']:.1f}, {s['max']:.1f}]", style={"color":"#aaa"}), width=3),
    ], className="mb-1") for s in stats.values()]
    table = html.Div([
        html.Hr(),
        html.Small("Estadísticas básicas", style={"color":"#666","letterSpacing":"1px"}),
        html.Div(rows, className="mt-2"),
    ])
    return fig, table

# ─── RENDERERS ────────────────────────────────────────────────────────────────
def _diagnostico_calce():
    if not layers or not wells: return None
    dxf_bmin = np.min([l.bbox_min for l in layers.values()], axis=0)
    dxf_bmax = np.max([l.bbox_max for l in layers.values()], axis=0)
    pts = list(all_points())
    if not pts: return None
    coords = np.array([[p.este, p.norte, p.cota] for p in pts])
    valid = np.all(np.isfinite(coords), axis=1)
    coords = coords[valid]
    if coords.size == 0: return None
    p_bmin = coords.min(0); p_bmax = coords.max(0)
    overlap = np.all(p_bmax >= dxf_bmin) and np.all(p_bmin <= dxf_bmax)
    if overlap:
        return dbc.Alert([
            html.B("✅ MWD y DXF calzan en la misma zona UTM."), html.Br(),
            html.Small(f"DXF: E=[{dxf_bmin[0]:.0f},{dxf_bmax[0]:.0f}] N=[{dxf_bmin[1]:.0f},{dxf_bmax[1]:.0f}] Z=[{dxf_bmin[2]:.0f},{dxf_bmax[2]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small(f"MWD: E=[{p_bmin[0]:.0f},{p_bmax[0]:.0f}] N=[{p_bmin[1]:.0f},{p_bmax[1]:.0f}] Z=[{p_bmin[2]:.0f},{p_bmax[2]:.0f}]", style={"color":"#aaa"}),
        ], color="success", style={"fontSize":"11px","padding":"7px 10px"})
    else:
        return dbc.Alert([
            html.B("⚠ MWD y DXF NO están en la misma zona UTM."), html.Br(),
            html.Small(f"DXF: E=[{dxf_bmin[0]:.0f},{dxf_bmax[0]:.0f}] N=[{dxf_bmin[1]:.0f},{dxf_bmax[1]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small(f"MWD: E=[{p_bmin[0]:.0f},{p_bmax[0]:.0f}] N=[{p_bmin[1]:.0f},{p_bmax[1]:.0f}]", style={"color":"#aaa"}), html.Br(),
            html.Small("Causa: DQ y MW de planes distintos, o TMatrix inconsistente.", style={"color":"#F39C12"}),
        ], color="warning", style={"fontSize":"11px","padding":"7px 10px"})

def _step1():
    all_pts = list(all_points())
    n_dxf, n_wells = len(layers), len(wells)
    n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_no_ucs = len(all_pts) - n_ucs
    n_excel = len(excel_data)
    diag = _diagnostico_calce()
    status_block = dbc.Alert([
        html.B("Etiquetado automático punto a punto"), html.Br(),
        html.Small("El cruce geométrico DXF ↔ MWD determina qué puntos tienen UCS."),
        html.Hr(style={"margin":"6px 0"}),
        dbc.Row([
            dbc.Col([html.Div(str(len(all_pts)),style={"fontSize":"22px","fontWeight":700}),
                     html.Small("Total MWD",style={"color":"#aaa"})], width=4),
            dbc.Col([html.Div(str(n_ucs),style={"fontSize":"22px","fontWeight":700,"color":"#2ECC71"}),
                     html.Small("Con UCS → ML",style={"color":"#aaa"})], width=4),
            dbc.Col([html.Div(str(n_no_ucs),style={"fontSize":"22px","fontWeight":700,"color":"#aaa"}),
                     html.Small("Sin UCS",style={"color":"#aaa"})], width=4),
        ]),
    ], color="dark", style={"fontSize":"12px"}) if all_pts else None
    return html.Div([
        html.H6("Paso 1 — Cargar datos", className="mb-3"),
        card("Mallas DXF", [
            html.Small("Sólidos 3DFACE en UTM. Asigna UCS a cada capa (panel inferior).",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📂 Cargar DXF ({n_dxf} cargadas)"], id="btn-dxf",
                       color="primary", outline=True, size="sm"),
        ]),
        card("Registros MWD (XML IREDES)", [
            html.Small("Archivos DQ (con TMatrix) + archivos MW. Se cargan juntos.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📊 Cargar XMLs ({n_wells} pozos)"], id="btn-xml",
                       color="primary", outline=True, size="sm"),
        ]),
        dbc.Button("🔎 Vista previa del cruce DXF↔MWD (opcional)", id="btn-preview-cross",
                   color="success", outline=True, size="sm", className="mb-2") if layers and wells else None,
        status_block, diag,
        card("Excel calibrador (opcional)", [
            html.Small("Promedios por tiro con UCS asignado.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"📈 Cargar Excel ({n_excel} tiros)"], id="btn-excel",
                       color="secondary", outline=True, size="sm"),
        ]),
        card("Excel geomecánico caserón×litología (bandas UCS/RMR/RQD/GSI)", [
            html.Small("Rangos de laboratorio por caserón×litología. Alimenta las "
                       "bandas [UCS_lo, UCS_hi] de las capas DXF y la verificación de "
                       "consistencia (Paso 5).",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button([f"🧪 Cargar Excel geomecánico ({len(geomech_bands['records'])} bandas)"],
                       id="btn-geomech", color="secondary", outline=True, size="sm"),
        ]),
        dbc.Row([
            dbc.Col(dbc.Alert("Carga al menos un XML MWD.", color="warning",
                              style={"fontSize":"11px","padding":"5px 10px"}) if n_wells == 0 else html.Div()),
            dbc.Col(dbc.Button("Siguiente →", id={"type":"pill","index":2}, color="info", size="sm",
                                disabled=n_wells == 0, className="float-end"), width="auto"),
        ], className="mt-3"),
    ])

def _step2():
    all_pts = list(all_points())
    active = sum(1 for p in all_pts if p.entrenable)
    n_excel = len(excel_data)
    var_labels = {"vel":"ROP [m/min]","pp":"Percusión","pa":"Avance",
                  "pd":"Damper","pr":"Rotación","pf":"Flujo"}
    def cal_row(k, lbl):
        raw_vals = [getattr(p, f"raw_{k}") for p in all_pts]
        if raw_vals and any(np.isfinite(v) for v in raw_vals):
            rng = f"raw:[{np.nanmin(raw_vals):.1f}, {np.nanmax(raw_vals):.1f}]"
        else: rng = "sin datos"
        return dbc.Row([
            dbc.Col(html.Small(lbl, style={"color":"#aaa"}), width=3),
            dbc.Col(dbc.Input(id=f"cal-{k}", type="number",
                               value=round(cal_factors.get(k, 1.0), 4),
                               step=0.0001, min=0.001, size="sm",
                               style={"fontSize":"11px"}), width=3),
            dbc.Col(html.Small(rng, style={"color":"#555","fontSize":"10px"}), width=6),
        ], className="g-1 mb-1")
    filter_items = [dbc.ListGroupItem([
        html.Small(f"{f['varName']} — {f['label']} [{f['lo']}, {f['hi']}]",
                   style={"fontSize":"11px","marginRight":"6px","flex":1}),
        dbc.Badge(f"-{f['removed']} pts", color="danger", className="me-2"),
        dbc.Button("✕", id={"type":"rm-filt","index":i}, size="sm", color="danger",
                   outline=True, style={"fontSize":"10px","padding":"0px 7px"}),
    ], className="d-flex align-items-center py-1 px-2") for i, f in enumerate(clean_filters)]
    return html.Div([
        html.H6("Paso 2 — Calibración y limpieza", className="mb-3"),
        card("Calibración de unidades", [
            html.Small("Factor = media_Excel / media_raw por variable.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            *[cal_row(k, l) for k, l in var_labels.items()],
            dbc.Row([
                dbc.Col(dbc.Button("Aplicar", id="btn-cal-apply", color="info",
                                    outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("Derivar del Excel", id="btn-cal-derive",
                                    color="secondary", outline=True, size="sm",
                                    disabled=n_excel == 0), width="auto"),
            ], className="g-1 mt-2"),
        ]),
        card("Entrenamiento preliminar con Excel", [
            html.Small("Modelo RF rápido con promedios por tiro. Se descarta al hacer ML real.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button(f"🧪 Entrenar preliminar ({n_excel} tiros)",
                       id="btn-prelim", color="warning", outline=True, size="sm",
                       disabled=n_excel == 0),
        ]) if n_excel else None,
        card("Filtros de limpieza (globales)", [
            dbc.Alert(f"Activos: {active}/{len(all_pts)} pts · {len(wells)} pozos",
                      color="info", style={"fontSize":"11px","padding":"4px 8px"}, className="mb-2"),
            dbc.Row([
                dbc.Col(html.Small("Corte emboquillado (m):", style={"color":"#aaa"}), width=5),
                dbc.Col(dbc.Input(id="val-cut", type="number", value=2.0, step=0.1,
                                   min=0, size="sm", style={"fontSize":"11px"}), width=3),
                dbc.Col(dbc.Button("Aplicar", id="btn-cut", size="sm",
                                    color="secondary", outline=True), width=4),
            ], className="g-1 mb-2"),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="sel-norm-var", value="se", clearable=False,
                    options=[{"label":l,"value":k} for k,l in
                             {"se":"SE","vel":"ROP","pp":"PP","pa":"AP","pr":"RP","pd":"DP","pf":"FP"}.items()],
                    style={"fontSize":"11px"}), width=4),
                dbc.Col(dcc.Dropdown(id="sel-norm-method", value="outliers_iqr", clearable=False,
                    options=[{"label":l,"value":v} for l,v in
                             [("IQR 1.5×","outliers_iqr"),("Q25-Q75","q25_q75"),
                              ("5%-95%","whisker5"),("Q10-Q90","quantile_reg")]],
                    style={"fontSize":"11px"}), width=5),
                dbc.Col(dbc.Button("+", id="btn-add-filt", size="sm",
                                    color="secondary", outline=True), width=3),
            ], className="g-1 mb-2"),
            dbc.ListGroup(filter_items, flush=True) if filter_items else
                html.Small("Sin filtros activos.", style={"color":"#555"}),
        ]),
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":1}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → DI", id={"type":"pill","index":3}, color="info", size="sm"),
                     width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _step3():
    all_pts = list(all_points())
    n_di = sum(1 for p in all_pts if p.di is not None)
    n_disc = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    return html.Div([
        html.H6("Paso 3 — Índice de discontinuidad (DI)", className="mb-3"),
        card("Fórmula", [
            html.Small("DIᵢ = √(Σⱼ βⱼ · zⱼ(i)²), ventana 14 muestras ≈ 26 cm.", style={"color":"#ccc"}),
            html.Br(), html.Br(),
            html.Small("Pesos Pucobre: PP=0.35, DP=0.25, FP=0.20, RP=0.20", style={"color":"#666"}),
        ]),
        card("Configuración", [
            dbc.Row([
                dbc.Col([html.Small("Ventana", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="di-window", type="number", value=di_config["window"],
                                     min=3, step=1, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Umbral", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="di-thresh", type="number", value=di_threshold,
                                     min=0.1, step=0.1, size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col(dbc.Button("🌀 Calcular DI", id="btn-di", color="info", size="sm",
                                    className="mt-3"), width=6),
            ], className="g-2 mb-2"),
        ]),
        dbc.Badge(f"DI: {n_di} pts · {n_disc} discontinuidades", color="success",
                  className="mb-2") if n_di else None,
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":2}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → ML", id={"type":"pill","index":4}, color="info", size="sm",
                                disabled=n_di == 0), width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _step4():
    all_pts = list(all_points())
    n_ucs = sum(1 for p in all_pts if p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_intact = sum(1 for p in all_pts if p.di is not None and p.di <= di_threshold
                   and p.entrenable and p.dominio and domains.get(p.dominio, {}).get("ucs_lab"))
    n_drops = sum(1 for p in all_pts if p.di is not None and p.di > di_threshold)
    return html.Div([
        html.H6("Paso 4 — Modelo ML (UCS)", className="mb-3"),
        dbc.Alert([f"Con UCS lab: {n_ucs}  ·  Roca intacta (DI≤{di_threshold}): {n_intact} → RF  ·  Caídas excluidas: {n_drops}"],
                  color="info", style={"fontSize":"11px","padding":"5px 10px"}, className="mb-2"),
        dbc.Row([
            dbc.Col([html.Small("UCS mín [MPa]", style={"color":"#aaa","display":"block"}),
                      dbc.Input(id="ucs-min", type="number", value=ucs_range["ucs_min"],
                                 min=UCS_CONFIG["physical_min"], step=5, size="sm",
                                 style={"fontSize":"11px"})], width=3),
            dbc.Col([html.Small("UCS máx [MPa]", style={"color":"#aaa","display":"block"}),
                      dbc.Input(id="ucs-max", type="number", value=ucs_range["ucs_max"],
                                 max=UCS_CONFIG["physical_max"], step=5, size="sm",
                                 style={"fontSize":"11px"})], width=3),
            dbc.Col(html.Small(f"Físico: [{UCS_CONFIG['physical_min']},{UCS_CONFIG['physical_max']}] MPa",
                                style={"color":"#555","fontSize":"10px","alignSelf":"flex-end"}), width=6),
        ], className="g-2 mb-2"),
        dbc.Button("🧠 Ejecutar Cruce + ML", id="btn-ml", color="info", size="sm",
                   disabled=task_state["running"]),
        html.Div([
            html.Small(id="ml-stage-label",
                       children=task_state["stage"] or "Sin ejecutar todavía.",
                       style={"color":"#aaa","display":"block","marginTop":"8px","marginBottom":"3px"}),
            dbc.Progress(id="ml-progress-bar", value=task_state["progress"],
                         label=f"{task_state['progress']}%", striped=task_state["running"],
                         animated=task_state["running"], style={"height":"18px"}),
            html.Div(id="ml-log-box", className="mt-2",
                     children=html.Div([
                         html.Div(line, style={"fontFamily":"monospace","fontSize":"10px","color":"#aaa"})
                         for line in task_state["log"][-40:]
                     ], style={"maxHeight":"140px","overflowY":"auto","background":"#050508",
                               "padding":"6px 8px","borderRadius":"4px","border":"1px solid #222"})),
        ], className="mb-2"),
        html.Div(id="ml-result", className="mb-2"),
        dbc.Row([
            dbc.Col(dbc.Button("← Atrás", id={"type":"pill","index":3}, color="secondary", outline=True, size="sm"), width="auto"),
            dbc.Col(dbc.Button("Siguiente → Dominios", id={"type":"pill","index":5}, color="info", size="sm",
                                disabled=rf_model is None), width="auto", className="ms-auto"),
        ], className="mt-3"),
    ])

def _domain_report_table():
    """
    Reporte de dominios geomecánicos detectados: litología, estructura,
    UCS-ML medio, DI medio y cantidad de tramos por dominio.
    """
    if not domain_groups:
        return dbc.Alert("Aún no se han agrupado dominios. Usa 'Agrupar dominios' primero.",
                          color="secondary", style={"fontSize":"11px","padding":"6px 10px"})
    rows = [gw_row for gw_row in sorted(domain_groups, key=lambda g: -g["count"])]
    def pct_compat(g):
        """% de puntos del dominio con banda compatible (sobre los evaluables)."""
        pts = g.get("pts", [])
        evaluados = [p for p in pts if p.band_check is not None]
        if not evaluados: return None
        comp = sum(1 for p in evaluados if p.band_check == "compatible")
        return 100.0 * comp / len(evaluados)
    def pct_cell(v):
        if v is None:
            return html.Small("—", style={"color":"#666"})
        color = "#2ECC71" if v >= 70 else ("#F1C40F" if v >= 40 else "#E74C3C")
        return html.Small(f"{v:.0f}%", style={"color":color, "fontWeight":700})
    header = dbc.Row([
        dbc.Col(html.Small("Dominio", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("Litología", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("Estructura", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("UCS-ML medio", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("DI medio", style={"color":"#888","fontWeight":700}), width=2),
        dbc.Col(html.Small("N tramos", style={"color":"#888","fontWeight":700}), width=1),
        dbc.Col(html.Small("% compat.", style={"color":"#888","fontWeight":700}), width=2),
    ], className="mb-1")
    body = [dbc.Row([
        dbc.Col(html.Small(g["id"], style={"color":"#3B8BD4","fontWeight":700}), width=1),
        dbc.Col(html.Small(g["lito"] or "—", style={"color":"#ccc"}), width=2),
        dbc.Col(html.Small(g["estructura"] or "—", style={"color":"#ccc"}), width=2),
        dbc.Col(html.Small(f"{g['ucsMean']:.1f} MPa", style={"color":"#2ECC71"}), width=2),
        dbc.Col(html.Small(f"{g['diMean']:.3f}", style={"color":"#EF9F27"}), width=2),
        dbc.Col(html.Small(str(g["count"]), style={"color":"#aaa"}), width=1),
        dbc.Col(pct_cell(pct_compat(g)), width=2),
    ], className="mb-1 py-1", style={"borderBottom":"1px solid #1a1a1a"}) for g in rows]
    return card(f"Dominios detectados ({len(domain_groups)})", [header] + body)

def _step5():
    all_pts = list(all_points())
    n_nodom = sum(1 for p in all_pts if not p.dominio)
    return html.Div([
        html.H6("Paso 5 — Dominios geomecánicos", className="mb-3"),
        card("Agrupación", [
            dbc.Row([
                dbc.Col([html.Small("Tol UCS", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-ucs", type="number", value=20, min=1, step=1,
                                     size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Tol DI", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-di", type="number", value=0.15, min=0.01, step=0.01,
                                     size="sm", style={"fontSize":"11px"})], width=3),
                dbc.Col([html.Small("Tramo (m)", style={"color":"#aaa","display":"block"}),
                          dbc.Input(id="tol-int", type="number", value=group_interval_m,
                                     min=0.5, step=0.5, size="sm", style={"fontSize":"11px"})], width=3),
            ], className="g-2 mb-2"),
            dbc.Button("🔀 Agrupar dominios", id="btn-group", color="info", outline=True, size="sm"),
        ]),
        _domain_report_table(),
        card("Predicción sin DXF", [
            html.Small(f"{n_nodom} pts sin dominio DXF recibirán grupo inferido.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Button("🎯 Ejecutar predicción", id="btn-pred", color="warning",
                       outline=True, size="sm", disabled=not domain_groups),
        ]),
        card("Recomendación Top-N de parámetros de perforación", [
            html.Small("Selecciona un dominio y el criterio de selección. Los segmentos "
                       "candidatos siempre pertenecen al mismo dominio predicho por el ML.",
                       style={"color":"#aaa","display":"block","marginBottom":"8px"}),
            dbc.Row([
                dbc.Col(dcc.Dropdown(id="topn-domain", clearable=False,
                    options=[{"label":f"{g['id']} ({g['lito'] or '—'} / {g['estructura'] or '—'})",
                              "value":g["id"]} for g in domain_groups],
                    value=domain_groups[0]["id"] if domain_groups else None,
                    style={"fontSize":"11px"}), width=5),
                dbc.Col(dcc.Dropdown(id="topn-method", clearable=False,
                    options=[
                        {"label":"Mínima variación interna de SE (cm a cm)","value":"min_se_cv"},
                        {"label":"Mínima SE (más eficiente energéticamente)","value":"min_se"},
                        {"label":"Máxima ROP (mayor productividad)","value":"max_rop"},
                    ], value="min_se_cv", style={"fontSize":"11px"}), width=5),
                dbc.Col(dbc.Button("Top-5", id="btn-topn", color="info", outline=True, size="sm"), width=2),
            ], className="g-1 mb-2") if domain_groups else
                html.Small("Agrupa dominios primero.", style={"color":"#555"}),
            html.Div(id="topn-result"),
        ]),
        card("Exportar", [
            dbc.Row([
                dbc.Col(dbc.Button("CSV dominios", id="btn-exp-dom", color="secondary",
                                    outline=True, size="sm"), width="auto"),
                dbc.Col(dbc.Button("CSV predicciones", id="btn-exp-pred", color="secondary",
                                    outline=True, size="sm"), width="auto"),
            ], className="g-1"),
        ]),
        dbc.Button("← Atrás", id={"type":"pill","index":4}, color="secondary", outline=True, size="sm", className="mt-3"),
    ])

if __name__ == "__main__":
    print(f"\n{'='*65}\n  {APP_TITLE} v{APP_VERSION}")
    print(f"  Formación Punta del Cobre — UCS: {UCS_CONFIG['default_min']}–{UCS_CONFIG['default_max']} MPa")
    print(f"{'='*65}")
    if IN_COLAB:
        try:
            from pyngrok import ngrok
            public_url = ngrok.connect(PORT)
            print(f"\n  ✅ URL: {public_url}\n")
        except Exception:
            print(f"\n  ⚠ Configura pyngrok:\n     !pip install pyngrok -q\n     !ngrok authtoken TU_TOKEN\n")
    else:
        print(f"\n  Abre: http://localhost:{PORT}\n")
    app.run(debug=False, host="0.0.0.0", port=PORT)
