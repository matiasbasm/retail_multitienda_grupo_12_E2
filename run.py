"""Un comando corre la cadena completa, de cero:

    python run.py              # corrida normal
    python run.py --sin-api    # simula que la API del IPC está caída (prueba del respaldo)

Pasos: 1 recepción -> 2 bodega -> 3 góndola -> pruebas del modelo -> capa semántica + cifras -> pruebas de la métrica.
Si una prueba BLOQUEANTE falla, la cadena se detiene y el tablero sigue mostrando la última corrida buena.
"""
import argparse
import sys
import time
import uuid
from datetime import datetime

import pandas as pd

from cadena import almacen, gondola, informe, metricas, recepcion
from cadena.bodega import depurar
from cadena.calidad import Pruebas, PruebaBloqueante, probar_metrica, probar_modelo
from cadena.config import cargar_parametros, obtener_log, ruta


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-api", action="store_true", help="simula la caída de la API del IPC")
    args = ap.parse_args(argv)

    p = cargar_parametros()
    log = obtener_log(p)
    corrida = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    t0 = time.time()
    log.info(f"===== Corrida {corrida} · inicio =====")
    pr = Pruebas(log)
    salidas = ruta(p["rutas"]["salidas"])
    estado, error, info_ipc, cifras = "OK", "", {}, None
    ruta_db = ruta(p["rutas"]["almacen"])
    ruta_tmp = ruta_db.with_suffix(".construyendo.duckdb")
    ruta_tmp.unlink(missing_ok=True)
    try:
        man, info_ipc = recepcion.recibir(p, log, pr, simular_caida_api=args.sin_api)
        # Se construye en un archivo nuevo y solo si todo pasa reemplaza al publicado:
        # así el tablero nunca ve una base a medio construir ni una corrida que falló.
        p_tmp = {**p, "rutas": {**p["rutas"], "almacen": str(ruta_tmp)}}
        con = almacen.conectar(p_tmp)
        almacen.preparar(con)
        extra = depurar(p, log, con)
        g = gondola.construir(p, log, con)
        probar_modelo(pr, g, p)
        m = metricas.cargar(con, p)
        cifras, res = informe.calcular(m, p, extra, log, salidas / "tablas")
        probar_metrica(pr, res, p)
        almacen.guardar(con, "operacion", "recepcion", man)
        almacen.guardar(con, "operacion", "cifras", cifras)
        almacen.guardar(con, "operacion", "decisiones", pd.DataFrame(list(extra["decisiones"].items()), columns=["problema", "decision"]))
        con.close()
    except PruebaBloqueante as e:
        estado, error = "BLOQUEADA", str(e)
    except Exception as e:
        estado, error = "ERROR", f"{type(e).__name__}: {e}"
        log.exception("La cadena falló")

    dur = round(time.time() - t0, 1)
    pruebas = pr.tabla().assign(corrida=corrida)
    pruebas.to_csv(salidas / "resultados_pruebas.csv", index=False, encoding="utf-8-sig")
    n_ok, n = int((pruebas["resultado"] == "OK").sum()), len(pruebas)
    bloq = pruebas[pruebas["si_falla"] == "bloquea"]
    pct_bloq_ok = round(100 * (bloq["resultado"] == "OK").mean(), 1) if len(bloq) else 0.0
    fila = pd.DataFrame([{"corrida": corrida, "inicio": datetime.fromtimestamp(t0).isoformat(timespec="seconds"),
                          "duracion_seg": dur, "estado": estado, "error": error, "pruebas_ok": n_ok, "pruebas_total": n,
                          "pct_bloqueantes_ok": pct_bloq_ok, "fuente_ipc": info_ipc.get("origen_ipc", ""),
                          "estado_ipc": info_ipc.get("estado_ipc", "")}])

    if estado == "OK":
        if ruta_db.exists():                 # el historial de corridas anteriores pasa a la base nueva
            import duckdb
            c = duckdb.connect(str(ruta_tmp))
            c.execute(f"ATTACH '{ruta_db}' AS viejo (READ_ONLY)")
            for t in ("corridas", "pruebas"):
                if c.execute(f"SELECT COUNT(*) FROM information_schema.tables WHERE table_catalog='viejo' AND table_schema='operacion' AND table_name='{t}'").fetchone()[0]:
                    c.execute(f"CREATE TABLE operacion.{t} AS SELECT * FROM viejo.operacion.{t}")
            c.close()
        ruta_tmp.replace(ruta_db)            # publicación atómica de la corrida buena
        destino = ruta_db
    else:
        ruta_tmp.unlink(missing_ok=True)
        destino = ruta_db if ruta_db.exists() else None
    if destino:                               # el historial de corridas y pruebas se archiva (se agrega, no se borra)
        import duckdb
        con = duckdb.connect(str(destino))
        almacen.preparar(con)
        almacen.agregar(con, "operacion", "corridas", fila)
        almacen.agregar(con, "operacion", "pruebas", pruebas)
        if estado == "OK":
            almacen.guardar(con, "operacion", "ultima_corrida", fila)
        con.close()

    log.info(f"===== Corrida {corrida} · {estado} en {dur} s · pruebas {n_ok}/{n} OK =====")
    if estado != "OK":
        log.error(f"No se publicó esta corrida: {error}. El tablero sigue mostrando la última corrida buena.")
        return 1
    print("\nCifras principales (salidas/cifras_informe.csv):")
    clave = ["RBA_90", "RBA_30", "RET_TRIM", "REPOSICION_90", "NNV_90", "PCT_EXCLUIDAS", "MARGEN_NO_CAPTURADO", "FUENTE_IPC"]
    print(cifras.set_index("etiqueta").loc[clave, ["descripcion", "valor", "unidad"]].to_string())
    print("\nAbrir el tablero:  streamlit run app/tablero.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
