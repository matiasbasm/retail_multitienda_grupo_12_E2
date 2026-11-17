"""Tablero de la gerencia · Multitienda del Sur.

Una pantalla, una pregunta: ¿la cadena retiene a sus clientes o los repone con compradores de una sola vez?
Lee SOLO la góndola (modelo estrella) y la capa semántica (cadena/metricas.py): no calcula nada por su cuenta,
así que muestra los mismos números que el informe y se actualiza cada vez que corre `python run.py`.

Abrir:  streamlit run app/tablero.py
"""
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from cadena import almacen, metricas  # noqa: E402
from cadena.config import cargar_parametros, ruta  # noqa: E402

st.set_page_config(page_title="Retención de clientes · Multitienda del Sur", page_icon="🛒", layout="wide")

AZUL, NARANJA, AQUA, GRIS = "#2a78d6", "#eb6834", "#1baf7a", "#9a9890"
P = cargar_parametros()
MT, CN = P["metrica"], P["caso_negocio"]
FIN = P["periodo"]["fin"]


# ------------------------------------------------------------------ datos
@st.cache_resource(show_spinner=False)
def _candado():
    import threading
    return threading.Lock()   # una sola corrida a la vez, aunque haya varias personas con el tablero abierto


def correr_cadena(sin_api=False):
    """Corre run.py dentro de este proceso. Devuelve (código, salida). Código 0 = corrida publicada."""
    import io
    import traceback
    from contextlib import redirect_stdout

    import run as cadena_run
    salida = io.StringIO()
    with _candado():
        try:
            with redirect_stdout(salida):
                codigo = cadena_run.main(["--sin-api"] if sin_api else [])
            return codigo, salida.getvalue()
        except Exception:
            return 1, salida.getvalue() + "\n" + traceback.format_exc()


@st.cache_resource(show_spinner=False)
def _correr_cadena_una_vez():
    return correr_cadena()


def asegurar_datos():
    """En un ambiente nuevo (por ejemplo, Streamlit Cloud) no hay base todavía: se corre la cadena una vez."""
    if ruta(P["rutas"]["almacen"]).exists():
        return
    with st.spinner("Primera apertura: corriendo la cadena de datos (≈20 segundos)…"):
        codigo, salida = _correr_cadena_una_vez()
    if codigo != 0 or not ruta(P["rutas"]["almacen"]).exists():
        st.error("La cadena de datos no terminó bien, así que no hay una corrida que mostrar. Detalle:")
        log = ruta(P["rutas"]["log"])
        texto = log.read_text(encoding="utf-8")[-6000:] if log.exists() else ""
        st.code((salida[-4000:] + "\n--- log ---\n" + texto).strip() or "sin salida", language="text")
        _correr_cadena_una_vez.clear()
        st.stop()


@st.cache_resource(show_spinner=False)
def cargar(huella):
    con = almacen.conectar(P, solo_lectura=True)
    m = metricas.cargar(con, P)
    op = {t: con.execute(f"SELECT * FROM operacion.{t}").df() for t in ["ultima_corrida", "pruebas", "cifras", "recepcion", "corridas"]}
    con.close()
    rets = {e: metricas.Retencion(m, e, MT["z_95"]) for e in metricas.ESCENARIOS_FECHA}
    return m, op, rets


asegurar_datos()
huella = ruta(P["rutas"]["almacen"]).stat().st_mtime   # si la cadena vuelve a correr, el tablero recarga solo
m, op, RETS = cargar(huella)
ultima = op["ultima_corrida"].iloc[0]
cifras = op["cifras"].set_index("etiqueta")["valor"]
pruebas_ult = op["pruebas"][op["pruebas"]["corrida"] == ultima["corrida"]]


def pct(x, d=1):
    return "—" if pd.isna(x) else f"{x:.{d}f}%".replace(".", ",")


def num(x, d=0):
    return "—" if pd.isna(x) else f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clp(x):
    return "—" if pd.isna(x) else ("−" if x < 0 else "") + "$" + num(abs(x))


def mm(x):
    return f"${x / 1e6:,.1f} MM".replace(".", ",")


# ------------------------------------------------------------------ filtros (barra lateral)
with st.sidebar:
    st.header("Filtros")
    W = st.radio("Ventana de cliente activo", MT["ventanas_tablero"], index=MT["ventanas_tablero"].index(MT["ventana_principal"]),
                 format_func=lambda w: f"{w} días" + ("  (principal)" if w == MT["ventana_principal"] else ""), horizontal=True,
                 help="Un cliente está activo si compró al menos una vez en los últimos W días.")
    r_tmp = RETS["dia-mes"]
    bases = [d for d in pd.date_range(P["periodo"]["inicio"], FIN, freq="ME") if r_tmp.primera_base(W) <= d < FIN]
    defecto = MT["fecha_base"] if MT["fecha_base"] in bases else bases[0]
    FB = st.selectbox("Fecha base (desde cuándo se mide)", bases, index=bases.index(defecto), format_func=lambda d: f"{d:%d-%m-%Y}",
                      help=f"Con W = {W} días, la primera fecha base con historia completa es el {r_tmp.primera_base(W):%d-%m}.")
    esc = st.radio("Lectura de las fechas ambiguas", list(metricas.ESCENARIOS_FECHA), format_func=metricas.ESCENARIOS_FECHA.get,
                   help=f"{cifras['PCT_FECHAS_SUPUESTO']}% de las boletas trae fechas como 03/04/2025, que pueden leerse de las dos formas.")
    st.divider()
    st.subheader("Caso: contactar clientes en riesgo")
    rango = st.slider("Días sin comprar", 15, 120, (CN["dias_sin_compra_desde"], CN["dias_sin_compra_hasta"]))
    costo_c = st.number_input("Costo por cliente contactado ($)", 0, 5000, CN["costo_contacto_clp"], 50)
    tasa = st.slider("Tasa de respuesta esperada", 0.0, 0.5, float(CN["tasa_respuesta"]), 0.01, format="%.2f")
    desc = st.slider("Descuento del cupón", 0.0, 0.5, float(CN["descuento_cupon_pct"]), 0.05, format="%.2f")
    st.caption("Valores iniciales = supuestos del grupo (config/parametros.yaml), a validar con Marketing.")
    st.divider()
    st.subheader("Datos")
    st.caption(f"Última corrida: {pd.Timestamp(ultima['inicio']):%d-%m-%Y %H:%M}  \nPruebas: {int(ultima['pruebas_ok'])}/{int(ultima['pruebas_total'])} OK")
    sin_api = st.checkbox("Simular caída de la API del IPC", help="Para probar el respaldo: la cadena corre como si la API no respondiera.")
    if st.button("Actualizar datos (volver a correr la cadena)", type="primary", width="stretch"):
        with st.spinner("Corriendo la cadena: recepción → bodega → góndola → pruebas…"):
            codigo, salida = correr_cadena(sin_api)
        st.session_state["ultima_accion"] = (codigo, salida)
        st.rerun()

R = RETS[esc]
r = R.rba(W, FB)
r_alt = R.rba(MT["ventana_alternativa"] if W != MT["ventana_alternativa"] else MT["ventana_principal"], FB)
trim = R.trimestral()
nnv = R.nnv(MT["ventana_principal"], "nuevos")

# ------------------------------------------------------------------ título
st.title("¿La cadena retiene a sus clientes o los repone con compradores de una sola vez?")
st.caption(f"Período: año {P['periodo']['anio']} · clientes identificados con tarjeta · ventana {W} días · base {FB:%d-%m-%Y} → cierre {FIN:%d-%m-%Y} · "
           f"lectura de fechas: {metricas.ESCENARIOS_FECHA[esc].lower()}  \n"
           "**Para:** Gerencia Comercial y Marketing · **Cuándo:** al cierre de cada mes · **Qué decide:** a quién y cuándo contactar para asegurar la segunda compra.")
if "ultima_accion" in st.session_state:
    codigo, salida = st.session_state.pop("ultima_accion")
    if codigo == 0:
        st.success(f"Cadena actualizada: corrida {ultima['corrida']} publicada a las {pd.Timestamp(ultima['inicio']):%H:%M:%S} "
                   f"en {ultima['duracion_seg']} s · pruebas {int(ultima['pruebas_ok'])}/{int(ultima['pruebas_total'])} OK.", icon="✅")
    else:
        st.error("La corrida no se publicó (una prueba bloqueante falló o hubo un error). El tablero sigue mostrando la última corrida buena.")
        with st.expander("Ver detalle"):
            st.code(salida[-4000:], language="text")
st.caption(f"🔄 **Datos actualizados:** {pd.Timestamp(ultima['inicio']):%d-%m-%Y %H:%M:%S} · corrida {ultima['corrida']} · "
           f"pruebas de calidad {int(ultima['pruebas_ok'])}/{int(ultima['pruebas_total'])} en verde · IPC: {ultima['fuente_ipc']}")
if esc != "dia-mes":
    st.warning("Están viendo el escenario alternativo de lectura de fechas (mes-día). El número oficial usa día-mes, decidido con los datos.")
if ultima["estado_ipc"] != "api":
    st.warning(f"La API del IPC no respondió en la última corrida: los pesos reales usan el **{ultima['fuente_ipc']}**. Las métricas de retención (cuentan clientes) no cambian.")

st.info(f"**Regla de lectura:** un cliente **se retiene** si compró en los {W} días previos al {FB:%d-%m} **y** en los {W} días previos al 31-dic. "
        f"Un cliente **nuevo** es uno cuya relación empezó después del {FB:%d-%m}.", icon="📏")

# ------------------------------------------------------------------ cifra clave
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"Retención base activa · {W} días", pct(r["RBA_pct"]),
          delta=f"{r['RBA_pct'] - r_alt['RBA_pct']:+.1f} pts vs W = {r_alt['ventana_dias']}".replace(".", ","), delta_color="off",
          help=metricas.DEFINICIONES["RBA"])
c1.caption(f"{num(r['retenidos'])} de {num(r['base_activa'])} clientes activos al {FB:%d-%m} siguen activos al 31-dic")
c2.metric("Retención trimestral T3→T4", pct(trim['retencion_a_T+1_pct'].iloc[-2]),
          delta=f"{trim['retencion_a_T+1_pct'].iloc[-2] - trim['retencion_a_T+1_pct'].iloc[0]:+.1f} pts vs T1 → T2".replace(".", ","),
          delta_color="normal", help=metricas.DEFINICIONES["trimestral"])
c2.caption("Horizonte fijo de un trimestre: " + " → ".join(pct(v) for v in trim["retencion_a_T+1_pct"].dropna()))
c3.metric("Índice de reposición", num(r["indice_reposicion"], 2), help=metricas.DEFINICIONES["reposicion"])
c3.caption(f"{num(r['nuevos_activos_cierre'])} nuevos activos al cierre por {num(r['perdidos'])} perdidos: "
           + ("**repone más de lo que pierde**" if r["indice_reposicion"] > 1.05 else "**repone apenas lo que pierde**" if r["indice_reposicion"] >= 0.95 else "**no alcanza a reponer**"))
c4.metric(f"Nuevos que no vuelven ({MT['ventana_principal']} días)", pct(nnv["pct_no_vuelve"]), help=metricas.DEFINICIONES["NNV"])
c4.caption(f"De {num(nnv['elegibles'])} clientes nuevos con {MT['ventana_principal']} días observables (IC95 {pct(nnv['IC95_inf'])} – {pct(nnv['IC95_sup'])})")
st.caption(f"**Cobertura:** la métrica usa {pct(100 - float(cifras['PCT_EXCLUIDAS']))} de las boletas originales; "
           f"{pct(float(cifras['PCT_EXCLUIDAS']))} queda fuera (anónimas {pct(float(cifras['PCT_ANONIMAS_ORIG']))}, duplicadas y fuera de 2025). "
           "La RBA depende de la fecha base (el horizonte cambia); por eso va siempre junto a la retención trimestral.")

# ------------------------------------------------------------------ gráfico que explica la cifra
st.subheader(f"De {num(r['base_activa'])} clientes activos al {FB:%d-%m}, {num(r['retenidos'])} siguen; "
             f"la base al cierre se sostiene con {num(r['nuevos_activos_cierre'])} nuevos")
comp = pd.DataFrame([
    {"momento": f"Activos al {FB:%d-%m}", "grupo": "Siguen activos (retenidos)", "clientes": r["retenidos"], "orden": 1},
    {"momento": f"Activos al {FB:%d-%m}", "grupo": "Se perdieron", "clientes": r["perdidos"], "orden": 2},
    {"momento": "Activos al 31-dic", "grupo": "Siguen activos (retenidos)", "clientes": r["retenidos"], "orden": 1},
    {"momento": "Activos al 31-dic", "grupo": "Nuevos", "clientes": r["nuevos_activos_cierre"], "orden": 3},
    {"momento": "Activos al 31-dic", "grupo": "Reactivados u otros", "clientes": r["reactivados_u_otros_cierre"], "orden": 4},
])
color = alt.Color("grupo:N", title=None, legend=alt.Legend(orient="top"),
                  scale=alt.Scale(domain=["Siguen activos (retenidos)", "Se perdieron", "Nuevos", "Reactivados u otros"],
                                  range=[AZUL, NARANJA, AQUA, GRIS]))
barras = alt.Chart(comp).mark_bar(cornerRadiusEnd=4, stroke="white", strokeWidth=2).encode(
    y=alt.Y("momento:N", title=None, sort=[f"Activos al {FB:%d-%m}", "Activos al 31-dic"], scale=alt.Scale(paddingInner=0.35)),
    x=alt.X("sum(clientes):Q", title="Clientes"), color=color, order=alt.Order("orden:Q"),
    tooltip=[alt.Tooltip("momento:N", title="Momento"), alt.Tooltip("grupo:N", title="Grupo"), alt.Tooltip("clientes:Q", title="Clientes")])
etiquetas = alt.Chart(comp).mark_text(color="white", fontWeight="bold").encode(
    y=alt.Y("momento:N", sort=[f"Activos al {FB:%d-%m}", "Activos al 31-dic"], scale=alt.Scale(paddingInner=0.35)),
    x=alt.X("sum(clientes):Q", stack="zero", bandPosition=0.5), detail="grupo:N", order=alt.Order("orden:Q"), text="sum(clientes):Q")
st.altair_chart((barras + etiquetas).properties(height=210), width="stretch")
st.caption("Fuente: fact_venta (POS), clientes identificados. Elaboración propia, Grupo 12.")

# ------------------------------------------------------------------ ¿cambia la conclusión con otra ventana?
st.subheader("¿Cambia la conclusión si se usa otra ventana? Las tres, con la misma fecha base")
base_c = st.selectbox("Fecha base común", [d for d in bases if d >= R.primera_base(max(MT["ventanas_tablero"]))] or [MT["fecha_base_comun"]],
                      format_func=lambda d: f"{d:%d-%m-%Y}", key="base_comun",
                      help="La primera fecha en que las tres ventanas tienen historia completa.") \
    if any(d >= R.primera_base(max(MT["ventanas_tablero"])) for d in bases) else MT["fecha_base_comun"]
filas = []
for w in MT["ventanas_tablero"]:
    x = R.rba(w, base_c)
    filas.append({"Ventana": f"{w} días", "Base activa": x["base_activa"], "Retenidos": x["retenidos"], "Retención (RBA)": x["RBA_pct"],
                  "Nuevos activos al cierre": x["nuevos_activos_cierre"], "Perdidos": x["perdidos"], "Índice de reposición": x["indice_reposicion"],
                  "Conclusión": "repone más de lo que pierde" if x["indice_reposicion"] > 1.05 else
                  ("repone lo mismo que pierde" if x["indice_reposicion"] >= 0.95 else "pierde más de lo que repone")})
tv = pd.DataFrame(filas)
st.dataframe(tv, hide_index=True, width="stretch",
             column_config={"Retención (RBA)": st.column_config.NumberColumn(format="%.1f%%"),
                            "Índice de reposición": st.column_config.NumberColumn(format="%.2f")})
st.caption(f"Con la misma base ({base_c:%d-%m-%Y}), una ventana más larga retiene más porque exige menos para \"seguir activo\". "
           "La lectura de negocio no cambia: la mayoría de la base al cierre es nueva y 1 de cada 3 nuevos no vuelve.")

# ------------------------------------------------------------------ corte por la dimensión principal
st.subheader("Por formato de local: las diferencias caben en el margen de error (sin ranking)")
pf = R.por_formato(W, FB, MT["min_clientes_corte"])
base_pf = alt.Chart(pf).encode(y=alt.Y("formato:N", title=None, sort=None))
puntos = base_pf.mark_point(filled=True, size=90, color=AZUL).encode(
    x=alt.X("RBA_pct:Q", title="Retención de la base activa (%) con intervalo de confianza 95%", scale=alt.Scale(domain=[0, 100])),
    tooltip=[alt.Tooltip("formato:N", title="Formato"), alt.Tooltip("base_activa:Q", title="Clientes en la base"),
             alt.Tooltip("RBA_pct:Q", title="RBA %"), alt.Tooltip("IC95_inf:Q", title="IC95 inferior"), alt.Tooltip("IC95_sup:Q", title="IC95 superior")])
bigotes = base_pf.mark_rule(strokeWidth=2, color=AZUL).encode(x="IC95_inf:Q", x2="IC95_sup:Q")
total = alt.Chart(pd.DataFrame({"x": [r["RBA_pct"]]})).mark_rule(strokeDash=[4, 4], color=GRIS).encode(x="x:Q")
st.altair_chart((bigotes + puntos + total).properties(height=170), width="stretch")
chicas = pf[pf["muestra_chica"]]["formato"].tolist()
st.caption(f"Línea punteada: total cadena ({pct(r['RBA_pct'])}). Formato = donde el cliente compró más veces antes de la fecha base. "
           + (f"Muestra chica (menos de {MT['min_clientes_corte']} clientes): {', '.join(chicas)}. " if chicas else "")
           + "No conviene decidir por local con estos datos: la tienda registrada no refleja la cercanía al hogar.")

# ------------------------------------------------------------------ caso de negocio
st.subheader("¿Cuánto cuesta contactar a los que se están yendo y cuánto se recupera?")
cn = metricas.contacto_en_riesgo(R, FIN, rango[0], rango[1], costo_c, desc, tasa, CN["horizonte_valor_dias"])
cas = R.caso_negocio(W, FB)
k1, k2, k3, k4 = st.columns(4)
k1.metric(f"Clientes con {rango[0]}–{rango[1]} días sin comprar", num(cn["clientes_en_riesgo"]))
k2.metric("Costo de la acción", clp(cn["costo_total"]), help="Contacto a todos + descuento del cupón a los que vuelven.")
k3.metric(f"Margen recuperado ({CN['horizonte_valor_dias']} días)", clp(cn["margen_recuperado"]),
          help=f"Recuperados esperados × margen promedio que deja un cliente en {CN['horizonte_valor_dias']} días tras volver a comprar.")
k4.metric("Resultado neto", clp(cn["beneficio_neto"]))
k4.caption(f"Conviene si responde más del {pct(100 * cn['tasa_equilibrio'])} de los contactados" if pd.notna(cn["tasa_equilibrio"]) else "")
st.caption(f"Lo que costó no retener (W = {W}, base {FB:%d-%m}): los {num(cas['clientes_perdidos'])} perdidos dejaron "
           f"**{mm(cas['margen_no_capturado'])} de margen** sin capturar (ventas {mm(cas['ventas_no_capturadas'])}; "
           f"rango de margen: piso {mm(cas['margen_piso'])} – techo {mm(cas['margen_cota_superior'])}). Pesos de diciembre de 2025.")

# ------------------------------------------------------------------ detalle
st.subheader("Detalle")
t1, t2 = st.tabs(["Clientes a contactar", "Retención por trimestre"])
with t1:
    ids = R.en_riesgo(FIN, rango[0], rango[1])
    det = R.ident[R.ident["cliente_key"].isin(ids)].groupby("cliente_key").agg(
        ultima_compra=("fecha", "max"), compras_2025=("boleta_id", "size"), gasto_real_2025=("monto_real_dic", "sum")).reset_index()
    dc = m.dim_cliente.set_index("cliente_key")
    det["cliente_id"] = det["cliente_key"].map(dc["cliente_id"])
    det["segmento_actual"] = det["cliente_key"].map(dc["segmento_actual"])
    det["dias_sin_comprar"] = (FIN - det["ultima_compra"]).dt.days
    det = det[["cliente_id", "segmento_actual", "ultima_compra", "dias_sin_comprar", "compras_2025", "gasto_real_2025"]] \
        .sort_values(["dias_sin_comprar", "gasto_real_2025"], ascending=[True, False])
    st.dataframe(det, hide_index=True, width="stretch",
                 column_config={"ultima_compra": st.column_config.DateColumn("última compra", format="DD-MM-YYYY"),
                                "gasto_real_2025": st.column_config.NumberColumn("gasto 2025 ($ dic)", format="dollar")})
    st.download_button("Descargar lista (CSV)", det.to_csv(index=False).encode("utf-8-sig"), "clientes_a_contactar.csv", "text/csv")
with t2:
    st.dataframe(trim, hide_index=True, width="stretch")

# ------------------------------------------------------------------ pie
n_ok = int((pruebas_ult["resultado"] == "OK").sum())
st.divider()
st.caption(
    f"**Fuente:** POS (origen_pos.sqlite), maestro de productos, promociones e IPC ({ultima['fuente_ipc']}). "
    f"**Actualizado:** {pd.Timestamp(ultima['inicio']):%d-%m-%Y %H:%M} (corrida {ultima['corrida']}) · "
    f"**Pruebas de calidad:** {n_ok}/{len(pruebas_ult)} en verde · "
    f"**Dueño del dato:** {P['sla']['dueno']} · **Definiciones:** propuestas por el Grupo 12, pendientes de certificar por la Gerencia Comercial · "
    f"Montos en pesos de diciembre de 2025.")
with st.expander("Definiciones y estado de la cadena"):
    for k, v in metricas.DEFINICIONES.items():
        if not k.startswith("regla"):
            st.markdown(f"- {v}")
    st.dataframe(pruebas_ult[["codigo", "paso", "que_verifica", "si_falla", "resultado", "detalle"]], hide_index=True, width="stretch")
