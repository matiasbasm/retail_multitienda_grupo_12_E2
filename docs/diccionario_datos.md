# Diccionario de datos · modelo estrella (esquema `gondola`)

**Grano de `fact_venta`: una fila es una línea de boleta válida de 2025, es decir, un producto vendido en una boleta.**
Una boleta válida no está duplicada, tiene fecha dentro de 2025 y monto neto mayor que cero. La boleta es una dimensión degenerada:
una visita del cliente = un `boleta_id` distinto. "Cliente activo" no es una tabla: se calcula en la capa semántica (`cadena/metricas.py`).

Todas las dimensiones tienen una **clave sustituta** (`*_key`, entero, PK) además de la clave del sistema de origen.

## fact_venta

| Campo | Significado de negocio | Origen | Regla de transformación | Unidad |
|---|---|---|---|---|
| `boleta_id` | Boleta (visita de compra). PK compuesta con `linea_n` | POS `boletas.boleta_id` | Duplicados exactos eliminados | id |
| `linea_n` | Número de línea dentro de la boleta. PK compuesta | POS `boleta_detalle.linea` | Renumerado 1..n: el origen repite el número en 408 pares de productos distintos | n° |
| `linea_origen` | Número de línea tal como venía del POS | POS `boleta_detalle.linea` | Sin cambio | n° |
| `fecha_key` | FK a `dim_fecha`: fecha de la boleta | POS `boletas.fecha` | 4 formatos → fecha; orden día-mes decidido con los datos | AAAAMMDD |
| `fecha_alt_key` | FK a `dim_fecha` (rol): fecha si las ambiguas se leyeran mes-día | POS `boletas.fecha` | Solo cambia en fechas con ambos números ≤ 12 | AAAAMMDD |
| `cliente_key` | FK a `dim_cliente` (0 = boleta anónima) | POS `boletas.cliente_id` | Nulo → 0 | clave |
| `producto_key` | FK a `dim_producto` | POS `boleta_detalle.sku` | SKU en mayúsculas y sin espacios | clave |
| `tienda_key` | FK a `dim_tienda` | POS `boletas.tienda_id` | — | clave |
| `medio_pago_key` | FK a `dim_medio_pago` | POS `boletas.medio_id` | — | clave |
| `campana_key` | FK a `dim_campana` (0 = sin campaña) | JSON de promociones | SKU en campaña, fecha dentro de la campaña y canal habilitado | clave |
| `cantidad` | Unidades vendidas | POS `boleta_detalle.cantidad` | Negativos → valor absoluto (error de signo, sin evidencia de devolución) | unidades |
| `precio_unitario` | Precio cobrado por unidad | POS `precio_unitario` (texto) | Texto → número (punto = miles) | $ nominales |
| `descuento_pct` | Descuento aplicado a la línea | POS `descuento` (3 notaciones) | "10%", "10" y "0,10" → 0,10 | fracción |
| `monto_nominal` | Venta de la línea | POS `monto_linea` (texto) | Texto → número; si no cuadra con cantidad × precio × (1 − descuento), se recalcula | $ nominales |
| `monto_real_dic` | Venta de la línea en pesos de diciembre | `monto_nominal` × IPC | Factor = índice dic ÷ índice del mes (variaciones de la API encadenadas) | $ dic-2025 |
| `costo_nominal` | Costo de la línea | cantidad × `maestro.costo_unitario` | Nulo si el SKU no está en el maestro | $ nominales |
| `margen_nominal` | Margen bruto de la línea | `monto_nominal − costo_nominal` | Nulo si no hay costo | $ nominales |
| `margen_real_dic` | Margen bruto en pesos de diciembre | `margen_nominal` × factor IPC | — | $ dic-2025 |

## dim_cliente

| Campo | Significado | Origen | Regla | Unidad |
|---|---|---|---|---|
| `cliente_key` | PK sustituta (0 = anónimo) | generado | 1..n ordenado por `cliente_id` | clave |
| `cliente_id` | Id del programa de fidelización | POS `clientes` | −1 para el anónimo | id |
| `fecha_alta` | Fecha de inscripción en el programa | POS `clientes.fecha_alta` | formatos mixtos → fecha | fecha |
| `fecha_alta_alt` | Fecha de alta si las ambiguas fueran mes-día | idem | solo cambian las ambiguas | fecha |
| `comuna`, `region`, `macrozona` | Ubicación del cliente | POS `comunas`, `regiones` | La Florida → Región Metropolitana (corrección manual) | texto |
| `segmento_actual` | Clásico / Plus / Black **hoy** | POS `clientes.segmento` | Se sobrescribe en el origen (SCD tipo 1): no sirve para cortar en el tiempo | texto |
| `tipo_nombre` | Persona o nombre de negocio | POS `clientes.nombre` | Prefijo Sr./Sra./Familia → persona | texto |
| `rut_valido` | El RUT tiene dígito verificador correcto | POS `clientes.rut` | Módulo 11 | sí/no |
| `rut_rango_empresa` | RUT ≥ 50 millones (persona jurídica) | idem | Convención SII | sí/no |

## dim_producto

| Campo | Significado | Origen | Regla | Unidad |
|---|---|---|---|---|
| `producto_key` | PK sustituta | generado | 1..n | clave |
| `sku` | Código del producto | maestro CSV | Mayúsculas; filas basura eliminadas; SKU repetido → registro activo | texto |
| `nombre`, `subcategoria`, `marca`, `proveedor` | Descripción | maestro CSV | Sin espacios sobrantes | texto |
| `categoria` | Categoría | maestro CSV | Variantes de escritura → forma canónica | texto |
| `costo_unitario`, `precio_lista` | Costo y precio de lista vigentes | maestro CSV (texto) | Texto → número | $ nominales |
| `activo` | Producto activo en el maestro | maestro CSV (Sí/si/1/…) | → sí / no / desconocido | sí/no |
| `en_maestro` | El SKU existe en el maestro | generado | Falso para los SKU vendidos que no están en el maestro (miembro "Sin maestro", sin costo) | sí/no |

## dim_tienda

| Campo | Significado | Origen | Regla | Unidad |
|---|---|---|---|---|
| `tienda_key` | PK sustituta | generado | 1..n | clave |
| `tienda_id`, `tienda` | Id y nombre del local | POS `tiendas` | — | texto |
| `formato` | Express, Supermercado, Híper, Online | POS `tiendas.formato` | "Hiper" → "Híper" | texto |
| `canal` | Presencial o Web | derivado de `formato` | Online → Web | texto |
| `comuna`, `region`, `macrozona` | Ubicación del local | POS | — | texto |

## dim_fecha · dim_medio_pago · dim_campana

| Tabla | Campos | Notas |
|---|---|---|
| `dim_fecha` | `fecha_key` (PK, AAAAMMDD), `fecha`, `anio`, `mes`, `nombre_mes`, `trimestre`, `dia_semana`, `es_fin_de_semana` | Un día por fila de 2025. Dimensión de rol doble (`fecha_key` y `fecha_alt_key`) |
| `dim_medio_pago` | `medio_pago_key` (PK), `medio_id`, `medio` | Efectivo, débito, crédito, otros |
| `dim_campana` | `campana_key` (PK; 0 = sin campaña), `campana_id`, `nombre`, `tipo`, `fecha_ini`, `fecha_fin`, `descuento_pct`, `canales` | Descuento normalizado a fracción |

## Medidas de la capa semántica (`cadena/metricas.py`)

| Medida | Fórmula | Unidad |
|---|---|---|
| Cliente activo (d, W) | Al menos una boleta en (d − W, d] | — |
| RBA_W | activos en la fecha base que siguen activos al 31-dic ÷ activos en la fecha base | % de clientes |
| Índice de reposición | nuevos activos al cierre ÷ perdidos de la base | nuevos por perdido |
| NNV_H | nuevos con H días observables sin 2ª boleta en H días ÷ esos nuevos | % de clientes |
| Retención trimestral | clientes del trimestre T que compran en T+1 ÷ clientes de T | % de clientes |
| Margen no capturado | (proyección de los perdidos × realización de los retenidos − gasto real de los perdidos) × margen % | $ dic-2025 |
