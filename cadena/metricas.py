"""CAPA SEMÁNTICA · la métrica escrita UNA sola vez.

El informe (cifras_informe.csv) y el tablero (app/tablero.py) llaman a estas mismas funciones.
Por eso no pueden mostrar números distintos (corrección de la E1: 658 vs 652).

Lee SOLO el esquema `gondola`.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Diccionario de definiciones: nombre, fórmula y regla de lectura (se muestran en el tablero)
# ---------------------------------------------------------------------------
DEFINICIONES = {
    "activo": "Un cliente está activo en la fecha d con ventana W si tiene al menos una boleta válida en los W días que terminan en d.",
    "RBA": "Retención de la base activa (RBA_W) = clientes activos en la fecha base que siguen activos al cierre (31-dic) ÷ clientes activos en la fecha base.",
    "regla_RBA": "Se retiene si compró en los {W} días previos al {base} Y en los {W} días previos al 31-dic.",
    "reposicion": "Índice de reposición = clientes nuevos (relación iniciada después de la fecha base) activos al cierre ÷ clientes de la base que se perdieron. Mayor que 1: entran más de los que se van.",
    "NNV": "Nuevos que no vuelven (NNV_H) = % de clientes nuevos con H días observables tras su primera compra que NO tienen una segunda boleta dentro de esos H días.",
    "trimestral": "Retención trimestral = % de los clientes que compraron en un trimestre que vuelven a comprar el trimestre siguiente (horizonte fijo, comparable entre trimestres).",
    "nuevo": "Cliente nuevo: su relación empezó en el período (la fecha más temprana entre el alta en el programa y su primera compra).",
}
ESCENARIOS_FECHA = {"dia-mes": "Día-mes (principal, decidido con los datos)", "mes-dia": "Mes-día (alternativa a validar con la gerencia)"}


@dataclass
class Modelo:
    fact: pd.DataFrame
    dim_cliente: pd.DataFrame
    dim_tienda: pd.DataFrame
    dim_producto: pd.DataFrame
    dim_campana: pd.DataFrame
    ini: pd.Timestamp
    fin: pd.Timestamp


def cargar(con, p):
    q = lambda t: con.execute(f"SELECT * FROM gondola.{t}").df()
    return Modelo(q("fact_venta"), q("dim_cliente"), q("dim_tienda"), q("dim_producto"), q("dim_campana"),
                  p["periodo"]["inicio"], p["periodo"]["fin"])


# ---------------------------------------------------------------------------
# Visitas: de líneas a boletas (una visita = un boleta_id)
# ---------------------------------------------------------------------------
def boletas(m: Modelo, escenario="dia-mes"):
    f = m.fact
    col = "fecha_key" if escenario == "dia-mes" else "fecha_alt_key"
    g = f.groupby("boleta_id")
    bol = pd.DataFrame({
        "cliente_key": g["cliente_key"].first(), "tienda_key": g["tienda_key"].first(),
        "fecha": pd.to_datetime(g[col].first().astype(str)),
        "monto_nominal": g["monto_nominal"].sum(), "monto_real_dic": g["monto_real_dic"].sum(),
        "unidades": g["cantidad"].sum(), "n_lineas": g.size(),
        "lineas_sin_costo": g["costo_nominal"].apply(lambda s: s.isna().sum()),
        "margen_nominal_lineas": g["margen_nominal"].sum(), "margen_real_lineas": g["margen_real_dic"].sum(),
        "tiene_promo": g["campana_key"].max() > 0,
    }).reset_index()
    # Margen de la boleta solo si todas sus líneas tienen costo (mismo criterio que la E1)
    completo = bol["lineas_sin_costo"] == 0
    bol["margen_nominal"] = np.where(completo, bol["margen_nominal_lineas"], np.nan)
    bol["margen_real_dic"] = np.where(completo, bol["margen_real_lineas"], np.nan)
    return bol.drop(columns=["margen_nominal_lineas", "margen_real_lineas"]).sort_values("fecha", kind="stable").reset_index(drop=True)


class Retencion:
    """Todas las métricas de la pregunta, para un escenario de lectura de fechas."""

    def __init__(self, m: Modelo, escenario="dia-mes", z=1.96):
        self.m, self.z, self.escenario = m, z, escenario
        self.bol = boletas(m, escenario)
        self.ident = self.bol[self.bol["cliente_key"] > 0].copy()
        # Inicio de la relación = min(fecha de alta, primera compra)
        dc = m.dim_cliente.set_index("cliente_key")
        alta = pd.to_datetime(dc["fecha_alta" if escenario == "dia-mes" else "fecha_alta_alt"])
        primera = self.ident.groupby("cliente_key")["fecha"].min()
        self.inicio = pd.concat([alta, primera.reindex(alta.index)], axis=1).min(axis=1).drop(index=0, errors="ignore")
        self.primera = primera
        # Última fecha de compra por cliente hasta cada fecha: se calcula en `activos`
        self._fechas = self.ident[["cliente_key", "fecha"]]

    # ------------------------------------------------------------- activo
    def activos(self, fecha, W):
        """Clientes con al menos una boleta en (fecha − W, fecha]."""
        x = self._fechas
        sel = (x["fecha"] <= fecha) & (x["fecha"] > fecha - pd.Timedelta(days=W))
        return set(x.loc[sel, "cliente_key"])

    def primera_base(self, W):
        return (self.m.ini + pd.Timedelta(days=W - 1)) + pd.offsets.MonthEnd(0)

    # ------------------------------------------------------------- RBA y reposición
    def rba(self, W, fecha_base, nuevos="inicio", W_cierre=None):
        cierre = self.m.fin
        A0, A1 = self.activos(fecha_base, W), self.activos(cierre, W_cierre or W)
        ret, perd = A0 & A1, A0 - A1
        if nuevos == "inicio":
            nv = set(self.inicio[(self.inicio > fecha_base) & (self.inicio <= cierre)].index)
        else:
            nv = set(self.primera[self.primera > fecha_base].index)
        nuevos_act = (A1 & nv) - A0
        return {"ventana_dias": W, "fecha_base": fecha_base, "base_activa": len(A0), "retenidos": len(ret), "perdidos": len(perd),
                "RBA_pct": round(100 * len(ret) / len(A0), 1) if A0 else np.nan, "activos_cierre": len(A1),
                "nuevos_activos_cierre": len(nuevos_act), "reactivados_u_otros_cierre": len(A1 - ret - nuevos_act),
                "pct_cierre_retenidos": round(100 * len(ret) / len(A1), 1) if A1 else np.nan,
                "pct_cierre_nuevos": round(100 * len(nuevos_act) / len(A1), 1) if A1 else np.nan,
                "indice_reposicion": round(len(nuevos_act) / len(perd), 2) if perd else np.nan,
                "medible": fecha_base >= self.primera_base(W),
                "_A0": A0, "_A1": A1}

    def rba_segun_fecha_base(self, ventanas):
        filas = []
        for W in ventanas:
            for fb in pd.date_range(self.m.ini, self.m.fin, freq="ME"):
                if fb < self.primera_base(W) or fb >= self.m.fin:
                    continue
                r = self.rba(W, fb)
                filas.append({"ventana_dias": W, "fecha_base": fb.date(), "horizonte_meses": (self.m.fin.to_period("M") - fb.to_period("M")).n,
                              "base_activa": r["base_activa"], "RBA_pct": r["RBA_pct"], "indice_reposicion": r["indice_reposicion"]})
        return pd.DataFrame(filas)

    # ------------------------------------------------------------- intervalos y recompra
    def intervalos(self):
        x = self.ident.sort_values(["cliente_key", "fecha"])
        return x.groupby("cliente_key")["fecha"].diff().dt.days.dropna()

    def _segunda(self):
        x = self.ident.assign(f0=self.ident["cliente_key"].map(self.primera))
        sig = x[x["fecha"] > x["f0"]].groupby("cliente_key")["fecha"].min()
        dias = (sig.reindex(self.primera.index) - self.primera).dt.days
        expo = (self.m.fin - self.primera).dt.days
        return dias, expo

    def pct_vuelve(self, W):
        dias, expo = self._segunda()
        e = expo >= W
        return round(100 * (dias[e] <= W).mean(), 1)

    def wilson(self, k, n):
        if n == 0:
            return np.nan, np.nan, np.nan
        z, p_ = self.z, k / n
        c = (p_ + z ** 2 / (2 * n)) / (1 + z ** 2 / n)
        mg = z * np.sqrt(p_ * (1 - p_) / n + z ** 2 / (4 * n ** 2)) / (1 + z ** 2 / n)
        return 100 * p_, 100 * (c - mg), 100 * (c + mg)

    def nnv(self, H, grupo="nuevos"):
        dias, expo = self._segunda()
        es_nuevo = self.inicio.reindex(self.primera.index) >= self.m.ini
        mask = {"nuevos": es_nuevo, "antiguos": ~es_nuevo, "toda_primera": pd.Series(True, index=self.primera.index)}[grupo]
        e = mask & (expo >= H)
        n, k = int(e.sum()), int((~(dias[e] <= H)).sum())
        p_, lo, hi = self.wilson(k, n)
        return {"H_dias": H, "grupo": grupo, "elegibles": n, "no_vuelven": k, "pct_no_vuelve": round(p_, 1),
                "IC95_inf": round(lo, 1), "IC95_sup": round(hi, 1)}

    def nnv_sin_control(self):
        dias, _ = self._segunda()
        es_nuevo = self.inicio.reindex(self.primera.index) >= self.m.ini
        return round(100 * dias[es_nuevo].isna().mean(), 1)

    # ------------------------------------------------------------- trimestral
    def trimestral(self):
        x = self.ident.assign(trimestre=self.ident["fecha"].dt.quarter)
        cli_q = x.groupby("trimestre")["cliente_key"].apply(set)
        filas, vistos = [], set()
        for q in sorted(cli_q.index):
            c, sig = cli_q[q], cli_q.get(q + 1)
            nq = {k for k in c - vistos if pd.notna(self.inicio.get(k)) and self.inicio.get(k) >= self.m.ini}
            rq = c - nq
            vq = x[x["trimestre"] == q]
            filas.append({"trimestre": f"T{q}", "clientes_que_compran": len(c), "nuevos_en_el_trimestre": len(nq),
                          "boletas_por_cliente": round(len(vq) / len(c), 2), "ventas_reales_dic": round(vq["monto_real_dic"].sum()),
                          "gasto_real_por_cliente": round(vq["monto_real_dic"].sum() / len(c)),
                          "retencion_a_T+1_pct": round(100 * len(c & sig) / len(c), 1) if sig is not None else np.nan,
                          "retencion_nuevos_pct": round(100 * len(nq & sig) / len(nq), 1) if (sig is not None and nq) else np.nan,
                          "retencion_resto_pct": round(100 * len(rq & sig) / len(rq), 1) if (sig is not None and rq) else np.nan})
            vistos |= c
        return pd.DataFrame(filas)

    # ------------------------------------------------------------- cortes
    def por_formato(self, W, fecha_base, min_n=30):
        """RBA por formato de la tienda donde el cliente compró más veces antes de la base, con IC95 (Wilson)."""
        dt = self.m.dim_tienda.set_index("tienda_key")
        prev = self.ident[self.ident["fecha"] <= fecha_base].assign(formato=lambda d: d["tienda_key"].map(dt["formato"]))
        # Formato principal = donde más veces compró; si hay empate, el de su compra más reciente (regla explícita;
        # en la E1 el empate dependía del orden de las filas)
        cnt = prev.groupby(["cliente_key", "formato"]).agg(n=("fecha", "size"), ultima=("fecha", "max")).reset_index()
        fp = cnt.sort_values(["cliente_key", "n", "ultima", "formato"], ascending=[True, False, False, True]) \
                .drop_duplicates("cliente_key").set_index("cliente_key")["formato"]
        r = self.rba(W, fecha_base)
        A0, A1 = r["_A0"], r["_A1"]
        fp = fp[fp.index.isin(A0)]
        filas = []
        for fmt, ids in fp.groupby(fp).groups.items():
            ids = set(ids)
            p_, lo, hi = self.wilson(len(ids & A1), len(ids))
            filas.append({"formato": fmt, "base_activa": len(ids), "retenidos": len(ids & A1), "RBA_pct": round(p_, 1),
                          "IC95_inf": round(lo, 1), "IC95_sup": round(hi, 1), "muestra_chica": len(ids) < min_n})
        return pd.DataFrame(filas).sort_values("formato").reset_index(drop=True)

    # ------------------------------------------------------------- dinero
    def margen_pct(self):
        b = self.bol
        return b["margen_nominal"].sum() / b.loc[b["margen_nominal"].notna(), "monto_nominal"].sum()

    def caso_negocio(self, W, fecha_base):
        """Contrafactual: lo que habrían comprado los perdidos si se comportaran como los retenidos, menos lo que sí compraron."""
        ini = self.m.ini
        meses_base = fecha_base.month - ini.month + 1
        meses_resto = 12 - meses_base
        gp = self.ident[self.ident["fecha"] <= fecha_base].groupby("cliente_key")["monto_real_dic"].sum()
        post = self.ident[self.ident["fecha"] > fecha_base]
        r = self.rba(W, fecha_base)
        perd, ret = list(r["_A0"] - r["_A1"]), list(r["_A0"] & r["_A1"])
        proy_perd = gp.reindex(perd).fillna(0).sum() / meses_base * meses_resto
        proy_ret = gp.reindex(ret).fillna(0).sum() / meses_base * meses_resto
        real_perd = post.loc[post["cliente_key"].isin(perd), "monto_real_dic"].sum()
        real_ret = post.loc[post["cliente_key"].isin(ret), "monto_real_dic"].sum()
        realiz = real_ret / proy_ret if proy_ret else np.nan
        contraf = proy_perd * realiz - real_perd
        mp = self.margen_pct()
        # Piso y control por nivel de compra antes de la base (1, 2, 3 o más boletas)
        nb = self.ident[self.ident["fecha"] <= fecha_base].groupby("cliente_key").size()
        nivel = nb.clip(upper=3)
        gpost = post.groupby("cliente_key")["monto_real_dic"].sum()
        realiz_n, por_nivel = {}, 0.0
        for n in (1, 2, 3):
            rn = [c for c in ret if nivel.get(c) == n]
            pn = [c for c in perd if nivel.get(c) == n]
            proy_rn = gp.reindex(rn).fillna(0).sum() / meses_base * meses_resto
            realiz_n[n] = gpost.reindex(rn).fillna(0).sum() / proy_rn if proy_rn else np.nan
            proy_pn = gp.reindex(pn).fillna(0).sum() / meses_base * meses_resto
            por_nivel += proy_pn * realiz_n[n] - gpost.reindex(pn).fillna(0).sum()
        realiz_min = np.nanmin(list(realiz_n.values()))
        piso = proy_perd * realiz_min - real_perd
        return {"ventana_dias": W, "clientes_perdidos": len(perd), "proyeccion_cota_superior": proy_perd,
                "ventas_piso": piso, "margen_piso": piso * mp, "realizacion_minima_pct": round(100 * realiz_min, 1),
                "ventas_por_nivel": por_nivel,
                "gasto_real_perdidos_post_base": real_perd, "realizacion_retenidos_pct": round(100 * realiz, 1),
                "ventas_no_capturadas": contraf, "margen_no_capturado": contraf * mp, "margen_cota_superior": proy_perd * mp,
                "margen_pct": mp}

    def en_riesgo(self, fecha, desde, hasta):
        """Clientes cuya última compra fue hace entre `desde` y `hasta` días (inclusive) al `fecha`."""
        x = self._fechas[self._fechas["fecha"] <= fecha]
        dias = (fecha - x.groupby("cliente_key")["fecha"].max()).dt.days
        return set(dias[(dias >= desde) & (dias <= hasta)].index)

    def valor_recuperado(self, H):
        """Margen real promedio que deja un cliente identificado en H días después de una recompra (proxy del cliente recuperado)."""
        x = self.ident.sort_values(["cliente_key", "fecha"])
        mp = self.margen_pct()
        # Para cada cliente con al menos 2 compras: gasto en los H días desde su 2ª compra, solo si hay H días observables
        x["n"] = x.groupby("cliente_key").cumcount()
        seg = x[x["n"] == 1].set_index("cliente_key")["fecha"]
        seg = seg[seg <= self.m.fin - pd.Timedelta(days=H)]
        y = x[x["cliente_key"].isin(seg.index)].assign(f2=lambda d: d["cliente_key"].map(seg))
        gasto = y[(y["fecha"] >= y["f2"]) & (y["fecha"] < y["f2"] + pd.Timedelta(days=H))].groupby("cliente_key")["monto_real_dic"].sum()
        return float(gasto.mean() * mp), int(len(gasto))


def contacto_en_riesgo(ret: Retencion, fecha, desde, hasta, costo_contacto, descuento, tasa_respuesta, horizonte):
    """Caso de negocio de la recomendación: contactar a quienes llevan entre `desde` y `hasta` días sin comprar."""
    clientes = ret.en_riesgo(fecha, desde, hasta)
    n = len(clientes)
    margen_cliente, n_ref = ret.valor_recuperado(horizonte)
    recuperados = n * tasa_respuesta
    ticket = ret.ident["monto_real_dic"].mean()
    costo = n * costo_contacto + recuperados * ticket * descuento
    margen = recuperados * margen_cliente
    return {"clientes_en_riesgo": n, "recuperados_esperados": recuperados, "costo_total": costo, "margen_recuperado": margen,
            "beneficio_neto": margen - costo, "margen_por_cliente_recuperado": margen_cliente, "ticket_promedio": ticket,
            "clientes_referencia": n_ref, "tasa_equilibrio": (n * costo_contacto) / (n * (margen_cliente - ticket * descuento))
            if n and margen_cliente > ticket * descuento else np.nan}
