"""Pruebas de calidad automáticas.

Cada prueba dice: qué verifica, en qué paso, sobre qué fuente o tabla, y qué hace si falla:
  - BLOQUEA: la cadena se detiene (no se publica un número malo).
  - AVISA:   la cadena sigue, pero queda registrado en el log, en `operacion.pruebas` y en el pie del tablero.
"""
import pandas as pd

BLOQUEA, AVISA = "bloquea", "avisa"


class PruebaBloqueante(Exception):
    pass


class Pruebas:
    def __init__(self, log):
        self.log = log
        self.filas = []

    def verificar(self, codigo, paso, objeto, que_verifica, ok, accion, detalle=""):
        ok = bool(ok)
        self.filas.append({"codigo": codigo, "paso": paso, "objeto": objeto, "que_verifica": que_verifica,
                           "si_falla": accion, "resultado": "OK" if ok else "FALLA", "detalle": str(detalle)})
        if ok:
            self.log.info(f"prueba {codigo} OK · {que_verifica}")
        elif accion == BLOQUEA:
            self.log.error(f"prueba {codigo} FALLA (bloquea) · {que_verifica} · {detalle}")
            raise PruebaBloqueante(f"{codigo}: {que_verifica} · {detalle}")
        else:
            self.log.warning(f"prueba {codigo} FALLA (avisa) · {que_verifica} · {detalle}")
        return ok

    def tabla(self):
        return pd.DataFrame(self.filas)


# ---------------------------------------------------------------------------
# Pruebas sobre el modelo (paso 3) y la métrica: protegen el número
# ---------------------------------------------------------------------------
def probar_modelo(pr, g, p):
    f = g["fact_venta"]
    ini, fin = p["periodo"]["inicio"], p["periodo"]["fin"]
    pr.verificar("M01", "gondola", "fact_venta", "La clave del hecho (boleta_id, linea_n) es única",
                 not f.duplicated(["boleta_id", "linea_n"]).any(), BLOQUEA,
                 f"{f.duplicated(['boleta_id', 'linea_n']).sum()} repetidas")
    for dim, clave in [("dim_cliente", "cliente_key"), ("dim_producto", "producto_key"), ("dim_tienda", "tienda_key"),
                       ("dim_medio_pago", "medio_pago_key"), ("dim_campana", "campana_key")]:
        d = g[dim]
        pr.verificar(f"M02-{dim}", "gondola", dim, f"La clave sustituta {clave} es única en {dim}",
                     d[clave].is_unique, BLOQUEA)
        huerf = ~f[clave].isin(d[clave])
        pr.verificar(f"M03-{dim}", "gondola", "fact_venta", f"Sin huérfanos: toda {clave} del hecho existe en {dim}",
                     not huerf.any(), BLOQUEA, f"{huerf.sum()} filas huérfanas")
    for rol in ("fecha_key", "fecha_alt_key"):
        huerf = ~f[rol].isin(g["dim_fecha"]["fecha_key"])
        pr.verificar(f"M03-{rol}", "gondola", "fact_venta", f"Sin huérfanos: toda {rol} existe en dim_fecha",
                     not huerf.any(), BLOQUEA, f"{huerf.sum()} filas huérfanas")
    fechas = pd.to_datetime(f["fecha_key"].astype(str))
    pr.verificar("M04", "gondola", "fact_venta", f"Todas las fechas están dentro del período ({ini:%d-%m-%Y} a {fin:%d-%m-%Y})",
                 fechas.between(ini, fin).all(), BLOQUEA, f"{(~fechas.between(ini, fin)).sum()} fuera")
    pr.verificar("M05", "gondola", "fact_venta", "Montos de línea positivos (las boletas válidas tienen compra neta)",
                 (f["monto_nominal"] > 0).all(), BLOQUEA, f"{(f['monto_nominal'] <= 0).sum()} líneas con monto ≤ 0")
    pr.verificar("M06", "gondola", "fact_venta", "Todo monto tiene su factor IPC (monto real calculado)",
                 f["monto_real_dic"].notna().all(), BLOQUEA)
    sin_costo = f["costo_nominal"].isna().mean()
    pr.verificar("M07", "gondola", "fact_venta", "Líneas sin costo (margen no calculable) bajo 5%",
                 sin_costo < 0.05, AVISA, f"{100 * sin_costo:.1f}% de las líneas")


def probar_metrica(pr, r, p):
    pr.verificar("Q01", "metricas", "RBA", "La retención principal está entre 0% y 100%",
                 0 <= r["rba_principal"] <= 100, BLOQUEA, r["rba_principal"])
    pr.verificar("Q02", "metricas", "RBA", "La base activa no está vacía (hay denominador)",
                 r["base_principal"] > 0, BLOQUEA, r["base_principal"])
    pr.verificar("Q03", "metricas", "RBA", "Retenidos + perdidos = base activa (la cuenta cierra)",
                 r["retenidos"] + r["perdidos"] == r["base_principal"], BLOQUEA)
    pr.verificar("Q04", "metricas", "Cobertura", "Las boletas excluidas + usadas suman las originales (la cobertura cierra)",
                 r["cobertura_cierra"], BLOQUEA)
    pr.verificar("Q05", "metricas", "Cobertura",
                 f"Completitud: al menos {p['sla']['completitud_min_pct']}% de las boletas originales llega a la métrica (SLA)",
                 r["pct_usadas"] >= p["sla"]["completitud_min_pct"], AVISA, f"{r['pct_usadas']:.1f}%")
    pr.verificar("Q06", "metricas", "NNV", "El % de nuevos que no vuelven está entre 0% y 100%",
                 0 <= r["nnv_principal"] <= 100, BLOQUEA, r["nnv_principal"])
