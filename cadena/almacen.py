"""Acceso a la base DuckDB (un solo archivo con un esquema por paso: bodega, gondola, operacion)."""
import duckdb
import pandas as pd

from .config import ruta

ESQUEMAS = ("bodega", "gondola", "operacion")


def conectar(p, solo_lectura=False):
    return duckdb.connect(str(ruta(p["rutas"]["almacen"])), read_only=solo_lectura)


def preparar(con):
    for e in ESQUEMAS:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {e}")


def guardar(con, esquema, nombre, df):
    """Carga completa: reemplaza la tabla entera (correr dos veces no duplica)."""
    df = df.copy()
    for c in df.columns:
        if df[c].dtype == object:
            no_nulos = df[c].dropna()
            if len(no_nulos) and not all(isinstance(v, str) for v in no_nulos):
                if all(isinstance(v, (bool,)) for v in no_nulos):
                    df[c] = df[c].astype("boolean")
                else:
                    df[c] = df[c].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    con.register("_tmp", df)
    con.execute(f'CREATE OR REPLACE TABLE {esquema}."{nombre}" AS SELECT * FROM _tmp')
    con.unregister("_tmp")


def leer(con, esquema, nombre):
    return con.execute(f'SELECT * FROM {esquema}."{nombre}"').df()


def agregar(con, esquema, nombre, df):
    """Para el historial de operación (corridas y pruebas): se agrega, no se reemplaza."""
    con.register("_tmp", df)
    existe = con.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{esquema}' AND table_name='{nombre}'").fetchone()[0]
    if existe:
        con.execute(f'INSERT INTO {esquema}."{nombre}" BY NAME SELECT * FROM _tmp')
    else:
        con.execute(f'CREATE TABLE {esquema}."{nombre}" AS SELECT * FROM _tmp')
    con.unregister("_tmp")
