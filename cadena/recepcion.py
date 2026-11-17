"""Paso 1 · RECEPCIÓN: copia exacta de lo que llegó, sin arreglar nada.

Como el andén de recepción de un supermercado: la mercadería se recibe, se cuenta y se anota
de dónde vino y cuándo, pero todavía no se ordena ni se revisa producto por producto.

Por qué existe: si mañana una fuente cambia o la API se cae, queda la copia de lo que se usó;
y si alguien pregunta "¿esto venía así o lo rompieron ustedes?", la respuesta está aquí.

Decisión ELT: primero se guarda (E, L) y recién después se transforma (T, en el paso 2).
Decisión de recarga: carga COMPLETA. Cada corrida reemplaza la copia anterior; nada se agrega
encima, así que correr dos veces no duplica registros.
Decisión ante falla de la API del IPC: API -> último respaldo bueno de la API -> respaldo manual (INE).
Se avisa en el log, en `operacion.pruebas` y en el pie del tablero.
"""
import hashlib
import json
import os
import shutil
import sqlite3
from datetime import datetime

import pandas as pd
import requests

from .calidad import AVISA, BLOQUEA
from .config import ruta


def _huella(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]


TABLAS_POS = ["regiones", "comunas", "tiendas", "medios_pago", "clientes", "boletas", "boleta_detalle"]
COLUMNAS_MAESTRO = ["sku", "nombre", "categoria", "subcategoria", "marca", "proveedor", "costo_unitario", "precio_lista", "activo"]


def validar_serie_ipc(data, anio):
    meses = pd.to_datetime([s["fecha"] for s in data["serie"]], utc=True).tz_localize(None).to_period("M")
    meses = {m for m in meses if m.year == anio}
    valores_ok = all(isinstance(s["valor"], (int, float)) for s in data["serie"])
    if len(meses) != 12 or not valores_ok:
        raise ValueError(f"serie inválida: {len(meses)} meses distintos de {anio}, valores numéricos={valores_ok}")


def obtener_ipc(p, log, simular_caida=False):
    """Devuelve (respuesta_json, origen_legible, estado) con la cascada API -> respaldo API -> respaldo manual."""
    anio, f = p["periodo"]["anio"], p["fuentes"]
    url, r_api, r_man = f["ipc_url"], ruta(f["ipc_respaldo_api"]), ruta(f["ipc_respaldo_manual"])
    try:
        if simular_caida:
            raise ConnectionError("caída simulada (--sin-api)")
        resp = requests.get(url, timeout=f["ipc_timeout_seg"])
        resp.raise_for_status()
        data = resp.json()
        validar_serie_ipc(data, anio)
        anterior = json.load(open(r_api, encoding="utf-8"))["respuesta"] if r_api.exists() else None
        if anterior is None or anterior.get("serie") != data.get("serie"):
            try:
                with open(r_api, "w", encoding="utf-8") as fh:
                    json.dump({"url": url, "consultado_en": datetime.now().isoformat(timespec="seconds"), "respuesta": data},
                              fh, ensure_ascii=False, indent=1)
                log.info("IPC: la serie de la API cambió; se actualizó el respaldo de la API")
            except OSError as e:
                log.warning(f"IPC: no se pudo guardar el respaldo nuevo de la API ({e}); se sigue con la respuesta recibida")
        return data, "API mindicador.cl", "api"
    except Exception as e:
        log.warning(f"IPC: la API no respondió o devolvió datos inválidos ({e}); se usa un respaldo")
        if r_api.exists():
            resp = json.load(open(r_api, encoding="utf-8"))
            validar_serie_ipc(resp["respuesta"], anio)
            return resp["respuesta"], f"respaldo de la API ({resp['consultado_en'][:10]})", "respaldo_api"
        data = json.load(open(r_man, encoding="utf-8"))
        validar_serie_ipc(data, anio)
        return data, "respaldo manual (valores INE)", "respaldo_manual"


def recibir(p, log, pruebas, simular_caida_api=False):
    destino = ruta(p["rutas"]["recepcion"])
    shutil.rmtree(destino, ignore_errors=True)       # carga completa: se reemplaza la copia anterior
    os.makedirs(destino)
    ahora = datetime.now().isoformat(timespec="seconds")
    manifiesto = []

    # --- POS (SQLite) ---
    src = ruta(p["fuentes"]["pos"])
    pruebas.verificar("F01", "recepcion", "origen_pos.sqlite", "La base del POS existe", src.exists(), BLOQUEA, src)
    shutil.copy2(src, destino / src.name)
    con = sqlite3.connect(destino / src.name)
    tablas = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)["name"].tolist()
    faltan = [t for t in TABLAS_POS if t not in tablas]
    pruebas.verificar("F02", "recepcion", "origen_pos.sqlite", "La base del POS trae las 7 tablas esperadas",
                      not faltan, BLOQUEA, f"faltan: {faltan}")
    filas = {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tablas}
    con.close()
    pruebas.verificar("F03", "recepcion", "origen_pos.sqlite", "Las boletas y su detalle no vienen vacíos",
                      filas.get("boletas", 0) > 0 and filas.get("boleta_detalle", 0) > 0, BLOQUEA, filas)
    manifiesto.append({"fuente": "POS (SQLite)", "archivo": src.name, "filas": sum(filas.values()), "huella": _huella(src)})

    # --- Maestro (CSV) ---
    src = ruta(p["fuentes"]["maestro"])
    pruebas.verificar("F04", "recepcion", src.name, "El maestro de productos existe", src.exists(), BLOQUEA)
    shutil.copy2(src, destino / src.name)
    primera = open(src, "rb").readline().decode("utf-8", errors="replace").strip().lower()
    faltan = [c for c in COLUMNAS_MAESTRO if c not in primera]
    pruebas.verificar("F05", "recepcion", src.name, "El maestro trae las 9 columnas esperadas", not faltan, BLOQUEA, f"faltan: {faltan}")
    n = sum(1 for _ in open(src, "rb")) - 1
    manifiesto.append({"fuente": "Maestro de productos (CSV)", "archivo": src.name, "filas": n, "huella": _huella(src)})

    # --- Promociones (JSON) ---
    src = ruta(p["fuentes"]["promociones"])
    shutil.copy2(src, destino / src.name)
    try:
        promos = json.load(open(src, encoding="utf-8"))
        ok = isinstance(promos.get("campanas"), list) and len(promos["campanas"]) > 0
    except Exception as e:
        ok, promos = False, {"campanas": []}
    pruebas.verificar("F06", "recepcion", src.name, "El JSON de promociones se lee y trae campañas", ok, BLOQUEA)
    manifiesto.append({"fuente": "Promociones (JSON)", "archivo": src.name, "filas": len(promos["campanas"]), "huella": _huella(src)})

    # --- IPC (API con respaldo) ---
    ipc, origen_ipc, estado_ipc = obtener_ipc(p, log, simular_caida_api)
    with open(destino / "ipc_recibido.json", "w", encoding="utf-8") as fh:
        json.dump({"origen": origen_ipc, "estado": estado_ipc, "recibido_en": ahora, "respuesta": ipc}, fh, ensure_ascii=False, indent=1)
    pruebas.verificar("F07", "recepcion", "API mindicador.cl", "La API del IPC respondió con 12 meses válidos",
                      estado_ipc == "api", AVISA, f"se usó: {origen_ipc}")
    manifiesto.append({"fuente": "IPC (API mindicador.cl)", "archivo": "ipc_recibido.json", "filas": len(ipc["serie"]),
                       "huella": origen_ipc})

    man = pd.DataFrame(manifiesto).assign(recibido_en=ahora)
    log.info(f"Recepción: {len(man)} fuentes copiadas en {destino}")
    return man, {"origen_ipc": origen_ipc, "estado_ipc": estado_ipc}
