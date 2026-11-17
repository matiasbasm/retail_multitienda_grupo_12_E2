"""Lectura de config/parametros.yaml y utilidades comunes (rutas, log)."""
import logging
import os
from pathlib import Path

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent.parent


def cargar_parametros(ruta=None):
    ruta = Path(ruta) if ruta else RAIZ / "config" / "parametros.yaml"
    with open(ruta, encoding="utf-8") as f:
        p = yaml.safe_load(f)
    anio = p["periodo"]["anio"]
    for k, v in p["fuentes"].items():
        if isinstance(v, str):
            p["fuentes"][k] = v.format(anio=anio)
    # Fechas derivadas (no se escriben a mano)
    ini, fin = pd.Timestamp(f"{anio}-01-01"), pd.Timestamp(f"{anio}-12-31")
    p["periodo"]["inicio"], p["periodo"]["fin"] = ini, fin
    p["metrica"]["fecha_base"] = primera_fecha_base(ini, p["metrica"]["ventana_principal"])
    p["metrica"]["fecha_base_comun"] = primera_fecha_base(ini, max(p["metrica"]["ventanas_tablero"]))
    return p


def primera_fecha_base(inicio, W):
    """Primer cierre de mes con W días de historia completos dentro del período."""
    return (inicio + pd.Timedelta(days=W - 1)) + pd.offsets.MonthEnd(0)


def ruta(rel):
    """Ruta absoluta dentro del repositorio (funciona desde cualquier carpeta)."""
    return RAIZ / rel


def obtener_log(p):
    os.makedirs(ruta(p["rutas"]["salidas"]), exist_ok=True)
    log = logging.getLogger("cadena")
    if not log.handlers:
        log.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
        archivo = logging.FileHandler(ruta(p["rutas"]["log"]), encoding="utf-8")   # se archiva: se agrega, no se borra
        archivo.setFormatter(fmt)
        consola = logging.StreamHandler()
        consola.setFormatter(fmt)
        log.addHandler(archivo)
        log.addHandler(consola)
    return log
