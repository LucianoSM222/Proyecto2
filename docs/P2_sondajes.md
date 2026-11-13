# PARTE VI — P2 · Sondajes

## P2 — SONDAJES
#### Parser, desurvey y selección de pozos
**Modelo sugerido:** Sonnet con pensamiento extendido.

### Objetivo

Incorporar los sondajes con testigo como fuente de verdad independiente, y resolver la selección de qué pozos son relevantes para un conjunto dado de caserones.

### Tarea 2.1 — Lector de los seis CSV

Mapeo tolerante de nombres de columna: distintas minas usan `azimuth_utm` o `azimuth`, y algunas agregan `subunidad`. El lector debe aceptar variantes sin fallar.

Convertir el centinela `-999` a nulo en todos los campos numéricos. Normalizar códigos de estructura (mayúsculas y sinónimos: `V` y `vet` son lo mismo) contra el registro de alias de P1.

### Tarea 2.2 — Desurvey por curvatura mínima

Los pozos no son rectos. Implementación validada contra los 11 pozos MPC:

```python
def desurvey(collar_ENZ, surveys):
    """surveys: lista ordenada de (depth, azimuth, dip). dip negativo hacia abajo.
       Devuelve lista de (depth, Este, Norte, Cota)."""
    E, N, Z = collar_ENZ
    pts = [(0.0, E, N, Z)]
    for i in range(len(surveys) - 1):
        d1, a1, i1 = surveys[i]
        d2, a2, i2 = surveys[i + 1]
        md = d2 - d1
        if md <= 0:
            continue
        I1, A1 = math.radians(90 + i1), math.radians(a1)
        I2, A2 = math.radians(90 + i2), math.radians(a2)
        cb = math.cos(I2 - I1) - math.sin(I1) * math.sin(I2) * (1 - math.cos(A2 - A1))
        cb = max(-1.0, min(1.0, cb))
        b = math.acos(cb)
        rf = 1.0 if b < 1e-9 else 2 / b * math.tan(b / 2)   # factor de razón
        dN = md / 2 * (math.sin(I1)*math.cos(A1) + math.sin(I2)*math.cos(A2)) * rf
        dE = md / 2 * (math.sin(I1)*math.sin(A1) + math.sin(I2)*math.sin(A2)) * rf
        dZ = md / 2 * (math.cos(I1) + math.cos(I2)) * rf
        E += dE; N += dN; Z -= dZ
        pts.append((d2, E, N, Z))
    return pts
```

Más una función de interpolación lineal que devuelva la posición a una profundidad arbitraria, necesaria para ubicar tramos de litología, estructura y geomecánica.

*Criterio de aceptación:* los 11 pozos MPC deben desurveyarse sin excepción, y la banda sur debe reproducir 6 pozos, 1.102,4 m de litología y 148 estructuras en el rango de cota 263–359.

### Tarea 2.3 — Contactos derivados

La tabla de estructuras casi no registra contactos. Derivarlos de los **límites entre tramos consecutivos de la tabla de litología**, marcándolos con un tipo distinto (`contacto_derivado`) para no confundirlos con estructuras logueadas.

Estos contactos serán las etiquetas del discriminador fractura-contacto en una sesión posterior. Aquí solo hay que generarlos y almacenarlos.

### Tarea 2.4 — Intersección traza-malla en tres estados

Los sondajes se cargan **después** de las capas DXF. Usar la maquinaria existente de `points_in_mesh` con rayo vertical.

| estado | criterio | por defecto |
|---|---|---|
| **Intersecta** | algún punto de la traza cae dentro de alguna malla | seleccionado |
| **Cercano** | no intersecta, pero pasa a menos de una distancia configurable | no seleccionado, mostrando la distancia |
| **Lejano** | fuera de rango | no seleccionado |

Los pozos cercanos importan: aunque no toquen el caserón, siguen siendo útiles para la interpolación al modelo de bloques.

### Tarea 2.5 — Métricas por pozo

Junto a cada pozo de la lista, mostrar lo necesario para decidir sin abrirlo:

- metros de traza dentro de mallas
- qué unidades atraviesa y cuántos metros de cada una
- número de estructuras registradas
- RQD y RMR medianos del tramo intersectado
- distancia mínima a la malla más cercana (si no intersecta)

Un pozo que intersecta 2 m probablemente no sirve, y sin este dato se seleccionaría igual.

### Tarea 2.6 — Interfaz

Lista de pozos con casillas, ordenable por cualquier métrica, con el estado indicado visualmente y posibilidad de anulación manual en ambos sentidos. La selección debe persistir en el estado de la aplicación.

---

---


