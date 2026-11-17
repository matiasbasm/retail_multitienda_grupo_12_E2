# Multitienda del Sur · Proyecto BI, Entrega 2

**IIC 3752 Tecnologías para Inteligencia de Negocios · Ingeniería UC · 2º semestre 2026 · Grupo 12**
Matías Bas · Pablo Solís · Samuel Donoso · Gonzalo San Martín

**Pregunta de negocio:** ¿La cadena está reteniendo a sus clientes o los está reponiendo con compradores de una sola vez?

Este repositorio contiene la cadena de datos completa y el prototipo (tablero) de la Entrega 2. Un comando corre todo de cero:
lee las cuatro fuentes, prueba su calidad, aplica las decisiones de limpieza, construye el modelo estrella, calcula la métrica
y deja las cifras del informe. El tablero lee lo que deja la cadena, así que muestra los mismos números que el informe.

---

## Cómo reproducir

### 1. Instalar (una vez, ~1 minuto)

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/sjdonosoa/retail_multitienda_grupo_12_E2.git
cd retail_multitienda_grupo_12_E2
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Correr la cadena (~10 segundos)

```bash
python run.py
```

Para probar qué pasa si la API del IPC está caída: `python run.py --sin-api`.

### 3. Qué se espera ver al final

La consola muestra las 30 pruebas de calidad y termina con:

```
===== Corrida ... · OK en ~6 s · pruebas 30/30 OK =====
RBA_90     RBA con W = 90 (principal), base 31-03          36.2  %
RBA_30     RBA con W = 30 (alternativa), base 31-03        14.3  %
RET_TRIM   Retención trimestral T1→T2 / T2→T3 / T3→T4      66.4 / 61.4 / 51.9  %
...
```

Todas las cifras del informe quedan en **`salidas/cifras_informe.csv`**, cada una con una etiqueta estable (por ejemplo, `RBA_90`).

### 4. Abrir el prototipo

```bash
streamlit run app/tablero.py
```

Se abre en el navegador en `http://localhost:8501`. Si la base todavía no existe (por ejemplo, la primera vez en Streamlit Cloud),
el tablero corre la cadena solo antes de mostrarse.

---

## Cómo está armada la cadena

```
 FUENTES                     1. RECEPCIÓN            2. BODEGA                   3. GÓNDOLA                 CONSUMO
 origen_pos.sqlite     ──▶   copia exacta,      ──▶  detección (29 problemas) ──▶ modelo estrella:      ──▶  tablero (Streamlit)
 maestro (CSV)               huella y fecha          + decisiones de limpieza     1 hecho + 6 dimensiones    cifras del informe
 promociones (JSON)          (data/recepcion/)       (DuckDB · esquema bodega)    (DuckDB · esquema gondola)       ▲
 API IPC mindicador.cl                                                                     │                    │
                                                                                 CAPA SEMÁNTICA: cadena/metricas.py
                                                                                 (la métrica escrita una sola vez)
```

| Paso | Carpeta / archivo | Qué hace | Por qué existe |
|---|---|---|---|
| 1. Recepción | `cadena/recepcion.py` | Copia cada fuente tal como llegó, con su huella y fecha; consulta la API del IPC con respaldo | Si una fuente cambia o falla, queda la copia de lo que se usó |
| 2. Bodega | `cadena/bodega/` | Detecta problemas (`deteccion.py`) y aplica decisiones (`limpieza.py`) | La limpieza se decide una vez y queda registrada |
| 3. Góndola | `cadena/gondola.py` | Modelo estrella: `fact_venta` + 6 dimensiones con claves sustitutas | Es lo único que consume el tablero |
| Capa semántica | `cadena/metricas.py` | RBA, reposición, NNV, retención trimestral, caso de negocio | Informe y tablero usan la misma fórmula: no pueden diferir |
| Pruebas | `cadena/calidad.py` | 30 pruebas por fuente, modelo y métrica (bloquean o avisan) | Un número malo no se publica |
| Parámetros | `config/parametros.yaml` | Ventanas, fechas, supuestos del caso de negocio, SLA | Toda decisión del grupo en un solo lugar |

Las decisiones de arquitectura (ELT, carga completa, falla de la API), las pruebas, el linaje y el acuerdo de servicio están en
[`docs/arquitectura.md`](docs/arquitectura.md). El diccionario de datos está en [`docs/diccionario_datos.md`](docs/diccionario_datos.md).

## Qué se versiona y qué no

```
├── run.py                     Un comando: corre la cadena completa
├── config/parametros.yaml     Parámetros y supuestos
├── cadena/                    Código de los pasos, la capa semántica y las pruebas
├── app/tablero.py             Prototipo
├── data/fuentes/              Fuentes originales (nunca se modifican desde el código, salvo el respaldo de la API)
├── salidas/cifras_informe.csv Cifras del informe de la última corrida
├── docs/                      Arquitectura, diccionario de datos, acta de la reunión
│
├── data/recepcion/            (no se sube) copia de recepción de la última corrida
├── data/almacen.duckdb        (no se sube) base con los esquemas bodega, gondola y operacion
└── salidas/calidad, tablas/   (no se sube) un CSV por problema detectado, tablas de soporte, log y resultado de pruebas
```

## Declaración de uso de IA

Se usó Claude (Anthropic) para trasladar el notebook de la Entrega 1 a la cadena por pasos, escribir el tablero y redactar
borradores de la documentación. Las definiciones de la métrica, las decisiones de limpieza y la recomendación son del grupo.
Las cifras de la cadena se compararon automáticamente contra las del notebook de la E1 (todas iguales salvo el rango por formato,
explicado en el registro de mejora). **Pendiente del grupo:** anotar aquí qué verificó cada integrante a mano antes de la entrega.
