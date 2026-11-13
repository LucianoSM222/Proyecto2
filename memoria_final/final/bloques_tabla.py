import sys, json, time
sys.path.insert(0, "/home/user/Proyecto2")
import geomech_wizard as gw, cargar_caserones as cc
t=time.time()
with open(cc.VOCABULARIO, encoding="utf-8") as f: gw.import_vocabulary(f.read())
gw.seed_param_registry()
with open(cc.PERFIL, encoding="utf-8") as f: gw.import_site_profile(f.read())
gw.load_project(sys.argv[1]); print("carga", time.time()-t, gw.di_activo(), gw.di_config["weights"], flush=True)
bm = gw.interpolate_block_model()
json.dump({"bloque_m": bm["bloque_m"], "di": [b["di"] for b in bm["bloques"]], "ucs": [b["ucs"] for b in bm["bloques"]],
           "caseron": [b["caseron"] for b in bm["bloques"]]}, open(sys.argv[2], "w"))
print("OK", bm["n_bloques"], time.time()-t)
