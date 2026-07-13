# Datos de prueba reales (Pucobre)

- `DQMGN_*_P40_*.xml` — DrillQuality (DQ) IREDES, plan P40, 21 tiros.
- `MWMGN_*_P41H5_*.xml` — MWD del pozo H5, plan P41, 1743 muestras.
- `synthetic_bands.xlsx` — Fixture SINTÉTICO del Excel geomecánico
  caserón×litología, con el formato documentado (hoja `BUDGET_S_2026_V02`,
  encabezados en fila índice 2, columnas 2/3/23/24/25/26/27). Incluye la fila
  Metandesitas UCS `100 - 267` (mid=183.5). Lo usa `test_geomech.py` cuando no
  hay Excel real; se regenera solo si se borra.

El DXF `Metandesitas.dxf` (~21 MB, 70.842 caras) NO se versiona por tamaño.

Tests: `test_matching.py` (T1), `test_geomech.py` (T2/T3),
`test_validation.py` (T4, consistencia multipozo de mallas).

## Variables de entorno para los tests

- `GEOMECH_DXF` → ruta al DXF Metandesitas (necesario para el test e2e de
  clasificación 1437/1743).
- `GEOMECH_DQ` / `GEOMECH_MW` → por defecto usan los XML de esta carpeta.
- `GEOMECH_XLSX` → ruta al Excel geomecánico REAL
  (`geomecanica_de_caserones.xlsx`). Si se define, los tests lo usan en vez del
  fixture sintético para validar `parse_geomech_excel` (≥40 registros).
