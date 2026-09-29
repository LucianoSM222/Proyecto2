# PARTE V — P1c · Adenda B · Registro de Brecha Hidrotermal

## ADENDA B (revisada) — Registro de Brecha Hidrotermal

### B.1 — La trampa documentada

**Comentario permanente en el registro.**

La hoja `UCS-TX` de `BRECHA_2.XLS` muestra una columna `σ1 [MPa]` con ocho probetas BHT y un promedio de **198,19 MPa** en la fila 14.

> **Ese promedio NO es el UCS.** Seis de las ocho probetas son ensayos triaxiales. El σ3 de cada una está en la hoja `Envolvente`, no en `UCS-TX`.

| probeta | σ3 | σ1 | | probeta | σ3 | σ1 |
|---|---|---|---|---|---|---|
| 2 BHT | **0** | 182,4 | | 7 BHT | **0** | 296,9 |
| 3 BHT | 6 | 192,5 | | 8 BHT | 9 | 222,1 |
| 4 BHT | 3 | 132,6 | | 10 BHT | 12 | 219,2 |
| 5 BHT | 6 | 152,0 | | 6 BHT | 3 | 187,9 |

Con los parámetros ajustados abajo, **6 MPa de confinamiento agregan cerca de 35%**: la envolvente predice σ1 ≈ 173 MPa para un material cuyo UCS es 128. Ahí está toda la diferencia entre 198 y 128.

Toda lectura futura de este libro **debe filtrar por σ3 = 0** antes de calcular estadísticas de UCS.

Nota adicional: la hoja `RocData` es la **entrada** de ese software, no su salida — un listado ensayo por ensayo (`TRX`, `UCS`, `UCS DEF`, `TID`) con identificador de probeta. RocData ajusta una envolvente a los pares (σ3, σ1) que recibe; no convierte usando módulo de Young ni velocidad de onda. `UCS DEF` es uniaxial con medición de deformabilidad.

### B.2 — Ajuste Hoek-Brown

Ajuste de roca intacta (s=1, a=0,5) sobre los **25 ensayos de compresión** del libro (15 triaxiales + 10 uniaxiales):

```
σci = 128,1 MPa      mi = 14,77      RMSE = 51,8 MPa
```

**Validado contra 18 ensayos brasileños que no entraron en el ajuste:** la envolvente predice σt = −8,63 MPa; lo medido da media −7,78, dentro del rango observado (−5,39 a −10,25). La forma de la envolvente es correcta.

### B.3 — Corroboración independiente por carga puntual

Campaña `PLT_MPC-NIVEL_175-CZ_06_Sector_CAS1004S_CAP_5`: 30 bloques irregulares de Brecha Hidrotermal con alteración silícea, MPC nivel 175, ensayados 30-03-2026 y 09-04-2026.

Separando por modo de rotura, que es lo que corresponde porque solo las roturas por matriz representan roca intacta:

```
por matriz         n=16   media 112,1   mediana 111,5   CV 0,563
por discontinuidad n=13   media 120,1   mediana 113,9   CV 0,353
promedio informe                        119,7
```

**Convergencia de cuatro métodos independientes** — dos laboratorios, tres tipos de ensayo, dos sectores:

| método | UCS |
|---|---|
| σci del ajuste Hoek-Brown (25 ensayos) | 128,1 |
| promedio de los 10 uniaxiales | 123,9 |
| carga puntual del informe (n=29) | 119,7 |
| carga puntual por matriz (n=16) | 112,1 |

### B.4 — Registro del atributo

```
Bht — Brecha Hidrotermal
  rol                 litologia
  nivel               unidad
  ucs_central         128,1
  ucs_banda_min       100        <- banda de confianza sobre el valor central
  ucs_banda_max       145
  dispersion_min      64,5       <- dispersión observada del material
  dispersion_max      296,9
  ucs_cv              0,57
  mi                  14,77
  sigma_t             -7,8
  fuente              "Hoek-Brown ajustado sobre 25 ensayos, BRECHA_2.XLS,
                       Laboratorio Punta del Cobre 19-06-2022.
                       Corroborado por carga puntual n=16 rotura por matriz,
                       CAS1004S nivel 175, marzo-abril 2026"
  calidad             1  (ensayo del sitio)
```

**Ampliar el esquema del atributo** con `ucs_central`, `dispersion_min`, `dispersion_max` y `ucs_cv`.

#### Distinción que debe quedar explícita en el código y en la memoria

> `ucs_banda_min/max` (100–145) es la **banda de confianza sobre el valor central**, no el rango de resistencia del material. Declarar 100–145 como rango del material afirmaría un CV de 0,09 —tan homogéneo como las lutitas— cuando cuatro métodos independientes miden 0,56.
>
> El modelo **entrena con el valor central**. La dispersión observada **gobierna el ancho del intervalo de predicción**.

**Prohibido** recortar valores por percentil: este proyecto rechazó explícitamente el filtrado por percentiles a favor de límites físicos. Los únicos filtros admitidos sobre probetas son físicos y trazables: modo de rotura por discontinuidad (estándar ISRM) y ensayos marcados `Inválido`.

Verificación registrada: excluir las probetas de densidad anómala (muestras 2 y 3, con 3,18 y 4,15 g/cm³) **no** produce el rango 100–145 — retira los valores altos 182,4 y 169,1 y baja la media a 110,9.

### B.5 — Alerta de variabilidad y techo del modelo

Si `ucs_cv > 0,35`, la interfaz muestra advertencia junto al atributo y el intervalo de predicción se ensancha.

Documentar:

> La granularidad de la etiqueta acota el techo del modelo. Con todos los puntos de Bht etiquetados en 128, el modelo no puede predecir nada distinto de 128 dentro de Bht: la resolución punto a punto no se cumple **para el UCS**. Sí se cumple para la asignación de dominio y para el DI. La variabilidad interna de Bht excede la resolución del modelo, y eso se declara como limitación.

### B.6 — Otros parámetros del mismo libro

- **Tracción indirecta** (`TI`): σt 4,57 a 21,99 MPa; media 14,9; CV 0,388. Una probeta marcada `Inválido` (ruptura tipo I) — **excluir**.
- **Ángulo de fricción básico** (`TT` / `Tres Núcleos`, tres núcleos ISRM): φb 26,57° a 30,29°.
- **Dureza Leeb** (`DS`): rebotes corregidos, FC = 0,9276.
- **Alteraciones observadas:** Silícea (mayoría de la carga puntual), Mineralizada (2 bloques), magnetita (CAP 5).
- **Densidad bimodal:** muestras 1–5 entre 3,15 y 4,15; muestras 6–10 entre 2,63 y 2,77. **No explica la variabilidad de UCS** — muestra 7 (ρ=2,63) da 296,9 y muestra 6 (ρ=2,64) da 69,0.

### B.7 — Recalcular traslape

Con Bht incorporada, recalcular la matriz de traslape entre todas las unidades y **reemplazar el resultado previo**. Usando la dispersión observada (64,5–296,9), Bht se traslapa con todas las demás unidades incluido el Albitófiro (274,3–304,9). Usando la banda de confianza (100–145), el panorama es distinto. **Reportar ambas** y explicar la diferencia — es material directo para la memoria.

---

---


