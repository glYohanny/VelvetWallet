# Fase 2 — Desarrollo del Proyecto APT

**Velvet Wallet** · Capstone APT122 · Ingeniería en Informática · Duoc UC, sede Puerto Montt
**Integrantes:** PADRON JOSSUE · TORRES PEDRO
**Entregas:** informe de avance, semana 9 · informe final y presentación, semana 15

Misma estructura y convención de nombres que la Fase 1:
`Apellido_Nombre_<n°>_APT122_<Documento><Fase>.docx`

---

## Evidencias grupales

| Archivo | Qué contiene | Entrega |
|---|---|---|
| `2.4_GuiaEstudiante_Fase 2_DesarrolloProyecto APT.docx` | Resumen de avance por objetivo, plan de trabajo con estado y ajustes a partir del monitoreo | Semana 9 |
| `2.6_GuiaEstudiante_Fase 2_Informe Final Proyecto APT.docx` | Informe final: relevancia, objetivos, metodología, desarrollo, evidencias y reflexiones individuales | Semana 15 |

## Evidencias individuales

| Archivo | Integrante |
|---|---|
| `Torres_Pedro_2.1_APT122_DiarioReflexionFase2.docx` | Pedro Torres |

---

## Evidencias del desarrollo

El avance técnico de esta fase no vive en esta carpeta sino en el propio repositorio, que es
la evidencia principal:

| Dónde | Qué evidencia |
|---|---|
| `simulador/` | Proveedor de información del SFA conforme al Anexo N°3 de la NCG N°514, con su OpenAPI |
| `backend/ingesta/` | Pipeline de ingesta, normalización y deduplicación hacia el modelo canónico |
| `backend/motor/` | Motores de proyección Monte Carlo, flujo de caja, recurrencias, sueldo y plazos de brechas |
| `backend/pruebas/` | 224 pruebas del backend, unitarias y de integración (`python -m pytest`) |
| `backend/api/` | API del backend: autenticación, datos, conexiones, metas y privacidad |
| `BD/` | Esquema de PostgreSQL y MongoDB, con el entorno reproducible en Docker Compose |
| `movil/` | Aplicación móvil en React Native + Expo |
| `movil/src/utils/__tests__/` | 129 pruebas de la aplicación (`npx jest`) |
| `TRAZABILIDAD.md` | Matriz de trazabilidad: cada requisito funcional con su código, sus pruebas y su estado |

El historial de commits documenta el aporte individual de cada integrante.
