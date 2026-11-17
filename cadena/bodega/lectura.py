"""Lectura de la copia de recepción y funciones de interpretación (fechas, números, texto).

Código trasladado del notebook E1_pipeline_v2.ipynb (secciones 1, 2.1, 2.5, 2.6, 2.11) sin cambiar la lógica.
"""
import csv
import io
import json
import re
import sqlite3
import unicodedata

import numpy as np
import pandas as pd


# ----------------------------------------------------------------- lectura
def leer_recepcion(carpeta):
    con = sqlite3.connect(carpeta / "origen_pos.sqlite")
    tablas = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", con)["name"].tolist()
    pos = {t: pd.read_sql(f'SELECT * FROM "{t}"', con) for t in tablas}
    con.close()
    maestro_raw, codif, sep = leer_csv_robusto(carpeta / "origen_maestro_productos.csv")
    promos = json.load(open(carpeta / "origen_promociones.json", encoding="utf-8"))
    campanas_raw = pd.DataFrame([{k: v for k, v in c.items() if k != "skus"} for c in promos["campanas"]])
    campana_sku_raw = pd.DataFrame([{"campana_id": c["campana_id"], "sku": s} for c in promos["campanas"] for s in c["skus"]])
    ipc_rec = json.load(open(carpeta / "ipc_recibido.json", encoding="utf-8"))
    return {"pos": pos, "maestro_raw": maestro_raw, "codif_maestro": codif, "campanas_raw": campanas_raw,
            "campana_sku_raw": campana_sku_raw, "ipc_raw": ipc_rec["respuesta"], "origen_ipc": ipc_rec["origen"]}


def leer_csv_robusto(ruta):
    contenido = open(ruta, "rb").read()
    for codif in ("utf-8", "cp1252", "latin-1"):
        try:
            texto = contenido.decode(codif)
            break
        except UnicodeDecodeError:
            continue
    sep = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=";,|\t").delimiter
    return pd.read_csv(io.StringIO(texto), sep=sep, dtype=str, keep_default_na=False), codif, sep


# ----------------------------------------------------------------- firmas de formato
def firma(v):
    s = re.sub(r"\d", "9", str(v))
    s = re.sub(r"[A-ZÁÉÍÓÚÑ]+", "A", s)
    return re.sub(r"[a-záéíóúñü]+", "a", s)


def familia(v):
    return re.sub(r"9+", "9", re.sub(r"^\s*-", "", firma(v)))


# ----------------------------------------------------------------- fechas
MESES_TEXTO = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
               "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
PATRONES_AMBIGUOS = [("99/99/9999", r"^(\d{1,2})/(\d{1,2})/\d{4}$"), ("99-99-99", r"^(\d{1,2})-(\d{1,2})-\d{2}$")]


def evidencia_orden(serie, patron):
    m = serie.astype(str).str.strip().str.extract(patron).dropna().astype(int)
    return int((m[0] > 12).sum()), int((m[1] > 12).sum())


def decidir_orden(serie):
    """Con los datos: si el primer número supera 12 en algunos casos y el segundo nunca, el orden es día-mes."""
    s = serie.astype(str).str.strip()
    evid = {}
    for etiqueta, patron in PATRONES_AMBIGUOS:
        p1, p2 = evidencia_orden(s, patron)
        orden = "día-mes" if p1 > 0 and p2 == 0 else ("mes-día" if p2 > 0 and p1 == 0 else "indeterminado")
        evid[etiqueta] = {"primero_mayor_12": p1, "segundo_mayor_12": p2, "orden": orden}
    dia_primero = all(v["orden"] != "mes-día" for v in evid.values())
    return dia_primero, evid


def parsear_fechas(serie, dia_primero):
    """Devuelve (fecha, fecha_alternativa).

    fecha_alternativa: la lectura contraria SOLO en las fechas que dependen del supuesto día-mes
    (formato numérico ambiguo con ambos números <= 12 y distintos). En el resto coincide con `fecha`.
    Así la lectura mes-día queda disponible como escenario en el tablero sin recalcular nada.
    """
    s = serie.astype(str).str.strip()

    def uno(x, dp):
        try:
            if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", x):
                return pd.Timestamp(x)
            m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", x)
            if m:
                a, b, y = int(m[1]), int(m[2]), int(m[3])
                y = y + 2000 if y < 100 else y
                return pd.Timestamp(y, b, a) if dp else pd.Timestamp(y, a, b)
            m = re.fullmatch(r"(\d{1,2})[-/ ]([A-Za-z]{3})[a-z]*[-/ ](\d{2,4})", x)
            if m and m[2].lower() in MESES_TEXTO:
                y = int(m[3]); y = y + 2000 if y < 100 else y
                return pd.Timestamp(y, MESES_TEXTO[m[2].lower()], int(m[1]))
        except ValueError:
            return pd.NaT
        return pd.NaT

    fecha = s.map(lambda x: uno(x, dia_primero))
    amb = s.str.extract(r"^(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})$")
    a, b = pd.to_numeric(amb[0]), pd.to_numeric(amb[1])
    depende = (a <= 12) & (b <= 12) & (a != b)
    alt = fecha.copy()
    alt[depende] = s[depende].map(lambda x: uno(x, not dia_primero))
    return fecha, alt, depende.fillna(False)


# ----------------------------------------------------------------- números
def evidencia_punto(serie):
    grupos = serie.astype(str).str.findall(r"\.(\d+)").explode().dropna()
    return (grupos.str.len() == 3).mean() if len(grupos) else np.nan


def parsear_numero(serie, punto_es_miles):
    s = serie.astype(str).str.strip().str.replace(" ", "").str.replace("$", "", regex=False)
    if punto_es_miles:
        s = s.str.replace(r"^(-?)\.(\d{3})$", r"\1\2", regex=True)   # '-.769' -> '-769'
        s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        s = s.str.replace(",", "", regex=False)
    return pd.to_numeric(s, errors="coerce")


def parsear_descuento(serie):
    s = serie.astype(str).str.strip()
    pct = s.str.endswith("%")
    v = pd.to_numeric(s.str.rstrip("%").str.replace(",", ".", regex=False), errors="coerce")
    return np.where(pct | (v >= 1), v / 100, v)


# ----------------------------------------------------------------- texto
def normalizar_texto(s):
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().strip()


def es_subsecuencia(corta, larga):
    it = iter(larga)
    return corta[0] == larga[0] and all(ch in it for ch in corta)


def proponer_canonicos(df, col, col_contexto=None):
    v = df[col].astype(str).str.strip()
    norm = v.map(normalizar_texto)
    candidatas = [n for n in norm.unique() if (v[norm == n] != v[norm == n].str.upper()).any()]
    completas = [n for n in candidatas if not any(o != n and len(o) > len(n) and es_subsecuencia(n, o) for o in candidatas)]
    visible = {n: v[norm == n].map(lambda x: (sum(c in "áéíóúÁÉÍÓÚ" for c in x), x[0].isupper(), x)).max()[2] for n in completas}
    mapa, metodo = {}, {}
    for n in norm.unique():
        if n in completas:
            mapa[n], metodo[n] = visible[n], "misma palabra normalizada"
        else:
            cand = [c for c in completas if es_subsecuencia(n, c)]
            if len(cand) == 1:
                mapa[n], metodo[n] = visible[cand[0]], "abreviación"
    if col_contexto:
        ctx = df[col_contexto].astype(str).str.strip()
        resueltas = norm.map(mapa)
        mayoria = resueltas.groupby(ctx).agg(lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None)
        for n in norm.unique():
            if n not in mapa:
                cats = ctx[norm == n].map(mayoria).dropna().unique()
                if len(cats) == 1:
                    mapa[n], metodo[n] = cats[0], f"categoría mayoritaria de su {col_contexto}"
    tabla = (pd.DataFrame({"original": v, "normalizado": norm}).value_counts().reset_index(name="filas")
             .assign(propuesta=lambda d: d["normalizado"].map(mapa), metodo=lambda d: d["normalizado"].map(metodo)))
    return tabla.sort_values(["propuesta", "filas"], ascending=[True, False])


def dv_rut(cuerpo):
    s, m = 0, 2
    for d in reversed(str(cuerpo)):
        s += int(d) * m
        m = 2 if m == 7 else m + 1
    r = 11 - s % 11
    return "0" if r == 11 else "K" if r == 10 else str(r)
