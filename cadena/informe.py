"""Cifras del informe: cada número del PDF y de la presentación sale de aquí.

Cada cifra tiene una ETIQUETA estable (por ejemplo, RBA_90). En el informe se escribe la etiqueta
y al final se reemplaza por el valor de salidas/cifras_informe.csv. Nunca se escriben números a mano.
"""
import os

import numpy as np
import pandas as pd

from .metricas import Retencion, contacto_en_riesgo


def calcular(m, p, extra, log, carpeta):
    os.makedirs(carpeta, exist_ok=True)
    mt, cn = p["metrica"], p["caso_negocio"]
    W, Wa, FB, FBC, fin = mt["ventana_principal"], mt["ventana_alternativa"], mt["fecha_base"], mt["fecha_base_comun"], p["periodo"]["fin"]
    r = Retencion(m, "dia-mes", mt["z_95"])
    rp, ra = r.rba(W, FB), r.rba(Wa, FB)
    ficha = pd.DataFrame([{k: v for k, v in x.items() if not k.startswith("_")} for x in (rp, ra)])
    ficha.to_csv(f"{carpeta}/ficha_metrica.csv", index=False)

    # Misma fecha base para 30/90/180 (corrección de la P1)
    comun = pd.DataFrame([{k: v for k, v in r.rba(w, FBC).items() if not k.startswith("_")} for w in mt["ventanas_tablero"]])
    comun.to_csv(f"{carpeta}/ventanas_misma_fecha_base.csv", index=False)
    c90, c180 = comun.set_index("ventana_dias").loc[90], comun.set_index("ventana_dias").loc[180]

    # Matriz base × cierre
    m_b90_c30 = round(100 * len(rp["_A0"] & r.activos(fin, Wa)) / len(rp["_A0"]), 1)
    m_b30_c90 = round(100 * len(ra["_A0"] & r.activos(fin, W)) / len(ra["_A0"]), 1)
    rfb = r.rba_segun_fecha_base(sorted(set(mt["ventanas_sensibilidad"]) | set(mt["ventanas_extra"])))
    rfb.to_csv(f"{carpeta}/rba_segun_fecha_base.csv", index=False)
    rango90 = rfb.loc[rfb["ventana_dias"] == W, "RBA_pct"]
    sens = pd.DataFrame([{k: v for k, v in r.rba(w, FB).items() if not k.startswith("_")} for w in mt["ventanas_sensibilidad"]])
    sens.to_csv(f"{carpeta}/sensibilidad_ventana.csv", index=False)
    rp_alt_nuevo = r.rba(W, FB, nuevos="primera")

    gaps = r.intervalos()
    nnv_p, nnv_ant, nnv_alt = r.nnv(W, "nuevos"), r.nnv(W, "antiguos"), r.nnv(W, "toda_primera")
    nnv_180 = r.nnv(max(mt["horizontes_recompra"]), "nuevos")
    pd.DataFrame([r.nnv(h, g) for h in mt["horizontes_recompra"] for g in ("nuevos", "antiguos", "toda_primera")]).to_csv(
        f"{carpeta}/nuevos_que_no_vuelven.csv", index=False)
    trim = r.trimestral()
    trim.to_csv(f"{carpeta}/retencion_trimestral.csv", index=False)
    ret_q = trim["retencion_a_T+1_pct"].dropna().tolist()
    pf = r.por_formato(W, FB, mt["min_clientes_corte"])
    pf.to_csv(f"{carpeta}/retencion_por_formato.csv", index=False)
    caso = r.caso_negocio(W, FB)
    pd.DataFrame([caso, r.caso_negocio(Wa, FB)]).to_csv(f"{carpeta}/caso_negocio.csv", index=False)
    contacto = contacto_en_riesgo(r, fin, cn["dias_sin_compra_desde"], cn["dias_sin_compra_hasta"], cn["costo_contacto_clp"],
                                  cn["descuento_cupon_pct"], cn["tasa_respuesta"], cn["horizonte_valor_dias"])

    # Escenario de lectura de fechas mes-día (alternativa a validar con la gerencia)
    r_md = Retencion(m, "mes-dia", mt["z_95"])
    rp_md = r_md.rba(W, FB)
    nnv_md = r_md.nnv(W, "nuevos")

    # Cobertura
    cob = extra["cobertura"]
    n_orig, n_ident = cob["originales"], len(r.ident)
    excl = cob["duplicadas"] + cob["sin_fecha"] + cob["fuera_periodo"] + cob["monto_no_positivo"] + cob["anonimas"]
    cobertura = pd.DataFrame([
        {"motivo": "Duplicadas", "boletas": cob["duplicadas"]}, {"motivo": "Fecha no interpretable", "boletas": cob["sin_fecha"]},
        {"motivo": "Fuera del período", "boletas": cob["fuera_periodo"]}, {"motivo": "Monto neto ≤ 0", "boletas": cob["monto_no_positivo"]},
        {"motivo": "Anónimas", "boletas": cob["anonimas"]}, {"motivo": "TOTAL excluido de la métrica", "boletas": excl},
        {"motivo": "Usadas en la métrica", "boletas": n_ident}])
    cobertura["pct_sobre_originales"] = (100 * cobertura["boletas"] / n_orig).round(1)
    cobertura.to_csv(f"{carpeta}/cobertura.csv", index=False)
    pct_excl = round(100 * excl / n_orig, 1)
    bol = r.bol
    anon = bol["cliente_key"] == 0
    tick_anon = bol.loc[anon, "monto_real_dic"].mean() / bol.loc[~anon, "monto_real_dic"].mean()

    C = []

    def cifra(etiqueta, descripcion, valor, unidad=""):
        if isinstance(valor, (float, np.floating)):
            valor = round(float(valor), 2)
        C.append({"etiqueta": etiqueta, "descripcion": descripcion, "valor": valor, "unidad": unidad})

    cifra("BOLETAS_ORIG", "Boletas originales", n_orig, "boletas")
    cifra("BOLETAS_VALIDAS", "Boletas válidas del período", len(bol), "boletas")
    cifra("BOLETAS_METRICA", "Boletas usadas en la métrica (identificadas)", n_ident, "boletas")
    cifra("LINEAS_FACT", "Filas de fact_venta (líneas de boleta válidas)", len(m.fact), "líneas")
    cifra("PCT_EXCLUIDAS", "% de boletas originales excluidas de la métrica", pct_excl, "%")
    cifra("PCT_ANONIMAS_VALIDAS", "% de boletas válidas anónimas", round(100 * anon.mean(), 1), "%")
    cifra("PCT_VENTAS_IDENT", "% de ventas válidas de clientes identificados",
          round(100 * bol.loc[~anon, "monto_nominal"].sum() / bol["monto_nominal"].sum(), 1), "%")
    cifra("N_PROBLEMAS", "Problemas de calidad detectados", extra["n_problemas"], "problemas")
    cifra("FUENTE_IPC", "Fuente del IPC usada en esta corrida", extra["origen_ipc"])
    cifra("INFLACION", f"Inflación acumulada {p['periodo']['anio']}", round(extra["inflacion"], 2), "%")
    cifra("IMPACTO_MONTO", "Cambio en ventas si se usara monto_linea original", round(extra["impacto_monto"], 2), "%")
    cifra("IMPACTO_ATIPICA", "Cambio en ventas si las cantidades atípicas se dividieran por 10", round(-extra["impacto_atipica"], 2), "%")
    cifra("PCT_FECHAS_SUPUESTO", "% de boletas con fecha que depende del supuesto día-mes", round(extra["pct_fechas_supuesto"], 1), "%")
    cifra("MEDIANA_DIAS", "Mediana de días entre compras", gaps.median(), "días")
    cifra(f"PCT_RECOMPRA_{Wa}", f"% de recompras dentro de {Wa} días", round(100 * (gaps <= Wa).mean(), 1), "%")
    cifra(f"PCT_RECOMPRA_{W}", f"% de recompras dentro de {W} días", round(100 * (gaps <= W).mean(), 1), "%")
    cifra(f"PCT_VUELVE_{W}", f"% de clientes que vuelve dentro de {W} días tras su primera compra", r.pct_vuelve(W), "%")
    cifra(f"PCT_VUELVE_{Wa}", f"% de clientes que vuelve dentro de {Wa} días tras su primera compra", r.pct_vuelve(Wa), "%")
    cifra("FECHA_BASE", "Fecha base de la métrica principal", f"{FB:%d-%m-%Y}")
    cifra(f"RBA_{W}", f"RBA con W = {W} (principal), base {FB:%d-%m}", rp["RBA_pct"], "%")
    cifra(f"RBA_{Wa}", f"RBA con W = {Wa} (alternativa), base {FB:%d-%m}", ra["RBA_pct"], "%")
    cifra(f"BASE_{W}", f"Base activa al {FB:%d-%m} con W = {W}", rp["base_activa"], "clientes")
    cifra(f"RETENIDOS_{W}", f"Retenidos al cierre con W = {W}", rp["retenidos"], "clientes")
    cifra(f"PERDIDOS_{W}", f"Perdidos al cierre con W = {W}", rp["perdidos"], "clientes")
    cifra(f"ACTIVOS_CIERRE_{W}", f"Clientes activos al 31-dic con W = {W}", rp["activos_cierre"], "clientes")
    cifra(f"NUEVOS_CIERRE_{W}", f"Nuevos activos al cierre con W = {W}", rp["nuevos_activos_cierre"], "clientes")
    cifra(f"PCT_CIERRE_NUEVOS_{W}", f"% de la base al cierre que es nueva (W = {W})", rp["pct_cierre_nuevos"], "%")
    cifra(f"REPOSICION_{W}", f"Índice de reposición W = {W}", rp["indice_reposicion"], "nuevos por perdido")
    cifra(f"REPOSICION_{Wa}", f"Índice de reposición W = {Wa}", ra["indice_reposicion"], "nuevos por perdido")
    cifra("REPOSICION_ALT_NUEVO", "Índice de reposición W = 90 con 'nuevo' = primera compra observada", rp_alt_nuevo["indice_reposicion"], "nuevos por perdido")
    cifra(f"MATRIZ_B{W}_C{Wa}", f"Base W={W} medida con W={Wa} al cierre", m_b90_c30, "%")
    cifra(f"MATRIZ_B{Wa}_C{W}", f"Base W={Wa} medida con W={W} al cierre", m_b30_c90, "%")
    cifra(f"RBA_{W}_RANGO_FB", f"RBA W={W}: rango según la fecha base", f"{rango90.min()} – {rango90.max()}", "%")
    cifra("FECHA_BASE_COMUN", "Fecha base común para comparar 30/90/180 días", f"{FBC:%d-%m-%Y}")
    for w, fila in comun.set_index("ventana_dias").iterrows():
        cifra(f"RBA_{w}_BASE_COMUN", f"RBA con W = {w}, misma fecha base {FBC:%d-%m}", fila["RBA_pct"], "%")
        cifra(f"REPOSICION_{w}_BASE_COMUN", f"Índice de reposición con W = {w}, misma fecha base {FBC:%d-%m}", fila["indice_reposicion"], "nuevos por perdido")
    cifra("NNV_90", f"% de nuevos que no vuelven en {W} días (con control de exposición)", nnv_p["pct_no_vuelve"], "%")
    cifra("NNV_90_IC95", f"IC95 del NNV_{W}", f"{nnv_p['IC95_inf']} – {nnv_p['IC95_sup']}", "%")
    cifra("NNV_90_N", f"Nuevos elegibles para NNV_{W}", nnv_p["elegibles"], "clientes")
    cifra("NNV_180", f"% de nuevos que no vuelven en {max(mt['horizontes_recompra'])} días", nnv_180["pct_no_vuelve"], "%")
    cifra("NNV_90_ANTIGUOS", f"% de antiguos que no vuelven en {W} días", nnv_ant["pct_no_vuelve"], "%")
    cifra("NNV_90_ALT_NUEVO", f"NNV_{W} con definición alternativa de nuevo", nnv_alt["pct_no_vuelve"], "%")
    cifra("NNV_SIN_CONTROL", "% de nuevos sin segunda compra en el año (sin control, sesgado)", r.nnv_sin_control(), "%")
    cifra("RET_TRIM", "Retención trimestral T1→T2 / T2→T3 / T3→T4", " / ".join(str(v) for v in ret_q), "%")
    cifra("RET_TRIM_ULTIMA", "Retención trimestral T3→T4", ret_q[-1], "%")
    cifra("CLIENTES_T1_T4", "Clientes que compran en T1 / T4", f"{trim['clientes_que_compran'].iloc[0]} / {trim['clientes_que_compran'].iloc[-1]}", "clientes")
    cifra("GASTO_CLIENTE_T1_T4", "Gasto real por cliente T1 / T4", f"{trim['gasto_real_por_cliente'].iloc[0]} / {trim['gasto_real_por_cliente'].iloc[-1]}", "$ dic-2025")
    cifra("RBA_FORMATO_RANGO", f"RBA W={W} por formato: mínimo – máximo", f"{pf['RBA_pct'].min()} – {pf['RBA_pct'].max()}", "%")
    cifra("PCT_ANONIMAS_ORIG", "% de boletas originales excluidas por anónimas", round(100 * cob["anonimas"] / n_orig, 1), "%")
    cifra("TICKET_ANON_REL", "Ticket anónimo / identificado", round(100 * tick_anon), "%")
    cifra("MARGEN_PCT", "Margen bruto promedio", round(100 * caso["margen_pct"], 1), "%")
    cifra("VENTAS_NO_CAPTURADAS", f"Ventas no capturadas por los perdidos (W={W}, central)", round(caso["ventas_no_capturadas"]), "$ dic-2025")
    cifra("MARGEN_NO_CAPTURADO", f"Margen no capturado por los perdidos (W={W}, central)", round(caso["margen_no_capturado"]), "$ dic-2025")
    cifra("VENTAS_COTA_SUP", f"Ventas no capturadas, cota superior (W={W})", round(caso["proyeccion_cota_superior"]), "$ dic-2025")
    cifra("MARGEN_COTA_SUP", f"Margen no capturado, cota superior (W={W})", round(caso["margen_cota_superior"]), "$ dic-2025")
    cifra("REALIZACION_RETENIDOS", f"Realización de los retenidos (W={W})", caso["realizacion_retenidos_pct"], "%")
    cifra("RIESGO_N", f"Clientes con {cn['dias_sin_compra_desde']} a {cn['dias_sin_compra_hasta']} días sin comprar al 31-dic", contacto["clientes_en_riesgo"], "clientes")
    cifra("RIESGO_COSTO", "Costo de contactarlos (contacto + cupón a los que vuelven)", round(contacto["costo_total"]), "$")
    cifra("RIESGO_MARGEN", "Margen recuperado esperado", round(contacto["margen_recuperado"]), "$ dic-2025")
    cifra("RIESGO_NETO", "Beneficio neto esperado del contacto", round(contacto["beneficio_neto"]), "$ dic-2025")
    cifra("RIESGO_TASA_EQUILIBRIO", "Tasa de respuesta mínima para no perder plata", round(100 * contacto["tasa_equilibrio"], 1), "%")
    cifra("RBA_90_MESDIA", f"RBA W={W} si las fechas ambiguas fueran mes-día", rp_md["RBA_pct"], "%")
    cifra("REPOSICION_90_MESDIA", f"Índice de reposición W={W} si las fechas fueran mes-día", rp_md["indice_reposicion"], "nuevos por perdido")
    cifra("NNV_90_MESDIA", f"NNV_{W} si las fechas fueran mes-día", nnv_md["pct_no_vuelve"], "%")

    cifras = pd.DataFrame(C)
    cifras.to_csv(f"{carpeta.parent}/cifras_informe.csv", index=False, encoding="utf-8-sig")
    log.info(f"Informe: {len(cifras)} cifras en salidas/cifras_informe.csv · RBA_{W} = {rp['RBA_pct']}% · NNV_{W} = {nnv_p['pct_no_vuelve']}%")
    return cifras, {"rba_principal": rp["RBA_pct"], "base_principal": rp["base_activa"], "retenidos": rp["retenidos"],
                    "perdidos": rp["perdidos"], "cobertura_cierra": n_orig == excl + n_ident,
                    "pct_usadas": 100 * n_ident / n_orig, "nnv_principal": nnv_p["pct_no_vuelve"]}
