"""Paso 2b · DECISIONES de limpieza. Cada problema detectado recibe una decisión, y cada decisión
aplicada queda en el registro de limpieza (base de la bitácora de supuestos del informe).

Las decisiones "auto" se resuelven con la evidencia de la detección; el grupo puede fijar otra opción aquí.
Código trasladado de la sección 3 del notebook E1_pipeline_v2.ipynb, sin cambios de lógica.
"""
import numpy as np
import pandas as pd

from .lectura import normalizar_texto

DECISIONES = {
    "duplicados_exactos": "eliminar",
    "fuera_de_periodo": "excluir",
    "monto_discrepante": "auto",      # auto | recalcular | monto_linea
    "cantidad_negativa": "auto",      # auto | valor_absoluto | devolucion
    "mes_vs_fecha": "auto",           # auto | usar_fecha | usar_mes
    "categorias": "aplicar_propuesta",
    "sku_repetido": "preferir_activo",
    "linea_repetida": "auto",         # auto | conservar_ambas | eliminar_repetidas
    "cantidad_atipica": "auto",       # auto | conservar | dividir_por_10
}
# Conocimiento externo (no se puede deducir de los datos)
CORRECCIONES_MANUALES = {"comunas": {("comuna", "La Florida"): {"region_id": 1}}}   # La Florida es de la Región Metropolitana
CATEGORIAS_MANUALES = {}
PREFIJOS_PERSONA = ("Sr.", "Sra.", "Familia")   # tratamientos de persona natural (para separar nombres de negocio)


def limpiar(d, ev, p, log):
    pos = d["pos"]
    ini, fin = p["periodo"]["inicio"], p["periodo"]["fin"]
    dec = dict(DECISIONES)
    comp = ev["comparacion"]
    if dec["monto_discrepante"] == "auto":
        dev_precio = abs(comp.loc["discrepancia", "precio"] - comp.loc["sanas", "precio"]) if "discrepancia" in comp.index else 0
        dev_monto = abs(comp.loc["discrepancia", "monto"] - comp.loc["sanas", "monto"]) if "discrepancia" in comp.index else 0
        dec["monto_discrepante"] = "recalcular" if dev_monto > dev_precio else "monto_linea"
    if dec["cantidad_negativa"] == "auto":
        dec["cantidad_negativa"] = "devolucion" if ev["evidencia_devolucion"] else "valor_absoluto"
    if dec["mes_vs_fecha"] == "auto":
        okf, okm = ev["camp_val"]["pct_fecha"].dropna(), ev["camp_val"]["pct_mes"].dropna()
        dec["mes_vs_fecha"] = "usar_fecha" if (okf.mean() if len(okf) else 100) >= (okm.mean() if len(okm) else 0) else "usar_mes"
    if dec["linea_repetida"] == "auto":
        dec["linea_repetida"] = "conservar_ambas" if (ev["lineas_rep_distintas"] or ev["rep_lineas"].empty) else "eliminar_repetidas"
    if dec["cantidad_atipica"] == "auto":
        dec["cantidad_atipica"] = "conservar" if (ev["evidencia_cantidad_real"] or not ev["at_cant"].any()) else "dividir_por_10"

    REG = []

    def registrar(fuente, regla, afectados, total, accion, motivo, efecto):
        REG.append({"n": len(REG) + 1, "fuente": fuente, "regla": regla, "registros_afectados": int(afectados),
                    "total_registros": int(total), "pct_afectado": round(100 * afectados / total, 2) if total else 0.0,
                    "accion": accion, "motivo": motivo, "efecto_si_el_supuesto_fuera_falso": efecto})

    # 3.2 Geografía, clientes y maestro
    comunas = pos["comunas"].copy()
    for (col_c, valor), cambios in CORRECCIONES_MANUALES.get("comunas", {}).items():
        filtro = comunas[col_c].astype(str).str.strip() == valor
        for col, nuevo in cambios.items():
            registrar("POS · comunas", f"Corrección manual: {col_c} = {valor}", filtro.sum(), len(comunas), f"{col} → {nuevo}",
                      "Referencia huérfana; se corrige con conocimiento externo.", "Sin corregir, esa comuna queda sin región.")
            comunas.loc[filtro, col] = nuevo

    cli = ev["cli"]
    clientes = pos["clientes"].copy()
    clientes["fecha_alta"] = ev["fecha_alta"].values
    clientes["fecha_alta_alt"] = ev["fecha_alta_alt"].values
    clientes = clientes.merge(cli[["cliente_id", "rut_valido", "rut_cuerpo"]], on="cliente_id", how="left")
    nombres = clientes["nombre"].astype(str).str.strip()
    clientes["tipo_nombre"] = np.where(nombres.str.split().str[0].isin(PREFIJOS_PERSONA), "persona", "nombre de negocio")
    registrar("POS · clientes", "fecha_alta convertida desde varios formatos", len(clientes), len(clientes), "Fecha estándar",
              "Formatos mixtos; orden día-mes decidido con evidencia.", "—")

    basura = ev["basura_maestro"]
    maestro_raw = d["maestro_raw"]
    m = maestro_raw[~basura].copy()
    registrar("Maestro (CSV)", "Filas cuya clave no sigue el patrón del SKU", basura.sum(), len(maestro_raw), "Eliminadas",
              "No son productos.", "—")
    for col in ["sku", "nombre", "categoria", "subcategoria", "marca", "proveedor"]:
        m[col] = m[col].astype(str).str.strip()
    m["sku"] = m["sku"].str.upper()
    m["costo_unitario"] = ev["NUM"][("maestro", "costo_unitario")].loc[m.index]
    m["precio_lista"] = ev["NUM"][("maestro", "precio_lista")].loc[m.index]
    VERD, FALS = {"si", "1", "true", "s", "activo", "yes"}, {"no", "0", "false", "n", "inactivo"}
    act = m["activo"].map(normalizar_texto)
    desconocido = ~act.isin(VERD | FALS)
    m["activo"] = np.where(act.isin(VERD), True, np.where(act.isin(FALS), False, None))
    registrar("Maestro (CSV)", "Valor de 'activo' vacío o no reconocido", desconocido.sum(), len(m), "Se deja como desconocido",
              "No se puede inferir el estado.", "Solo afecta la preferencia entre SKU repetidos.")
    vc = ev["variantes_cat"]
    mapa_cat = dict(zip(vc["normalizado"], vc["propuesta"]))
    mapa_cat.update(CATEGORIAS_MANUALES)
    cat_antes = m["categoria"].copy()
    m["categoria"] = m["categoria"].map(normalizar_texto).map(mapa_cat)
    registrar("Maestro (CSV)", "Categoría normalizada a su forma canónica", (cat_antes != m["categoria"]).sum(), len(m),
              f"{cat_antes.nunique()} escrituras → {m['categoria'].nunique()} categorías", "Variantes de escritura.",
              "Solo afecta cortes por categoría.")
    if m["categoria"].isna().any():
        raise ValueError(f"Categorías sin resolver: {cat_antes[m['categoria'].isna()].unique()}. Agréguenlas a CATEGORIAS_MANUALES.")
    orden = m.assign(_act=m["activo"].map({True: 0, False: 2}).fillna(1)).sort_values(["sku", "_act"], kind="stable")
    rep = orden.duplicated("sku", keep="first")
    registrar("Maestro (CSV)", "SKU repetido", rep.sum(), len(m), "Se conserva el registro activo (o el primero)",
              "Una clave debe identificar un solo producto.", "Si el vigente fuera el otro, cambia el costo de ese SKU.")
    maestro = orden[~rep].drop(columns="_act").sort_values("sku").reset_index(drop=True)

    # 3.3 Boletas
    boletas = pos["boletas"].copy()
    boletas["fecha"] = ev["fecha_boleta"].values
    boletas["fecha_alt"] = ev["fecha_boleta_alt"].values
    n_orig = len(boletas)
    dup = boletas.drop(columns="fecha_alt").duplicated()
    registrar("POS · boletas", "Filas duplicadas exactas", dup.sum(), n_orig, "Eliminadas (se conserva una)",
              "La misma transacción cargada dos veces.", "Si fueran compras distintas, la frecuencia estaría levemente subestimada.")
    boletas = boletas[~dup]
    sin_fecha = boletas["fecha"].isna()
    registrar("POS · boletas", "Fecha no interpretable", sin_fecha.sum(), len(boletas), "Eliminadas", "Sin fecha no se ubica en el tiempo.", "—")
    boletas = boletas[~sin_fecha]
    fuera_p = ~boletas["fecha"].between(ini, fin)
    registrar("POS · boletas", "Fecha fuera del período de análisis", fuera_p.sum(), len(boletas), "Excluidas",
              "Los meses fuera del período tienen un volumen muy inferior: son registros sueltos.",
              "Si fueran compras del período con el año mal digitado, se pierde ese porcentaje de boletas.")
    boletas = boletas[~fuera_p]
    registrar("POS · boletas", "Columna 'mes' no coincide con la fecha", ev["mes_inc"].sum(), n_orig,
              "Columna descartada" if dec["mes_vs_fecha"] == "usar_fecha" else "Se usa 'mes'",
              "La prueba con campañas indica que la fecha es la versión confiable.", "Si 'mes' fuera la correcta, esas boletas cambiarían de mes.")
    registrar("POS · boletas", "Columna 'region' no coincide con la tienda", ev["reg_inc"].sum(), n_orig,
              "Columna descartada; la región se toma de la tienda", "La región es atributo de la tienda.", "Solo afecta cortes por región.")
    boletas = boletas.drop(columns=["mes", "region"])

    # 3.4 Detalle y monto de cada boleta
    det_chk = ev["det_chk"]
    det = det_chk[det_chk["boleta_id"].isin(boletas["boleta_id"])].copy()
    registrar("POS · boleta_detalle", "Líneas de boletas excluidas", (~det_chk["boleta_id"].isin(boletas["boleta_id"])).sum(),
              len(det_chk), "Eliminadas", "Pertenecen a boletas fuera del período o duplicadas.", "—")
    det["sku"] = det["sku_n"]
    rep_det = det.duplicated(["boleta_id", "linea"], keep=False)
    if dec["linea_repetida"] == "conservar_ambas":
        registrar("POS · boleta_detalle", "Número de línea repetido dentro de la boleta", rep_det.sum(), len(det),
                  "Se conservan todas las líneas", f"Son productos distintos: el SKU difiere en {100 * ev['pct_sku_distinto']:.0f}% de los pares.",
                  "Si fueran copias, las ventas de esas boletas estarían sobrestimadas; la retención no cambia.")
    else:
        n_rep = det.duplicated(["boleta_id", "linea"]).sum()
        det = det[~det.duplicated(["boleta_id", "linea"])]
        registrar("POS · boleta_detalle", "Número de línea repetido", n_rep, len(det) + n_rep, "Se elimina la repetición", "Decisión del grupo.",
                  "Si fueran productos distintos, las ventas estarían subestimadas.")
    at_det = det["cantidad"].abs() > ev["lim_cant"]
    impacto_atipica = 100 * 0.9 * det.loc[at_det, "monto"].abs().sum() / det["monto"].abs().sum()
    if dec["cantidad_atipica"] == "dividir_por_10":
        det.loc[at_det, ["cantidad", "monto", "calculado"]] = det.loc[at_det, ["cantidad", "monto", "calculado"]] / 10
        registrar("POS · boleta_detalle", "Cantidad atípica", at_det.sum(), len(det), "Se divide por 10", "Decisión del grupo.",
                  f"Si fueran compras reales, las ventas estarían subestimadas en {impacto_atipica:.2f}%.")
    else:
        registrar("POS · boleta_detalle", "Cantidad atípica", at_det.sum(), len(det), "Se conserva",
                  f"El monto registrado confirma la cantidad en {100 * ev['pct_monto_confirma']:.0f}% de los casos.",
                  f"Si fueran errores de digitación (×10), las ventas estarían sobrestimadas en {impacto_atipica:.2f}%.")
    if dec["cantidad_negativa"] == "valor_absoluto":
        n_neg = (det["cantidad"] < 0).sum()
        det["cantidad"] = det["cantidad"].abs(); det["monto"] = det["monto"].abs(); det["calculado"] = det["calculado"].abs()
        registrar("POS · boleta_detalle", "Cantidad negativa", n_neg, len(det), "Se toma el valor absoluto (error de signo)",
                  "No hay evidencia de devolución.", "Si fueran devoluciones, algunas boletas no contarían como visita.")
    else:
        registrar("POS · boleta_detalle", "Cantidad negativa", (det["cantidad"] < 0).sum(), len(det), "Devolución neteada en la boleta",
                  "La evidencia es compatible con devoluciones.", "Si fueran errores de signo, el monto estaría subestimado.")
    trunc = det["tipo"] == "truncamiento"
    registrar("POS · boleta_detalle", "Diferencia menor a $1 por decimales del descuento", trunc.sum(), len(det), "Se conserva monto_linea",
              "El monto es el cálculo sin decimales.", "—")
    disc = det["tipo"] == "discrepancia"
    if dec["monto_discrepante"] == "recalcular":
        det.loc[disc, "monto"] = np.trunc(det.loc[disc, "calculado"])
        registrar("POS · boleta_detalle", "monto_linea con discrepancia de $1 o más", disc.sum(), len(det),
                  "Monto recalculado = cantidad × precio × (1 − descuento)",
                  "El precio unitario coincide con el precio de lista y el monto no.", "Si el monto original fuera el correcto, cambian las ventas.")
    else:
        registrar("POS · boleta_detalle", "monto_linea con discrepancia", disc.sum(), len(det), "Se conserva monto_linea",
                  "Decisión del grupo.", "Si el correcto fuera el cálculo, cambian las ventas.")
    impacto_monto = 100 * (det_chk.loc[det.index, "monto"].abs().sum() / det["monto"].sum() - 1)

    monto_boleta = det.groupby("boleta_id")["monto"].sum()
    boletas["monto_nominal"] = boletas["boleta_id"].map(monto_boleta)
    no_compra = boletas["monto_nominal"] <= 0
    registrar("POS · boletas", "Boleta con monto neto ≤ 0", no_compra.sum(), len(boletas), "Excluida",
              "Una boleta sin compra neta no es una visita de compra.", "—")
    boletas_validas = boletas[~no_compra].copy()
    det = det[det["boleta_id"].isin(boletas_validas["boleta_id"])]
    anon = boletas_validas["cliente_id"].isna()
    registrar("POS · boletas", "Boleta sin cliente identificado (anónima)", anon.sum(), len(boletas_validas),
              "Conservada para ventas; excluida de la métrica de retención", "Sin tarjeta no se puede seguir al cliente.",
              "Si hubiera frecuentes sin tarjeta, la retención real sería mayor.")
    sku_fuera = ~det["sku"].isin(maestro["sku"])
    registrar("POS · boleta_detalle", "SKU vendido que no existe en el maestro", sku_fuera.sum(), len(det),
              "Conservado para ventas; sin costo (margen no calculable)", "POS y ERP no comparten la misma fuente de productos.",
              "El margen se calcula sobre el resto de las líneas.")

    # 3.5 Promociones e IPC
    campanas = d["campanas_raw"].copy()
    campanas["descuento_pct"] = campanas["descuento_pct"].map(
        lambda x: (lambda v: v / 100 if v >= 1 else v)(float(str(x).replace("%", "").replace(",", "."))))
    campanas["fecha_ini"] = pd.to_datetime(campanas["fecha_ini"])
    campanas["fecha_fin"] = pd.to_datetime(campanas["fecha_fin"])
    campanas["canales_lista"] = campanas["canales"]
    campanas["canales"] = campanas["canales"].map(lambda c: ", ".join(c) if isinstance(c, list) else c)
    campana_sku = d["campana_sku_raw"].assign(sku=d["campana_sku_raw"]["sku"].str.strip().str.upper())
    ipc = ev["ipc"].copy()
    ipc["indice_base_100"] = 100 * (1 + ipc["valor"] / 100).cumprod()
    ipc["factor_a_pesos_dic"] = ipc["indice_base_100"].iloc[-1] / ipc["indice_base_100"]
    inflacion = ipc["indice_base_100"].iloc[-1] - 100
    registrar("API IPC", f"Serie IPC leída desde: {d['origen_ipc']}", len(ipc), 12, "Variaciones encadenadas en un índice",
              "La API entrega variación mensual, no nivel.", f"La empresa usa 3% fijo; la serie da {inflacion:.2f}%.")

    registro = pd.DataFrame(REG)
    log.info(f"Limpieza: {len(registro)} decisiones aplicadas · {len(boletas_validas):,} boletas válidas · {len(det):,} líneas")
    cobertura = {"originales": n_orig, "duplicadas": int(dup.sum()), "sin_fecha": int(sin_fecha.sum()),
                 "fuera_periodo": int(fuera_p.sum()), "monto_no_positivo": int(no_compra.sum()), "anonimas": int(anon.sum())}
    return {"decisiones": dec, "registro": registro, "comunas": comunas, "clientes": clientes, "maestro": maestro,
            "boletas_validas": boletas_validas, "detalle": det, "campanas": campanas, "campana_sku": campana_sku, "ipc": ipc,
            "inflacion": inflacion, "impacto_monto": impacto_monto, "impacto_atipica": impacto_atipica, "cobertura": cobertura}
