# PARTE II — Decisiones cerradas

### Decisiones cerradas en esta ronda

**Caserones.** Descartados 1501, 1502 y 1055 (sin capas ni sondaje). Selección:

| rol | caserón | sector | aporte |
|---|---|---|---|
| entrena | **1043** | PCS | gran variedad litológica, mucho MWD |
| entrena | **0042** | PCC, nivel 295 | Bht + lavas, mucho MWD, capas en mano |
| entrena | **1059** | PCS | aporta brecha mixta |
| **prueba** | **1541** | PCC | estrecho: lavas + albitófiro, ambas presentes en los de entrenamiento |
| demostración | CAP 5 | PCS | dos diques de resistencia desconocida — **fuera del entrenamiento** |

Geología confirma que 1043, 0042 y 1059 contienen las litologías presentes en 1541. **MPC Centro y MPC Sur son contiguos y comparten el mismo tipo de geología**, de modo que el conjunto es geológicamente coherente.

La asignación entrenamiento/prueba es **parámetro de ejecución**, no constante de código.

**Alteraciones.** No son dimensión obligatoria del dominio. Los dominios se definen por litología + estructura. La alteración se **registra cuando viene en el dato** (la carga puntual trae Silícea; CAP 5 trae magnetita) y se activa como dimensión solo en un experimento nombrado.

**Campos `Val`.** Se usan exactamente siete: `LT | ROP | PP | FP | DP | RP | FLP`. Todo campo excedente se descarta del uso, pero **se reporta una vez en la carga** ("se encontraron 8 campos, se usaron 7"). Descarte silencioso está prohibido.

**Volumen.** 15 abanicos × 10 tiros × 35 m ≈ **5.250 m y 262.500 registros por caserón**, ~150 pozos. Cuatro caserones superan el millón de puntos.

---


