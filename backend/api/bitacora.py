# -*- coding: utf-8 -*-
"""
Bitácora de tratamiento de datos personales (RNF-18 / RF-28, Ley 21.719).

La ley obliga a llevar un registro de las actividades de tratamiento: qué se
hizo con los datos de una persona, cuándo, y a petición de quién. No basta con
poder consultarlo internamente — el titular tiene derecho a verlo.

Dos decisiones que vale la pena explicar:

**Solo se inserta.** La tabla no se actualiza ni se borra nunca. Un registro de
auditoría que se puede editar no sirve como registro de auditoría, porque
cualquiera podría borrar justamente el acceso que no quiere mostrar. Al suprimir
la cuenta, la fila no se elimina: pierde el `usuario_id` y queda anonimizada
(`ON DELETE SET NULL`), de modo que la estadística sobrevive sin el titular.

**No se registra todo, se registran los hechos de tratamiento.** Anotar cada
petición HTTP convertiría la bitácora en un log de servidor, que es otra cosa y
que además nadie puede leer. Se anota lo que la ley considera tratamiento: leer
los movimientos, exportarlos, otorgar o revocar un consentimiento, vincular o
desvincular un banco y suprimir la cuenta.

Nunca se guarda el contenido de los datos, solo qué se tocó y cuándo: la
bitácora no puede convertirse ella misma en una copia de los datos personales.
"""
import ipaddress

from fastapi import Request

# Acciones que se registran. Es una lista cerrada a propósito: si alguien
# agrega una acción nueva, tiene que decidir conscientemente que es un hecho de
# tratamiento y cómo se le explica a la persona.
ACCIONES = {
    "datos.leer":            "Se mostraron tus movimientos",
    "datos.exportar":        "Descargaste una copia de tus datos",
    "consentimiento.otorgar": "Autorizaste una finalidad de uso",
    "consentimiento.revocar": "Revocaste una finalidad de uso",
    "banco.vincular":        "Vinculaste una institución",
    "banco.desvincular":     "Desvinculaste una institución y se borraron sus datos",
    "cuenta.suprimir":       "Solicitaste eliminar tu cuenta y tus datos",
    "categoria.corregir":    "Corregiste la categoría de un movimiento",
    "perfil.actualizar":     "Cambiaste tu sueldo declarado",
    "datos.importar":        "Importaste una cartola",
    "datos.registrar_manual": "Anotaste un movimiento a mano",
    "datos.borrar_manual":   "Borraste un movimiento que habías anotado",
    "correccion.excluir":    "Marcaste un movimiento como que no es gasto",
    "correccion.duplicado":  "Marcaste un movimiento como duplicado",
    "correccion.dividir":    "Repartiste un gasto entre categorías",
    "correccion.deshacer":   "Deshiciste una corrección",
}


def ip_de(peticion: Request | None) -> str | None:
    """
    IP del cliente, si el servidor la conoce y es una IP de verdad.

    Se valida porque la columna es de tipo `inet`: un valor que no sea una
    dirección hace fallar el INSERT, y un INSERT fallido aborta la transacción
    de quien llamó. El cliente de pruebas de FastAPI, por ejemplo, se
    identifica como "testclient". Vale más perder el dato de origen que
    tumbar la operación que se estaba registrando.
    """
    if peticion is None or peticion.client is None:
        return None
    try:
        return str(ipaddress.ip_address(peticion.client.host))
    except ValueError:
        return None


def registrar(conn, usuario_id: str, accion: str, recurso: str,
              ip: str | None = None, agrupar_minutos: int | None = None) -> None:
    """
    Anota un hecho de tratamiento.

    Usa la conexión de quien llama para que quede dentro de la misma
    transacción: si la operación se deshace, su registro también. Anotar un
    acceso que finalmente no ocurrió sería tan incorrecto como no anotarlo.

    `agrupar_minutos` evita repetir el mismo hecho una y otra vez. Abrir la
    aplicación cinco veces en media hora son cinco lecturas de los mismos
    datos, y anotarlas por separado convierte la bitácora en un registro de
    peticiones que la persona no puede leer. Lo que la ley pide demostrar es
    que hubo acceso y cuándo, no cuántas veces se repintó una pantalla. Para
    los hechos que sí son decisiones —consentir, revocar, exportar, borrar— no
    se agrupa nunca: cada uno es único y tiene que quedar.

    Nunca interrumpe la operación principal: si la bitácora falla, se pierde el
    registro pero la persona no pierde su acción. Es una decisión discutible y
    por eso queda escrita: ante la duda, se prioriza que el usuario pueda
    operar.

    Para que eso sea cierto hace falta el SAVEPOINT. En PostgreSQL una
    sentencia fallida aborta la transacción completa: atrapar la excepción no
    basta, porque todo lo que venga después falla igual con "current
    transaction is aborted". El punto de retorno acota el daño a este INSERT.
    """
    if accion not in ACCIONES:
        raise ValueError(f"Acción no declarada en la bitácora: {accion}")
    try:
        with conn.transaction():
            if agrupar_minutos:
                reciente = conn.execute(
                    """SELECT 1 FROM bitacora_auditoria
                       WHERE usuario_id = %s AND accion = %s
                         AND ocurrido_at > now() - make_interval(mins => %s)
                       LIMIT 1""",
                    (usuario_id, accion, agrupar_minutos),
                ).fetchone()
                if reciente:
                    return

            conn.execute(
                """INSERT INTO bitacora_auditoria (usuario_id, accion, recurso, ip_origen)
                   VALUES (%s, %s, %s, %s)""",
                (usuario_id, accion, recurso[:120], ip),
            )
    except Exception:  # noqa: BLE001
        pass
