# Matriz de trazabilidad — requisitos funcionales

Cada requisito funcional de [`F3-requisitos-funcionales.docx`](Fase%201/Evidencias_Grupales/F3-requisitos-funcionales.docx)
(RF-01 a RF-36), con el objetivo específico al que responde, **dónde está implementado** y **qué
prueba automática lo verifica**. Es el cruce que el documento de requisitos dejó comprometido para
el bloque J del plan.

Actualizada al 5 de noviembre de 2026, sobre la rama que integra el cifrado en reposo, las cartolas,
las correcciones y los varios bancos.

## Cómo leer la matriz

| Estado | Significa |
|---|---|
| **Cumplido** | Está implementado y al menos una prueba automática lo verifica. |
| **Parcial** | Está implementado en lo principal, pero falta una parte del enunciado. La nota dice cuál. |

Las pruebas se nombran como `archivo › Clase` o `archivo › prueba`, con la cantidad de casos entre
paréntesis. Las del backend están en `backend/pruebas/` (salvo las del clasificador, en
`backend/clasificador/tests/`); las de la app, en `movil/src/utils/__tests__/`; las del simulador son
los scripts `simulador/app/prueba_*.py`.

## Resumen

| Objetivo específico | Requisitos | Cumplidos | Parciales |
|---|---|---|---|
| OE-1 — Ingesta y normalización | RF-06 … RF-14, RF-35 | 9 | 1 |
| OE-2 — Consumidor del SFA | RF-01 … RF-05, RF-33 | 5 | 1 |
| OE-3 — Clasificación automática | RF-15 … RF-19 | 3 | 2 |
| OE-4 — Detección de recurrencias | RF-20 … RF-22 | 3 | 0 |
| OE-5 — Proyección financiera | RF-23 … RF-26, RF-34, RF-36 | 5 | 1 |
| OE-6 — Cumplimiento Ley 21.719 | RF-27 … RF-32 | 5 | 1 |
| **Total** | **36** | **30** | **6** |

Ningún requisito quedó sin implementar. Los seis parciales están detallados en
[Lo que falta](#lo-que-falta).

---

## OE-2 — Consumidor del SFA

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-01 | Conectar una institución con el flujo de autorización (PAR + consentimiento) | `backend/api/conexiones.py` (`/conexiones/iniciar`, `/conexiones/retorno`), `backend/ingesta/cliente_sfa.py`, `simulador/app/sitio_banco.py` | `test_integracion.py › TestLaClaveNoPasaPorVelvet` (4), `› TestAislamientoEntreUsuarios` (5), `simulador/app/prueba_autorizacion.py` (24 comprobaciones) | Cumplido |
| RF-02 | Consentimiento granular (RAR): qué cuentas, qué datos y por cuánto tiempo | `PERMISOS` en `backend/ingesta/sincronizar.py`, `consentimiento.alcance_rar`, página de decisión del banco (`sitio_banco.pagina_consentimiento`) | `prueba_autorizacion.py` (rechazar, vencimiento), `test_integracion.py › TestDerechosDelTitular › test_otorgar_y_revocar_deja_rastro` | Parcial |
| RF-03 | Ciclo de vida de los tokens: guardado seguro, refresco automático, vencido o revocado como acción del usuario | Refresh token cifrado (`backend/ingesta/cifrado.py`), `ClienteSFA.renovar_acceso`, estado `autorizacion_vencida` y código `reautorizar` | `test_integracion.py › TestCifradoEnReposo › test_el_token_y_el_rut_del_banco_quedan_cifrados`, `› TestVariosBancos › test_un_permiso_vencido_en_un_banco_no_frena_al_otro`, `› test_sin_bancos_vinculados_pide_autorizar`, `prueba_clientes.py` (refresh) | Cumplido |
| RF-04 | Ver el estado de cada conexión por separado y revocar de forma granular | `GET /api/conexiones`, `DELETE /api/conexiones/{id}`, `movil/src/components/FilaConexion.tsx` | `test_integracion.py › TestVariosBancos › test_desvincular_un_banco_deja_el_otro`, `› test_si_un_banco_no_responde_el_otro_se_sincroniza_igual` | Cumplido |
| RF-05 | Consumir las APIs de Cuentas y de Operaciones de Crédito, con la paginación de la CMF | `ClienteSFA.listar_cuentas`, `obtener_movimientos` (paginado), `listar_creditos`; `backend/api/creditos.py` | `test_integracion.py › TestOperacionesDeCreditoYPaginacion` (2) | Cumplido |
| RF-33 | Registrarse, iniciar sesión y gestionar la sesión de forma segura | `backend/api/auth.py`, `backend/api/seguridad.py` (bcrypt, JWT); cuenta de prueba con `backend/preparar_demo.py` | `test_integracion.py › TestSesion` (4), `› TestCuentaDePrueba`, `› TestLaClaveNoPasaPorVelvet › test_iniciar_exige_sesion_de_velvet` | Cumplido |

## OE-1 — Ingesta y normalización

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-06 | Guardar el payload crudo tal como llegó | `Repositorio.guardar_crudo_bulk` / `leer_crudo` (MongoDB, cifrado autenticado: una alteración se detecta) | `test_integracion.py › TestCifradoEnReposo › test_el_payload_crudo_queda_cifrado_e_intacto`, `test_cartola.py › test_la_fila_cruda_se_guarda_completa`, `test_cifrado.py › test_un_dato_alterado_no_se_descifra` | Cumplido |
| RF-07 | Sincronizar cada conexión por separado: la caída de una no afecta a las demás | `sincronizar_todos` en `backend/ingesta/sincronizar.py`, segundo banco del simulador (`SFA_BANCO=austral`) | `test_integracion.py › TestVariosBancos` (8) | Cumplido |
| RF-08 | Normalizar al modelo canónico, venga de API, cartola o carga manual | `backend/ingesta/normalizador.py`, `backend/ingesta/importacion.py` | `test_integracion.py › TestLasCapasFuncionanSobreDatosReales` (4), `› TestCartolasYCargaManual › test_banco_fuera_del_sfa_con_vista_previa`, `› test_gasto_en_efectivo` | Cumplido |
| RF-09 | Deduplicar lo que llega por dos fuentes, conservando ambos orígenes | `backend/ingesta/dedup.py`, tabla `transaccion_origen`, `Repositorio.adoptar_desde_sfa` | `test_dedup.py` (12), `test_integracion.py › TestCartolasYCargaManual › test_historial_de_un_banco_conectado_se_fusiona_con_la_api`, `› test_la_api_adopta_lo_que_entro_antes_por_cartola` | Cumplido |
| RF-10 | Normalizar las glosas de comercio (`UBER *EATS 8829 SANTIAGO` → "Uber Eats") | El SFA entrega el nombre limpio del comercio (`merchantDetails.name`) y es el que se muestra; `clave_comercio` en `backend/motor/recurrencias.py` normaliza glosas para agrupar | `test_recurrencias.py › TestClaveComercio` (4), `› TestToleranciaDeGlosa` (2) | Parcial |
| RF-11 | Pendiente → confirmado: actualizar sin duplicar aunque cambie el monto | `Repositorio.upsert_transacciones_bulk` (por `transactionID`), `movil/src/utils/fusion.ts` | `test_integracion.py › TestPendienteAConfirmada`, `fusion.prueba.ts › actualiza sin duplicar cuando el mismo identificador llega con otro monto` | Cumplido |
| RF-12 | Importar cartolas CSV (instituciones fuera del SFA e historial antiguo) | `backend/ingesta/cartola.py`, `importacion.importar_cartola`, `POST /api/cartolas`, `movil/src/app/(tabs)/cuentas/cartola.tsx` | `test_cartola.py` (30), `test_integracion.py › TestCartolasYCargaManual` (9) | Cumplido |
| RF-13 | Registro manual de gastos, principalmente efectivo | `importacion.registrar_manual`, `POST` y `DELETE /api/movimientos`, `movil/src/app/(tabs)/gastos/nuevo.tsx` | `test_integracion.py › TestCartolasYCargaManual › test_gasto_en_efectivo`, `› test_validaciones_del_gasto_manual`, `› test_no_se_borra_lo_que_mando_un_banco` | Cumplido |
| RF-14 | Registrar las correcciones (recategorizar, duplicado, excluir, dividir) sin sobrescribir el original | `PUT /api/movimientos/{id}/categoria`, `backend/api/correcciones.py`, `movil/src/utils/porciones.ts` | `test_integracion.py › TestCorrecciones` (6), `porciones.prueba.ts` (5), `fusion.prueba.ts › conserva la categoría que corrigió el usuario…` | Cumplido |
| RF-35 | Indicar cuándo falta una cuenta por sincronizar y hasta cuándo el dato es confiable, sin mostrar un total que parezca completo | `datoAntiguo` y `datosHasta` en `GET /api/conexiones`; aviso de Inicio con `conexionesConProblema`; `FilaConexion` | `resumen.prueba.ts › conexionesConProblema` (3), `test_integracion.py › TestVariosBancos › test_si_un_banco_no_responde_el_otro_se_sincroniza_igual`, `› TestCartolasYCargaManual › test_banco_fuera_del_sfa_con_vista_previa` | Cumplido |

## OE-3 — Clasificación automática

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-15 | Clasificar cada transacción automáticamente | `backend/clasificador/` (cascada: reglas → modelo → abstención), llamado desde la ingesta | `test_clasificador.py` (11), `test_integracion.py › TestLasCapasFuncionanSobreDatosReales › test_los_gastos_llegan_clasificados` | Cumplido |
| RF-16 | Resolver los comercios conocidos con reglas antes del modelo | `backend/clasificador/reglas.py` | `test_clasificador.py › test_reglas_reconocen_comercios_conocidos`, `› test_cascada_usa_el_modelo_cuando_la_regla_no_reconoce` | Cumplido |
| RF-17 | Abstenerse cuando la confianza es baja | Umbral del clasificador; `categoria_id` queda NULL | `test_clasificador.py › test_modelo_se_abstiene_con_basura`, `› test_se_abstiene_sin_comercio`, `test_integracion.py › …test_lo_que_no_se_reconoce_queda_sin_categoria_y_no_inventado` | Cumplido |
| RF-18 | Bandeja de revisión con las tres categorías más probables | `movil/src/app/(tabs)/gastos/por-revisar.tsx`, `movil/src/utils/sugerencias.ts` | `sugerencias.prueba.ts` (12) | Parcial |
| RF-19 | Incorporar cada corrección al set de entrenamiento y al catálogo de comercios para reentrenar | `backend/clasificador/reentrenar.py` (solo correcciones con consentimiento, guardia de regresión) | `backend/prueba_clasificador_e2e.py` (script de punta a punta, no pytest) | Parcial |

## OE-4 — Detección de recurrencias

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-20 | Detectar recurrencias tolerando variación de monto, fecha y glosa | `backend/motor/recurrencias.py` | `test_recurrencias.py` (25), `test_integracion.py › …test_se_detectan_gastos_recurrentes` | Cumplido |
| RF-21 | Guardar cada recurrencia con periodicidad, monto esperado y próxima fecha | `Repositorio.guardar_suscripciones`, tabla `suscripcion` | `test_recurrencias.py › TestEstadoYProyeccion › test_estima_el_proximo_cobro`, `test_integracion.py › …test_se_detectan_gastos_recurrentes` | Cumplido |
| RF-22 | Confirmar o descartar cada suscripción detectada | `PATCH /api/suscripciones/{id}`, `movil/src/app/(tabs)/gastos/suscripciones.tsx` | `test_integracion.py › TestConfirmarSuscripciones` (2) | Cumplido |

## OE-5 — Proyección financiera

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-23 | Excedente mensual real (ingresos − fijos, cuotas y suscripciones) | `backend/motor/flujo.py`, `GET /api/flujo` | `test_flujo.py › TestExcedente` (4) | Cumplido |
| RF-24 | Proyectar metas con Monte Carlo y expresarlo con probabilidad | `backend/motor/proyeccion.py` | `test_proyeccion.py` (21), `metas.prueba.ts` (11) | Cumplido |
| RF-25 | Flujo de caja hasta el día de pago y la holgura disponible | `backend/motor/flujo.py`, `movil/src/components/PanelFlujo.tsx` | `test_flujo.py › TestFlujo` (7), `› TestProximoPago` (5), `› TestGastoVariable` (3) | Cumplido |
| RF-26 | Crear metas de ahorro y ver su proyección con probabilidad | `backend/api/metas.py`, `movil/src/app/(tabs)/metas/` | `test_integracion.py › …test_una_meta_se_proyecta_con_el_historial_real`, `metas.prueba.ts` (11) | Cumplido |
| RF-34 | Mostrar en el inicio cuánto hay disponible en el mes | `movil/src/app/(tabs)/index.tsx`, `resumenDelMes` | `resumen.prueba.ts › resumenDelMes` (5) | Cumplido |
| RF-36 | Configurar el sueldo y los gastos fijos | `PUT /api/perfil/sueldo` (cifrado), detección en `backend/motor/sueldo.py`; los fijos se confirman en Suscripciones | `test_sueldo.py` (13), `test_integracion.py › TestCifradoEnReposo › test_el_sueldo_queda_cifrado_y_se_sigue_leyendo`, `› TestConfirmarSuscripciones` | Parcial |

## OE-6 — Cumplimiento de la Ley 21.719

| RF | Qué pide | Dónde está | Pruebas | Estado |
|---|---|---|---|---|
| RF-27 | Mostrar qué se autorizó, a quién y por cuánto tiempo, y revocar de forma granular | `GET /api/privacidad/consentimientos`, `/finalidades`; `movil/src/app/(tabs)/cuentas/autorizaciones.tsx` | `test_integracion.py › TestDerechosDelTitular › test_el_consentimiento_de_tratamiento_llega_apagado`, `› test_otorgar_y_revocar_deja_rastro`, `› TestVariosBancos › test_desvincular_un_banco_deja_el_otro` | Cumplido |
| RF-28 | Registrar en la bitácora toda acción de acceso a datos personales | `backend/api/bitacora.py` (solo inserción; sobrevive anonimizada a la supresión) | `test_integracion.py › TestDerechosDelTitular › test_leer_los_movimientos_queda_en_la_bitacora`, `› test_borrar_la_cuenta_elimina_los_datos_pero_no_la_bitacora` | Parcial |
| RF-29 | Exportar todos los datos en formato estructurado (portabilidad) | `GET /api/privacidad/exportar` | `test_integracion.py › TestDerechosDelTitular › test_la_exportacion_no_incluye_credenciales`, `› TestCifradoEnReposo › test_el_sueldo_queda_cifrado_y_se_sigue_leyendo` | Cumplido |
| RF-30 | Borrar la cuenta y todos sus datos (supresión) | `DELETE /api/privacidad/cuenta` (Postgres en cascada y crudos de MongoDB) | `test_integracion.py › TestDerechosDelTitular › test_borrar_la_cuenta_exige_el_correo_exacto`, `› test_borrar_la_cuenta_elimina_los_datos_pero_no_la_bitacora`, `› TestCartolasYCargaManual › test_borrar_la_cuenta_se_lleva_tambien_los_crudos` | Cumplido |
| RF-31 | Cifrar en reposo los datos financieros sensibles | `backend/ingesta/cifrado.py` (AES-256-GCM, atado a campo y registro, clave rotable) | `test_cifrado.py` (20), `test_integracion.py › TestCifradoEnReposo` (4) | Cumplido |
| RF-32 | Detectar incidentes y notificar brechas en 72 horas | `backend/motor/brechas.py`, `backend/api/incidentes.py`, `backend/registrar_incidente.py`, `movil/src/app/(tabs)/cuentas/incidentes.tsx` | `test_brechas.py` (13), `test_integracion.py › TestAvisoDeBrechas` | Cumplido |

---

## Lo que falta

Los seis parciales, qué hay y qué falta. Ninguno impide la demostración: son partes del enunciado
que quedaron fuera del alcance construido.

- **RF-02 — Consentimiento granular.** En la página del banco la persona ve exactamente qué datos se
  piden, qué cuentas se compartirán y hasta cuándo vale el permiso (90 días), y puede autorizar o
  rechazar. **Falta** que pueda elegir un subconjunto: compartir solo algunas cuentas o algunos
  permisos. Hoy el alcance es fijo (`PERMISOS`) y se comparten todas las cuentas del cliente.
- **RF-10 — Normalizar las glosas.** Lo que llega por el SFA trae el nombre limpio del comercio y es el
  que se muestra, y el detector de recurrencias normaliza las glosas para agruparlas. **Falta**
  convertir una glosa sucia en un nombre de comercio para mostrarlo: la columna
  `transaccion.glosa_normalizada` existe pero no se llena, así que una línea de cartola como
  `COMPRA JUMBO LA FLORIDA` se ve tal cual (aunque se clasifica bien en Supermercado).
- **RF-18 — Las tres categorías más probables.** La bandeja "Por revisar" existe y sugiere categorías
  para cada movimiento. **Falta** que sean las tres más probables según el modelo: hoy son hasta dos,
  sacadas de las reglas, de la categoría que mandó el banco o de las que la persona más usa, porque la
  app no recibe las probabilidades del modelo.
- **RF-19 — Reentrenar con las correcciones.** Las correcciones (solo de quienes consintieron esa
  finalidad) reentrenan el modelo, con una guardia que descarta un modelo que empeora. **Falta**
  sumarlas también al catálogo de comercios de las reglas, y que el ciclo tenga una prueba en pytest:
  hoy lo verifica el script `backend/prueba_clasificador_e2e.py`.
- **RF-28 — Bitácora de toda acción de acceso.** Se registran la lectura de movimientos (agrupada cada
  30 minutos), la exportación, los consentimientos, vincular y desvincular bancos, la supresión, las
  correcciones, las cartolas y lo anotado a mano. **Falta** registrar las demás lecturas: cuentas,
  resumen, créditos, flujo, metas y perfil.
- **RF-36 — Configurar los gastos fijos.** El sueldo se declara (y se guarda cifrado) o se detecta de los
  abonos. Los gastos fijos se confirman o descartan entre los que detecta el sistema. **Falta** poder
  escribir a mano un gasto fijo que el sistema no detectó.

## Fuera de alcance declarado

No son requisitos funcionales de esta lista, pero conviene tenerlo a la vista: las capas del perfil
FAPI 2.0 que no se pueden ejercitar contra un simulador propio quedaron fuera a propósito y están
declaradas en `simulador/app/main.py` y `backend/ingesta/cliente_sfa.py`. Son mTLS entre
participantes, la firma JWS de los mensajes y el registro dinámico de clientes (DCR). Tampoco se
notifica a la autoridad de protección de datos desde el sistema: `registrar_incidente.py` avisa a los
afectados y recuerda que ese aviso se hace aparte.

## Cómo correr las pruebas

| Dónde | Qué necesita | Comando | Resultado |
|---|---|---|---|
| Backend (`backend/`) | Postgres y los dos bancos simulados (8001 y 8002); si falta alguno, las de integración se saltan solas | `python -m pytest` | 224 pruebas |
| App (`movil/`) | Nada | `npx jest` | 129 pruebas |
| Simulador (`simulador/`) | Nada | `python -m app.prueba_clientes` y `python -m app.prueba_autorizacion` | 23 y 24 comprobaciones |

Las de integración del backend levantan la API real contra una base desechable (`velvet_pruebas`) y
un MongoDB en memoria: nunca tocan la base de desarrollo.

Algunas pruebas no corresponden a un requisito funcional sino a cómo se presenta la información:
`formato.prueba.ts` (montos y fechas en español de Chile) y `animacion.prueba.ts` (curvas de
movimiento de la interfaz).
