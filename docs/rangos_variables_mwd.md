# Rangos de las variables MWD

Cuatro caserones de MPC (PCC_0042, PCC_1541, PCS_1043 y PCS_1059): 928 pozos.
Se reportan dos conjuntos:

- **Todos los registros**: 982.420 registros, sin ninguna depuración.
- **Registros entrenables**: 881.536 registros que quedan después de la
  limpieza estándar. Se excluyen el cambio de barra, la regulación automática
  de la percusión, el emboquillado por meseta, la PP fuera de 90–230 bar y los
  saltos en la continuidad del registro (100.884 registros en total).

Siglas según el XML IREDES. La columna «Registros en 0» cuenta los valores
exactamente iguales a cero.

## Todos los registros (n = 982.420)

| Variable | Descripción | Unidad | Mínimo | Máximo | Media | Mediana | Registros en 0 |
|---|---|---|---:|---:|---:|---:|---:|
| PR | Velocidad de penetración | m/min | 0,00 | 945,39 ¹ | 1,00 | 0,94 | 19.950 |
| PP | Presión de percusión | bar | 0,0 | 230,6 | 195,1 | 211,4 | 1.224 |
| FP | Presión de avance | bar | 0,0 | 136,4 | 75,2 | 75,0 | 6 |
| DP | Presión del dámper | bar | 15,0 | 225,0 | 96,5 | 100,3 | 0 |
| RP | Presión de rotación | bar | 0,0 | 142,6 | 48,3 | 46,7 | 9 |
| FLP | Presión del flujo de barrido | bar | 1,9 | 24,6 | 7,8 | 8,0 | 0 |
| PEP | Presión específica de penetración, (PP + RP + FP) / PR | bar·min/m | 0 | sin cota ² | — ² | 344,7 | 3 |

## Registros entrenables (n = 881.536)

| Variable | Descripción | Unidad | Mínimo | Máximo | Media | Mediana | Registros en 0 |
|---|---|---|---:|---:|---:|---:|---:|
| PR | Velocidad de penetración | m/min | 0,00 | 8,85 | 0,98 | 0,97 | 3.321 ³ |
| PP | Presión de percusión | bar | 90,1 | 229,9 | 203,7 | 217,6 | 0 |
| FP | Presión de avance | bar | 1,8 | 136,4 | 77,3 | 76,5 | 0 |
| DP | Presión del dámper | bar | 22,8 | 214,7 | 99,5 | 101,4 | 0 |
| RP | Presión de rotación | bar | 1,8 | 137,5 | 48,5 | 46,8 | 0 |
| FLP | Presión del flujo de barrido | bar | 2,9 | 11,0 | 7,8 | 8,1 | 0 |
| PEP | Presión específica de penetración, (PP + RP + FP) / PR | bar·min/m | 28,8 | sin cota ² | — ² | 346,4 | 0 |

## Notas

1. **PR máxima de 945 m/min.** Es un valor sin sentido físico para un Simba
   E70S. Corresponde a registros aislados que la limpieza estándar ya retira:
   en los entrenables, el máximo baja a 8,85 m/min.
2. **PEP sin cota.** La PEP divide por la PR. Cuando la PR es cero o casi
   cero, el cociente crece sin límite: el máximo registrado es del orden de
   4·10¹¹ bar·min/m, y la media queda dominada por esos pocos registros. Por
   eso, para la PEP solo se informan el mínimo y la mediana.
3. **PR = 0 en registros entrenables.** El filtro de cambio de barra retira
   solo las detenciones que caen sobre la grilla de 1,756 m del pozo. Las
   3.321 detenciones que quedan fuera de esa grilla siguen como entrenables.
   Los análisis que usan la PEP aplican además un mínimo de PR (por ejemplo,
   PR ≥ 0,2 m/min).

Cálculo: `rangos.py` (scratchpad de la sesión), corrido el 2026-11-11 sobre la
carga completa con la limpieza estándar vigente.
