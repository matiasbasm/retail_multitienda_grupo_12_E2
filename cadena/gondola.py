"""Paso 3 · GÓNDOLA: el modelo estrella, listo para que lo use la gerencia.

Lee SOLO el esquema `bodega` y escribe el esquema `gondola`.

UNA tabla de hechos (corrección de la E1: el modelo anterior tenía dos y era una galaxia):
  fact_venta · grano: "una fila es una línea de boleta válida de 2025: un producto vendido en una boleta".

Seis dimensiones, todas con clave sustituta (*_key, entero) además de la clave del sistema de origen:
  dim_fecha (rol doble: fecha de la boleta y fecha en la lectura alternativa mes-día),
  dim_cliente, dim_producto, dim_tienda, dim_medio_pago, dim_campana.

La boleta es una dimensión degenerada (boleta_id vive en el hecho): una visita = un boleta_id distinto.
"Cliente activo" NO se guarda como tabla: se calcula en la capa semántica (metricas.py) desde fact_venta.
"""
import numpy as np
import pandas as pd

from .almacen import guardar, leer

MACROZONA = {"Metropolitana": "Metropolitana", "Valparaíso": "Centro sur", "Biobío": "Centro sur",
             "Araucanía": "Sur", "Los Lagos": "Sur"}
NOMBRE_MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
RUT_EMPRESA_DESDE = 50_000_000   # convención del SII para personas jurídicas (conocimiento externo)


def construir(p, log, con):
    b = {t: leer(con, "bodega", t) for t in ["boletas", "detalle", "clientes", "productos", "comunas", "regiones",
                                            "tiendas", "medios_pago", "campanas", "campana_sku", "ipc"]}
    ini, fin = p["periodo"]["inicio"], p["periodo"]["fin"]

    # ---------------- dim_fecha
    fechas = pd.date_range(ini, fin, freq="D")
    dim_fecha = pd.DataFrame({"fecha_key": fechas.strftime("%Y%m%d").astype(int), "fecha": fechas, "anio": fechas.year,
                              "mes": fechas.month, "nombre_mes": [NOMBRE_MES[i - 1] for i in fechas.month],
                              "trimestre": fechas.quarter, "dia_semana": fechas.dayofweek + 1, "es_fin_de_semana": fechas.dayofweek >= 5})

    # ---------------- dim_tienda
    t = (b["tiendas"].merge(b["comunas"], on="comuna_id", how="left").merge(b["regiones"], on="region_id", how="left")
         .rename(columns={"nombre": "tienda"}))
    t["formato"] = t["formato"].replace({"Hiper": "Híper"})
    t["canal"] = np.where(t["formato"] == "Online", "Web", "Presencial")
    t["region"] = t["region"].fillna("Sin región")
    t["macrozona"] = t["region"].map(MACROZONA).fillna("Sin macrozona")
    t = t.sort_values("tienda_id").reset_index(drop=True)
    t.insert(0, "tienda_key", range(1, len(t) + 1))
    dim_tienda = t[["tienda_key", "tienda_id", "tienda", "formato", "canal", "comuna", "region", "macrozona"]]

    # ---------------- dim_cliente (key 0 = cliente anónimo, sin tarjeta)
    c = (b["clientes"].merge(b["comunas"][["comuna_id", "comuna", "region_id"]], on="comuna_id", how="left")
         .merge(b["regiones"], on="region_id", how="left").sort_values("cliente_id").reset_index(drop=True))
    c["macrozona"] = c["region"].map(MACROZONA)
    c["rut_rango_empresa"] = pd.to_numeric(c["rut_cuerpo"], errors="coerce") >= RUT_EMPRESA_DESDE
    c.insert(0, "cliente_key", range(1, len(c) + 1))
    c = c.rename(columns={"segmento": "segmento_actual"})
    cols = ["cliente_key", "cliente_id", "fecha_alta", "fecha_alta_alt", "comuna", "region", "macrozona",
            "segmento_actual", "tipo_nombre", "rut_valido", "rut_rango_empresa"]
    anon = pd.DataFrame([{"cliente_key": 0, "cliente_id": -1, "segmento_actual": "Anónimo", "tipo_nombre": "anónimo"}])
    dim_cliente = pd.concat([anon, c[cols]], ignore_index=True)[cols]
    dim_cliente["cliente_id"] = dim_cliente["cliente_id"].astype(int)

    # ---------------- dim_producto (SKU vendidos que no están en el maestro: miembro "Sin maestro", sin costo)
    pr = b["productos"].sort_values("sku").reset_index(drop=True)
    sin_m = sorted(set(b["detalle"]["sku"]) - set(pr["sku"]))
    pr = pd.concat([pr, pd.DataFrame({"sku": sin_m, "nombre": "Producto no registrado en el maestro",
                                      "categoria": "Sin maestro", "subcategoria": "Sin maestro"})], ignore_index=True)
    pr["en_maestro"] = ~pr["sku"].isin(sin_m)
    pr.insert(0, "producto_key", range(1, len(pr) + 1))
    dim_producto = pr[["producto_key", "sku", "nombre", "categoria", "subcategoria", "marca", "proveedor",
                       "costo_unitario", "precio_lista", "activo", "en_maestro"]]

    # ---------------- dim_medio_pago
    mp = b["medios_pago"].sort_values("medio_id").reset_index(drop=True)
    mp.insert(0, "medio_pago_key", range(1, len(mp) + 1))
    dim_medio_pago = mp

    # ---------------- dim_campana (key 0 = sin campaña)
    ca = b["campanas"].sort_values("campana_id").reset_index(drop=True)
    ca.insert(0, "campana_key", range(1, len(ca) + 1))
    sin = pd.DataFrame([{"campana_key": 0, "campana_id": "SIN", "nombre": "Sin campaña"}])
    dim_campana = pd.concat([sin, ca], ignore_index=True)

    # ---------------- fact_venta (grano: línea de boleta válida)
    bol = b["boletas"]
    d = b["detalle"].merge(bol[["boleta_id", "fecha", "fecha_alt", "tienda_id", "cliente_id", "medio_id"]], on="boleta_id")
    d = d.sort_values(["boleta_id", "linea"], kind="stable").reset_index(drop=True)
    d["linea_n"] = d.groupby("boleta_id").cumcount() + 1           # la línea de origen se repite en 408 pares: se numera de nuevo
    d = d.merge(dim_producto[["producto_key", "sku", "costo_unitario"]], on="sku", how="left")
    d = d.merge(dim_tienda[["tienda_key", "tienda_id", "canal"]], on="tienda_id", how="left")
    d = d.merge(dim_medio_pago[["medio_pago_key", "medio_id"]], on="medio_id", how="left")
    d["cliente_id"] = d["cliente_id"].fillna(-1).astype(int)
    d = d.merge(dim_cliente[["cliente_key", "cliente_id"]], on="cliente_id", how="left")
    # Campaña de la línea: SKU en la campaña, fecha dentro de la campaña y canal habilitado
    cs = b["campana_sku"].merge(ca[["campana_key", "campana_id", "fecha_ini", "fecha_fin", "canales"]], on="campana_id")
    dp = d[["boleta_id", "linea_n", "sku", "fecha", "canal"]].merge(cs, on="sku")
    dp = dp[(dp["fecha"] >= dp["fecha_ini"].dt.normalize()) & (dp["fecha"] <= dp["fecha_fin"]) &
            np.array([cn in str(cs_).split(", ") for cn, cs_ in zip(dp["canal"], dp["canales"])], dtype=bool)]
    camp = dp.drop_duplicates(["boleta_id", "linea_n"]).set_index(["boleta_id", "linea_n"])["campana_key"]
    d["campana_key"] = pd.Series(list(zip(d["boleta_id"], d["linea_n"]))).map(camp).fillna(0).astype(int).values
    # Pesos reales de diciembre con el IPC encadenado
    ipc = b["ipc"].assign(mes_p=lambda x: pd.PeriodIndex(x["mes"], freq="M"))
    factor = dict(zip(ipc["mes_p"], ipc["factor_a_pesos_dic"]))
    d["factor_ipc"] = d["fecha"].dt.to_period("M").map(factor)
    d["costo_nominal"] = d["cantidad"] * d["costo_unitario"]
    fact = pd.DataFrame({
        "boleta_id": d["boleta_id"], "linea_n": d["linea_n"], "linea_origen": d["linea"],
        "fecha_key": d["fecha"].dt.strftime("%Y%m%d").astype(int),
        "fecha_alt_key": d["fecha_alt"].dt.strftime("%Y%m%d").astype(int),
        "cliente_key": d["cliente_key"], "producto_key": d["producto_key"], "tienda_key": d["tienda_key"],
        "medio_pago_key": d["medio_pago_key"], "campana_key": d["campana_key"],
        "cantidad": d["cantidad"], "precio_unitario": d["precio"], "descuento_pct": d["desc"],
        "monto_nominal": d["monto"], "monto_real_dic": d["monto"] * d["factor_ipc"],
        "costo_nominal": d["costo_nominal"], "margen_nominal": d["monto"] - d["costo_nominal"],
        "margen_real_dic": (d["monto"] - d["costo_nominal"]) * d["factor_ipc"],
    })
    assert not fact.duplicated(["boleta_id", "linea_n"]).any(), "fact_venta rompe su grano"
    assert fact["boleta_id"].nunique() == len(bol), "fact_venta no contiene todas las boletas válidas"

    g = {"dim_fecha": dim_fecha, "dim_cliente": dim_cliente, "dim_producto": dim_producto, "dim_tienda": dim_tienda,
         "dim_medio_pago": dim_medio_pago, "dim_campana": dim_campana, "fact_venta": fact}
    for n, df in g.items():
        guardar(con, "gondola", n, df)
    log.info(f"Góndola: fact_venta con {len(fact):,} líneas de {fact['boleta_id'].nunique():,} boletas · 6 dimensiones")
    return g
