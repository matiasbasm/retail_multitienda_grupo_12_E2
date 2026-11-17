"""Paso 2 · BODEGA: la mercadería se revisa y se ordena.

Lee SOLO la copia de recepción, detecta los problemas (deteccion.py), aplica las decisiones
(limpieza.py) y guarda las tablas depuradas en el esquema `bodega` de la base DuckDB.
"""
from ..config import ruta
from ..almacen import guardar
from .deteccion import detectar
from .limpieza import limpiar
from .lectura import leer_recepcion


def depurar(p, log, con):
    d = leer_recepcion(ruta(p["rutas"]["recepcion"]))
    ev = detectar(d, p, ruta(p["rutas"]["salidas"]) / "calidad", log)
    lim = limpiar(d, ev, p, log)
    pos = d["pos"]
    tablas = {
        "boletas": lim["boletas_validas"], "detalle": lim["detalle"].drop(columns=["sku_n"]),
        "clientes": lim["clientes"], "productos": lim["maestro"], "comunas": lim["comunas"],
        "regiones": pos["regiones"], "tiendas": pos["tiendas"], "medios_pago": pos["medios_pago"],
        "campanas": lim["campanas"].drop(columns=["canales_lista"]), "campana_sku": lim["campana_sku"],
        "ipc": lim["ipc"].assign(mes=lim["ipc"]["mes"].astype(str)),
        "registro_limpieza": lim["registro"], "resumen_calidad": ev["resumen_calidad"],
    }
    for nombre, df in tablas.items():
        guardar(con, "bodega", nombre, df)
    log.info(f"Bodega: {len(tablas)} tablas depuradas guardadas en el esquema 'bodega'")
    extra = {"decisiones": lim["decisiones"], "cobertura": lim["cobertura"], "inflacion": lim["inflacion"],
             "impacto_monto": lim["impacto_monto"], "impacto_atipica": lim["impacto_atipica"],
             "pct_fechas_supuesto": ev["pct_fechas_supuesto"], "evid_orden_boletas": ev["evid_orden_boletas"],
             "n_problemas": len(ev["resumen_calidad"]), "origen_ipc": d["origen_ipc"]}
    return extra
