"""Cadena de datos de Multitienda del Sur (IIC 3752, Grupo 12).

Pasos (cada uno lee solo del anterior):
  1. recepcion  -> copia exacta de las fuentes, con fecha y huella (data/recepcion/)
  2. bodega     -> datos depurados: detección de problemas + decisiones de limpieza (DuckDB, esquema `bodega`)
  3. gondola    -> modelo estrella con una sola tabla de hechos (DuckDB, esquema `gondola`)
  +  metricas   -> capa semántica: la métrica escrita una sola vez (la usan el informe y el tablero)
  +  calidad    -> pruebas automáticas en cada corrida (bloquean o avisan)
"""
