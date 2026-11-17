"""Paso 2a · DETECCIÓN de datos sucios. No modifica ningún dato.

Revisa cada fuente con chequeos genéricos (no dependen de conocer los datos de antemano) y deja
cada problema en salidas/calidad/ con las filas afectadas. Las decisiones se toman en limpieza.py.
Código trasladado de la sección 2 del notebook E1_pipeline_v2.ipynb, sin cambios de lógica.
"""
import os

import numpy as np
import pandas as pd

from .lectura import (decidir_orden, dv_rut, evidencia_punto, familia, firma, normalizar_texto,
                      parsear_descuento, parsear_fechas, parsear_numero, proponer_canonicos)

CLAVES = {"boletas": ["boleta_id"], "boleta_detalle": ["boleta_id", "linea"], "clientes": ["cliente_id"],
          "tiendas": ["tienda_id"], "comunas": ["comuna_id"], "regiones": ["region_id"], "medios_pago": ["medio_id"],
          "maestro": ["sku"]}
RELACIONES = [("comunas", "region_id", "regiones", "region_id"), ("tiendas", "comuna_id", "comunas", "comuna_id"),
              ("clientes", "comuna_id", "comunas", "comuna_id"), ("boletas", "tienda_id", "tiendas", "tienda_id"),
              ("boletas", "cliente_id", "clientes", "cliente_id"), ("boletas", "medio_id", "medios_pago", "medio_id"),
              ("boleta_detalle", "boleta_id", "boletas", "boleta_id"), ("boleta_detalle", "sku", "maestro", "sku")]
UMBRAL_MAYORIA = 0.95


def detectar(d, p, carpeta_calidad, log):
    os.makedirs(carpeta_calidad, exist_ok=True)
    pos, maestro_raw = d["pos"], d["maestro_raw"]
    ini, fin = p["periodo"]["inicio"], p["periodo"]["fin"]
    anio = p["periodo"]["anio"]
    TABLAS = {**pos, "maestro": maestro_raw}
    H = []

    def hallazgo(chequeo, tabla, columna, afectados, total, detalle="", archivo=""):
        H.append({"chequeo": chequeo, "tabla": tabla, "columna": columna, "afectados": int(afectados), "total": int(total),
                  "pct": round(100 * afectados / total, 2) if total else 0.0, "detalle": detalle, "archivo": archivo})

    def guardar(df, nombre):
        r = os.path.join(carpeta_calidad, f"{nombre}.csv")
        df.to_csv(r, index=False, encoding="utf-8-sig")
        return os.path.relpath(r, carpeta_calidad.parent.parent)

    # 2.1 Perfil de columnas y formatos mixtos
    perfil = []
    for t, df in TABLAS.items():
        for col in df.columns:
            s = df[col]
            nn = s[s.notna() & (s.astype(str).str.strip() != "")].astype(str)
            if nn.empty:
                continue
            fams = nn.map(familia).value_counts()
            num_o_fecha = (nn.str.contains(r"\d") & (nn.str.count(r"[A-Za-zÁÉÍÓÚáéíóúñÑ]") <= 3)).mean() >= 0.9
            perfil.append({"tabla": t, "columna": col, "filas": len(s), "nulos_o_vacios": len(s) - len(nn),
                           "valores_distintos": nn.nunique(), "n_familias_formato": len(fams),
                           "familias_principales": " | ".join(f"{k} ({v})" for k, v in fams.head(5).items()),
                           "formato_mixto": bool(num_o_fecha and len(fams) > 1)})
    perfil = pd.DataFrame(perfil)
    r = guardar(perfil, "01_perfil_columnas")
    for _, x in perfil[perfil["formato_mixto"]].iterrows():
        hallazgo("Formatos mixtos en la columna", x.tabla, x.columna, x.filas - x.nulos_o_vacios, x.filas, x.familias_principales, r)

    # 2.2 Filas fuera de patrón en el maestro
    firmas = maestro_raw["sku"].astype(str).str.strip().map(firma)
    vc = firmas.value_counts(normalize=True)
    basura_maestro = (firmas != vc.index[0]) if vc.iloc[0] >= 0.9 else pd.Series(False, index=maestro_raw.index)
    r = guardar(maestro_raw[basura_maestro], "02_maestro_filas_fuera_de_patron")
    hallazgo("Fila cuya clave no sigue el patrón de la columna", "maestro", "sku", basura_maestro.sum(), len(maestro_raw),
             f"patrón dominante '{vc.index[0]}'", r)
    maestro_sin_basura = maestro_raw[~basura_maestro]

    # 2.3 Duplicados y claves repetidas
    for t, clave in CLAVES.items():
        df = TABLAS[t] if t != "maestro" else maestro_sin_basura
        cmp_ = df.apply(lambda s: s.astype(str).str.strip().str.upper()) if t == "maestro" else df
        exactos = cmp_.duplicated(keep="first")
        sin_ex = cmp_[~exactos]
        rep = sin_ex.duplicated(clave, keep=False)
        if exactos.any():
            r = guardar(df[cmp_.duplicated(keep=False)].sort_values(clave), f"03_{t}_duplicados_exactos")
            hallazgo("Filas duplicadas exactas", t, "+".join(clave), exactos.sum(), len(df), "", r)
        if rep.any():
            r = guardar(df.loc[sin_ex[rep].index].sort_values(clave), f"03_{t}_clave_repetida")
            hallazgo("Clave repetida con contenido distinto", t, "+".join(clave), rep.sum(), len(df), "", r)

    # 2.3b Líneas con el mismo número dentro de una boleta
    det_orig = pos["boleta_detalle"]
    rep_lineas = det_orig[det_orig.duplicated(CLAVES["boleta_detalle"], keep=False)]
    pct_sku_distinto = (rep_lineas.groupby(CLAVES["boleta_detalle"])["sku"].nunique() > 1).mean() if len(rep_lineas) else np.nan
    lineas_rep_distintas = bool(len(rep_lineas)) and pct_sku_distinto >= 0.9

    # 2.4 Integridad referencial
    def norm_clave(s):
        return s.astype(str).str.strip().str.upper().str.replace(r"\.0$", "", regex=True)
    for t, col, tref, colref in RELACIONES:
        df = TABLAS[t]
        ref = maestro_sin_basura if tref == "maestro" else TABLAS[tref]
        nulos = df[col].isna() | (df[col].astype(str).str.strip() == "")
        huerf = ~nulos & ~norm_clave(df[col]).isin(set(norm_clave(ref[colref])))
        if huerf.any():
            r = guardar(df[huerf], f"04_{t}_{col}_huerfanos")
            vals = ", ".join(map(str, sorted(df.loc[huerf, col].astype(str).unique())[:10]))
            hallazgo("Referencia huérfana", t, col, huerf.sum(), len(df), f"no existe en {tref}.{colref}: {vals}", r)

    # 2.5 Fechas: orden día-mes decidido con los datos, y rango
    dp_bol, evid_bol = decidir_orden(pos["boletas"]["fecha"])
    dp_cli, evid_cli = decidir_orden(pos["clientes"]["fecha_alta"])
    fecha_boleta, fecha_boleta_alt, dep_bol = parsear_fechas(pos["boletas"]["fecha"], dp_bol)
    fecha_alta, fecha_alta_alt, dep_cli = parsear_fechas(pos["clientes"]["fecha_alta"], dp_cli)
    for nombre, serie, tabla in [("fecha", fecha_boleta, "boletas"), ("fecha_alta", fecha_alta, "clientes")]:
        if serie.isna().any():
            r = guardar(pos[tabla][serie.isna()], f"05_{tabla}_{nombre}_no_interpretable")
            hallazgo("Fecha no interpretable", tabla, nombre, serie.isna().sum(), len(serie), "", r)
    fuera = (fecha_boleta < ini) | (fecha_boleta > fin)
    r = guardar(pos["boletas"][fuera].assign(fecha_interpretada=fecha_boleta[fuera]), "05_boletas_fuera_de_periodo")
    hallazgo("Fecha fuera del período de análisis", "boletas", "fecha", fuera.sum(), len(fuera),
             f"período {ini:%d-%m-%Y} a {fin:%d-%m-%Y}", r)

    # 2.5b Fechas que dependen solo del supuesto día-mes
    amb_bol = int(dep_bol.sum())
    pct_fechas_supuesto = 100 * amb_bol / len(pos["boletas"])
    hallazgo("Fecha ambigua resuelta solo por el orden día-mes", "boletas", "fecha", amb_bol, len(pos["boletas"]),
             "ambos números <= 12: depende del supuesto")

    # 2.6 Números escritos como texto
    NUM = {}
    for t, col in [("boleta_detalle", "precio_unitario"), ("boleta_detalle", "monto_linea"),
                   ("maestro", "costo_unitario"), ("maestro", "precio_lista")]:
        df = TABLAS[t] if t != "maestro" else maestro_sin_basura
        share3 = evidencia_punto(df[col])
        miles = bool(share3 >= UMBRAL_MAYORIA) if not np.isnan(share3) else True
        NUM[(t, col)] = parsear_numero(df[col], miles)
        if miles:
            limpio = df[col].astype(str).str.strip().str.replace(" ", "").str.replace("$", "", regex=False)
            no_conf = limpio.str.contains(r"\.") & ~limpio.str.fullmatch(r"-?\d{0,3}(\.\d{3})+(,\d+)?")
            if no_conf.any():
                NUM[(t, col)] = NUM[(t, col)].mask(no_conf)
                r = guardar(df[no_conf], f"06_{t}_{col}_punto_no_conforme")
                hallazgo("Punto que no sigue el patrón de miles", t, col, no_conf.sum(), len(df), "se deja sin convertir", r)
        fallidos = NUM[(t, col)].isna() & df[col].astype(str).str.strip().ne("")
        especiales = df[col].astype(str).str.fullmatch(r"-\.\d{3}")
        if fallidos.any():
            r = guardar(df[fallidos], f"06_{t}_{col}_no_convertible")
            hallazgo("Número no convertible", t, col, fallidos.sum(), len(df), "", r)
        if especiales.any():
            r = guardar(df[especiales], f"06_{t}_{col}_negativo_sin_entero")
            hallazgo("Negativo escrito sin dígito antes del punto ('-.999')", t, col, especiales.sum(), len(df),
                     "se interpreta como -999", r)
    det_raw = pos["boleta_detalle"]
    DESC = pd.Series(parsear_descuento(det_raw["descuento"]), index=det_raw.index)

    # 2.7 Regla de negocio: monto = cantidad × precio × (1 − descuento)
    det_chk = det_raw.assign(precio=NUM[("boleta_detalle", "precio_unitario")], monto=NUM[("boleta_detalle", "monto_linea")],
                             desc=DESC, sku_n=det_raw["sku"].astype(str).str.strip().str.upper())
    det_chk["calculado"] = det_chk["cantidad"] * det_chk["precio"] * (1 - det_chk["desc"])
    det_chk["diferencia"] = det_chk["monto"] - det_chk["calculado"]
    det_chk["tipo"] = np.select(
        [det_chk["diferencia"] == 0, (det_chk["diferencia"].abs() < 1) & (det_chk["monto"] == np.trunc(det_chk["calculado"]))],
        ["exacta", "truncamiento"], "discrepancia")
    precio_lista = pd.Series(NUM[("maestro", "precio_lista")].values, index=maestro_sin_basura["sku"].str.strip().str.upper())
    precio_lista = precio_lista[~precio_lista.index.duplicated()]
    det_chk["precio_lista"] = det_chk["sku_n"].map(precio_lista)
    det_chk["unitario_implicito"] = det_chk["monto"] / (det_chk["cantidad"] * (1 - det_chk["desc"]))
    comparacion = det_chk.dropna(subset=["precio_lista"]).groupby(det_chk["tipo"] == "discrepancia").apply(lambda g: pd.Series({
        "precio": (g["precio"] / g["precio_lista"]).median(), "monto": (g["unitario_implicito"] / g["precio_lista"]).median()}))
    comparacion.index = comparacion.index.map({False: "sanas", True: "discrepancia"})
    if (det_chk["tipo"] == "discrepancia").any():
        r = guardar(det_chk[det_chk["tipo"] == "discrepancia"], "07_detalle_monto_discrepante")
        hallazgo("monto_linea no cumple cantidad × precio × (1 − descuento)", "boleta_detalle", "monto_linea",
                 (det_chk["tipo"] == "discrepancia").sum(), len(det_chk), "diferencia de $1 o más", r)
    # 2.7b control de magnitud
    razon_sanas = comparacion.loc["sanas", "precio"]
    assert 0.5 < razon_sanas < 2, "El precio unitario no se parece al precio de lista: revisar la interpretación del punto"

    # 2.8 Cantidades negativas: ¿devolución o error de signo?
    neg = det_chk["cantidad"] < 0
    fechas_b = pd.Series(fecha_boleta.values, index=pos["boletas"]["boleta_id"]).groupby(level=0).first()
    cliente_b = pos["boletas"].drop_duplicates("boleta_id").set_index("boleta_id")["cliente_id"]
    lin = det_chk.assign(fecha=det_chk["boleta_id"].map(fechas_b), cliente=det_chk["boleta_id"].map(cliente_b))
    lin_ident = lin.dropna(subset=["cliente"])
    primera_compra_sku = lin_ident[lin_ident["cantidad"] > 0].groupby(["cliente", "sku_n"])["fecha"].min()

    def compro_antes(df):
        prim = primera_compra_sku.reindex(list(zip(df["cliente"], df["sku_n"]))).values
        return (pd.Series(prim, index=df.index) < df["fecha"]).mean()
    pct_previo_neg = compro_antes(lin_ident[lin_ident["cantidad"] < 0]) if (lin_ident["cantidad"] < 0).any() else np.nan
    pos_l = lin_ident[lin_ident["cantidad"] > 0]
    pct_previo_base = compro_antes(pos_l.sample(min(2000, len(pos_l)), random_state=1))
    pos_mismo = det_chk[det_chk["cantidad"] > 0].groupby("boleta_id")["sku_n"].apply(set)
    pct_mismo_sku = det_chk[neg].apply(lambda x: x["sku_n"] in pos_mismo.get(x["boleta_id"], set()), axis=1).mean() if neg.any() else np.nan
    evidencia_devolucion = (pct_previo_neg > pct_previo_base + 0.10) or (pct_mismo_sku > 0.5)
    if neg.any():
        r = guardar(det_chk[neg], "08_detalle_cantidad_negativa")
        hallazgo("Cantidad negativa", "boleta_detalle", "cantidad", neg.sum(), len(det_chk),
                 f"devolución probable: {evidencia_devolucion}", r)

    # 2.8b Cantidades atípicas
    cant_abs = det_chk["cantidad"].abs()
    q1, q3 = cant_abs.quantile([0.25, 0.75])
    lim_cant = q3 + 3 * (q3 - q1)
    at_cant = cant_abs > lim_cant
    pct_monto_confirma = (det_chk.loc[at_cant, "tipo"] != "discrepancia").mean() if at_cant.any() else np.nan
    evidencia_cantidad_real = bool(at_cant.any()) and pct_monto_confirma >= 0.9
    if at_cant.any():
        r = guardar(det_chk[at_cant], "08b_detalle_cantidad_atipica")
        hallazgo("Cantidad atípica (más allá de Q3 + 3×RIC)", "boleta_detalle", "cantidad", at_cant.sum(), len(det_chk),
                 f"monto la confirma en {100 * pct_monto_confirma:.0f}%", r)

    # 2.9 Columnas redundantes que se contradicen (mes vs fecha; region vs tienda)
    b = pos["boletas"].copy()
    b["fecha_interpretada"] = fecha_boleta
    mes_inc = pd.to_numeric(b["mes"], errors="coerce") != fecha_boleta.dt.month
    r = guardar(b[mes_inc], "09_boletas_mes_inconsistente")
    hallazgo("Columna 'mes' distinta del mes de la fecha", "boletas", "mes", mes_inc.sum(), len(b), "", r)
    camp_val = []
    for _, c in d["campanas_raw"].iterrows():
        d_c = float(str(c["descuento_pct"]).replace("%", "").replace(",", ".")); d_c = d_c / 100 if d_c >= 1 else d_c
        skus_c = set(d["campana_sku_raw"].loc[d["campana_sku_raw"]["campana_id"] == c["campana_id"], "sku"].str.strip().str.upper())
        i_c, f_c = pd.Timestamp(c["fecha_ini"]), pd.Timestamp(c["fecha_fin"])
        l = det_chk[det_chk["sku_n"].isin(skus_c) & (det_chk["desc"].round(4) == round(d_c, 4))].merge(
            b[["boleta_id", "fecha_interpretada", "mes"]].drop_duplicates("boleta_id"), on="boleta_id")
        meses_camp = set(pd.period_range(i_c, f_c, freq="M").month)
        camp_val.append({"campana": c["campana_id"], "lineas": len(l),
                         "pct_fecha": 100 * l["fecha_interpretada"].between(i_c.normalize(), f_c).mean() if len(l) else np.nan,
                         "pct_mes": 100 * pd.to_numeric(l["mes"]).isin(meses_camp).mean() if len(l) else np.nan})
    camp_val = pd.DataFrame(camp_val)
    geo = pos["tiendas"].merge(pos["comunas"], on="comuna_id", how="left").merge(pos["regiones"], on="region_id", how="left")
    reg_inc = b["region"] != b["tienda_id"].map(geo.set_index("tienda_id")["region"])
    r = guardar(b[reg_inc], "09_boletas_region_inconsistente")
    hallazgo("Columna 'region' distinta de la región de la tienda", "boletas", "region", reg_inc.sum(), len(b), "", r)

    # 2.10 RUT y fecha de alta
    cli = pos["clientes"].copy()
    rut = cli["rut"].astype(str).str.upper().str.replace(r"[\s.]", "", regex=True)
    con_guion = rut.str.contains("-")
    cuerpo = np.where(con_guion, rut.str.split("-").str[0], rut.str[:-1])
    dv = np.where(con_guion, rut.str.split("-").str[1], rut.str[-1])
    cli["rut_valido"] = [c.isdigit() and dv_rut(c) == x for c, x in zip(cuerpo, dv)]
    cli["rut_cuerpo"] = [c if v else (r_ if not g else c) for c, r_, g, v in zip(cuerpo, rut, con_guion, cli["rut_valido"])]
    if (~cli["rut_valido"]).any():
        r = guardar(cli[~cli["rut_valido"]], "10_clientes_rut_invalido")
        hallazgo("RUT con dígito verificador inválido o ausente", "clientes", "rut", (~cli["rut_valido"]).sum(), len(cli), "", r)
    fa = pd.Series(fecha_alta.values, index=cli["cliente_id"])
    vt = pd.DataFrame({"cliente_id": pos["boletas"]["cliente_id"], "fecha": fecha_boleta}).dropna()
    primera = vt[vt["fecha"].between(ini, fin)].groupby("cliente_id")["fecha"].min()
    dias = (primera.reindex(fa.index) - fa).dt.days
    r = guardar(pd.DataFrame({"fecha_alta": fa, "primera_compra": primera.reindex(fa.index)})[dias < 0].reset_index(),
                "10_clientes_compra_antes_del_alta")
    hallazgo("Compras identificadas anteriores a la fecha de alta", "clientes", "fecha_alta", (dias < 0).sum(), len(fa), "", r)

    # 2.11 Variantes de escritura en la categoría
    variantes_cat = proponer_canonicos(maestro_sin_basura, "categoria", "subcategoria")
    r = guardar(variantes_cat, "11_maestro_categoria_variantes")
    no_canon = variantes_cat[variantes_cat["original"] != variantes_cat["propuesta"]]
    hallazgo("Categoría escrita de forma no canónica", "maestro", "categoria", no_canon["filas"].sum(), len(maestro_sin_basura),
             f"{variantes_cat['original'].nunique()} escrituras para {variantes_cat['propuesta'].nunique()} categorías", r)

    # 2.12 Promociones e IPC
    campanas_raw, campana_sku_raw = d["campanas_raw"], d["campana_sku_raw"]
    notac = campanas_raw["descuento_pct"].map(lambda x: type(x).__name__ + ":" + familia(x))
    if notac.nunique() > 1:
        hallazgo("Descuento de campaña en notaciones distintas", "promociones", "descuento_pct", len(campanas_raw),
                 len(campanas_raw), ", ".join(notac.unique()))
    skus_m = set(maestro_sin_basura["sku"].str.strip().str.upper())
    fuera_m = ~campana_sku_raw["sku"].str.strip().str.upper().isin(skus_m)
    if fuera_m.any():
        r = guardar(campana_sku_raw[fuera_m], "12_promociones_sku_inexistente")
        hallazgo("SKU en promoción que no existe en el maestro", "promociones", "sku", fuera_m.sum(), len(campana_sku_raw), "", r)
    ipc = pd.DataFrame(d["ipc_raw"]["serie"])
    ipc["mes"] = pd.to_datetime(ipc["fecha"], utc=True).dt.tz_localize(None).dt.to_period("M")
    ipc = ipc[ipc["mes"].dt.year == anio].sort_values("mes").reset_index(drop=True)

    resumen = pd.DataFrame(H)
    resumen.to_csv(os.path.join(carpeta_calidad, "00_resumen_calidad.csv"), index=False, encoding="utf-8-sig")
    log.info(f"Detección: {len(resumen)} problemas de calidad detectados (detalle en {carpeta_calidad})")
    return {
        "resumen_calidad": resumen, "basura_maestro": basura_maestro, "maestro_sin_basura": maestro_sin_basura,
        "NUM": NUM, "det_chk": det_chk, "comparacion": comparacion, "rep_lineas": rep_lineas,
        "pct_sku_distinto": pct_sku_distinto, "lineas_rep_distintas": lineas_rep_distintas,
        "fecha_boleta": fecha_boleta, "fecha_boleta_alt": fecha_boleta_alt, "fecha_alta": fecha_alta,
        "fecha_alta_alt": fecha_alta_alt, "evid_orden_boletas": evid_bol, "pct_fechas_supuesto": pct_fechas_supuesto,
        "evidencia_devolucion": evidencia_devolucion, "lim_cant": lim_cant, "at_cant": at_cant,
        "pct_monto_confirma": pct_monto_confirma, "evidencia_cantidad_real": evidencia_cantidad_real,
        "mes_inc": mes_inc, "reg_inc": reg_inc, "camp_val": camp_val, "cli": cli, "variantes_cat": variantes_cat,
        "ipc": ipc,
    }
