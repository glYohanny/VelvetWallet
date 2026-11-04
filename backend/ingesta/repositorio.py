# -*- coding: utf-8 -*-
"""
Escritura en las dos bases.

  · MongoDB   → el payload crudo, tal como llegó, sin tocar (RF-06 / trazabilidad).
  · PostgreSQL → el dato normalizado, con UPSERT por id_externo.

El UPSERT es la pieza clave: en cada sincronización, si el movimiento ya existe
(mismo cuenta_id + id_externo) se ACTUALIZA; si no, se INSERTA. Eso es lo que
hace que una compra que pasa de pendiente a confirmada (mismo transactionID,
otro monto) se actualice en vez de duplicarse.

Las operaciones vienen en versión "una por una" y en versión "en lote" (bulk).
La ingesta usa las de lote: escribir los cientos de movimientos de un viaje en
pocas idas y vueltas a la nube, en vez de una por movimiento, es la diferencia
entre segundos y más de un minuto.
"""
from __future__ import annotations

import json
from datetime import datetime

from bson import ObjectId
from psycopg.types.json import Json

from . import config, esquema
from .cifrado import (cifrar, cifrar_alcance, ctx_payload, descifrar,
                      descifrar_alcance)
from .bootstrap import asegurar_conexion
from .conexiones_bd import mongo, pool

# Columnas de transaccion que escribe la ingesta, en orden fijo.
_COLS_TX = ["cuenta_id", "id_externo", "payload_crudo_ref", "monto", "moneda",
           "fecha", "glosa_original", "categoria_origen", "categoria_id",
           "confianza_clasificacion", "hash_dedup", "estado"]

# Un movimiento que el usuario recategorizó: su categoría es la de él, y ni una
# re-sincronización ni un modelo nuevo la pisan.
_CORREGIDO = ("EXISTS (SELECT 1 FROM correccion co WHERE co.transaccion_id = transaccion.id"
              " AND co.tipo = 'recategorizar')")

class Repositorio:
    def __init__(self):
        # Conexión prestada del pool (no se abre una nueva por sincronización)
        # y el cliente de Mongo compartido del proceso. Ver conexiones_bd.py.
        self.conn = pool().getconn()
        esquema.asegurar(self.conn)
        self._categorias: dict[str, str] | None = None   # nombre → categoria_id
        self.db = mongo()[config.MONGO_DB]

    # ── MongoDB: crudo intacto ──────────────────────────────────────────────
    # El payload se guarda cifrado (RF-31) pero intacto: se cifra el JSON tal
    # como llegó y se recupera idéntico con leer_crudo(). GCM además detecta
    # cualquier alteración, así que el crudo sigue sirviendo de prueba (RF-06).
    # El "sobre" (de qué conexión y endpoint vino, cuándo) queda en claro para
    # poder buscar y borrar por conexión sin descifrar nada.
    @staticmethod
    def _sellar(conexion_id: str, payload: dict) -> dict:
        return {"cifrado": cifrar(json.dumps(payload, ensure_ascii=False, sort_keys=True),
                                  ctx_payload(conexion_id))}

    def leer_crudo(self, ref: str) -> dict | None:
        """El payload tal como lo entregó el banco, descifrado. None si no existe."""
        doc = self.db.payload_crudo.find_one({"_id": ObjectId(ref)})
        if doc is None:
            return None
        payload = doc["payload"]
        if isinstance(payload, dict) and set(payload) == {"cifrado"}:
            return json.loads(descifrar(payload["cifrado"], ctx_payload(doc["conexion_id"])))
        return payload   # guardado antes del cifrado

    def guardar_crudo(self, conexion_id: str, endpoint: str, payload: dict) -> str:
        """Guarda un movimiento crudo y devuelve el ObjectId (24 hex) para la FK."""
        doc = {
            "conexion_id": str(conexion_id),
            "endpoint_origen": endpoint,
            "payload": self._sellar(conexion_id, payload),
            "procesado": True,
            "recibido_at": datetime.utcnow(),
        }
        return str(self.db.payload_crudo.insert_one(doc).inserted_id)

    def guardar_crudo_bulk(self, conexion_id: str, endpoint: str,
                           payloads: list[dict]) -> list[str]:
        """
        Guarda muchos movimientos crudos en UNA sola operación (insert_many) y
        devuelve sus ObjectId (como texto), en el mismo orden.
        """
        if not payloads:
            return []
        ahora = datetime.utcnow()
        docs = [
            {
                "conexion_id": str(conexion_id),
                "endpoint_origen": endpoint,
                "payload": self._sellar(conexion_id, p),
                "procesado": True,
                "recibido_at": ahora,
            }
            for p in payloads
        ]
        res = self.db.payload_crudo.insert_many(docs)
        return [str(_id) for _id in res.inserted_ids]

    # ── PostgreSQL: consentimiento ──────────────────────────────────────────
    def registrar_consentimiento(self, conexion_id: str, alcance_rar: dict,
                                 fecha_expiracion) -> str:
        """
        Deja registrado el consentimiento vigente de la conexión (RF-02 / RF-27).
        Si ya hay uno vigente, lo refresca; si no, lo crea.

        El refresh token y la identidad del cliente del banco se guardan
        cifrados (RF-31); el resto del alcance queda en claro.
        """
        alcance_rar = cifrar_alcance(alcance_rar, conexion_id)
        fila = self.conn.execute(
            """UPDATE consentimiento
               SET alcance_rar = %s, fecha_expiracion = %s
               WHERE conexion_id = %s AND estado = 'vigente'
               RETURNING id""",
            (Json(alcance_rar), fecha_expiracion, conexion_id),
        ).fetchone()
        if fila:
            return fila[0]

        fila = self.conn.execute(
            """INSERT INTO consentimiento (conexion_id, alcance_rar, fecha_expiracion)
               VALUES (%s, %s, %s) RETURNING id""",
            (conexion_id, Json(alcance_rar), fecha_expiracion),
        ).fetchone()
        return fila[0]

    def consentimiento_vigente(self, conexion_id: str) -> dict | None:
        """
        El alcance (alcance_rar) del consentimiento vigente de la conexión, o
        None si no hay. Ahí queda a qué cliente del banco corresponde la
        conexión (rutCliente) y el refresh token para renovar el acceso.
        """
        fila = self.conn.execute(
            """SELECT alcance_rar FROM consentimiento
               WHERE conexion_id = %s AND estado = 'vigente'
               ORDER BY fecha_inicio DESC LIMIT 1""",
            (conexion_id,),
        ).fetchone()
        return descifrar_alcance(fila[0], conexion_id) if fila else None

    def eliminar_conexion(self, conexion_id: str) -> None:
        """
        Desvincula un banco: borra la conexión y, en cascada, sus cuentas,
        consentimientos, movimientos y correcciones (FK ON DELETE CASCADE).
        También borra los payloads crudos de Mongo: si el usuario retira el
        permiso, sus datos no se quedan guardados (Ley 21.719).
        """
        self.db.payload_crudo.delete_many({"conexion_id": str(conexion_id)})
        self.conn.execute("DELETE FROM conexion WHERE id = %s", (conexion_id,))

    # ── PostgreSQL: upsert de cuenta ────────────────────────────────────────
    def upsert_cuenta(self, conexion_id: str, usuario_id: str, datos: dict) -> str:
        fila = self.conn.execute(
            """
            INSERT INTO cuenta (conexion_id, usuario_id, id_externo, tipo,
                                moneda, saldo, actualizado_at)
            VALUES (%(conexion_id)s, %(usuario_id)s, %(id_externo)s, %(tipo)s,
                    %(moneda)s, %(saldo)s, now())
            ON CONFLICT (conexion_id, id_externo) WHERE id_externo IS NOT NULL
            DO UPDATE SET saldo          = EXCLUDED.saldo,
                          moneda         = EXCLUDED.moneda,
                          tipo           = EXCLUDED.tipo,
                          actualizado_at = now()
            RETURNING id
            """,
            {"conexion_id": conexion_id, "usuario_id": usuario_id, **datos},
        ).fetchone()
        return fila[0]

    def upsert_creditos(self, conexion_id: str, usuario_id: str,
                        creditos: list[dict]) -> int:
        """
        Guarda los créditos que trajo el banco, y retira los que ya no vienen.

        Un crédito que desaparece del listado es uno que se terminó de pagar o
        que la institución dejó de exponer. Dejarlo en la base lo mostraría
        como vigente para siempre, que es peor que no mostrarlo: alguien
        creería que todavía debe algo que ya pagó.
        """
        vistos: list[str] = []
        for c in creditos:
            self.conn.execute(
                """
                INSERT INTO credito (conexion_id, usuario_id, id_externo, producto, tipo,
                                     moneda, estado, monto_original, cuota_mensual,
                                     plazo_meses, cuotas_restantes, saldo_actual,
                                     tasa_interes, tipo_tasa, proposito, dia_de_pago,
                                     en_mora, calendario_url, actualizado_at)
                VALUES (%(conexion_id)s, %(usuario_id)s, %(id_externo)s, %(producto)s, %(tipo)s,
                        %(moneda)s, %(estado)s, %(monto_original)s, %(cuota_mensual)s,
                        %(plazo_meses)s, %(cuotas_restantes)s, %(saldo_actual)s,
                        %(tasa_interes)s, %(tipo_tasa)s, %(proposito)s, %(dia_de_pago)s,
                        %(en_mora)s, %(calendario_url)s, now())
                ON CONFLICT (conexion_id, id_externo) DO UPDATE
                   SET producto         = EXCLUDED.producto,
                       estado           = EXCLUDED.estado,
                       cuota_mensual    = EXCLUDED.cuota_mensual,
                       cuotas_restantes = EXCLUDED.cuotas_restantes,
                       saldo_actual     = EXCLUDED.saldo_actual,
                       tasa_interes     = EXCLUDED.tasa_interes,
                       tipo_tasa        = EXCLUDED.tipo_tasa,
                       en_mora          = EXCLUDED.en_mora,
                       actualizado_at   = now()
                """,
                {"conexion_id": conexion_id, "usuario_id": usuario_id, **c},
            )
            vistos.append(c["id_externo"])

        self.conn.execute(
            "DELETE FROM credito WHERE conexion_id = %s AND NOT (id_externo = ANY(%s))",
            (conexion_id, vistos),
        )
        return len(vistos)

    # ── PostgreSQL: upsert de transacciones (en lote) ───────────────────────
    # ── PostgreSQL: categorías ──────────────────────────────────────────────
    def categoria_id(self, nombre: str | None) -> str | None:
        """
        id de la categoría de gasto con ese nombre; la crea si no existe (así
        funciona sobre una base sin el catálogo cargado). None si no hay nombre:
        el clasificador se abstuvo y categoria_id queda NULL.
        """
        if not nombre:
            return None
        if self._categorias is None:
            # Todo el catálogo de una vez (una ida y vuelta, no una por categoría).
            self._categorias = {}
            for n, cid in self.conn.execute(
                    "SELECT nombre, id FROM categoria WHERE tipo = 'gasto' ORDER BY id DESC"):
                self._categorias[n] = cid
        if nombre not in self._categorias:
            fila = self.conn.execute(
                "INSERT INTO categoria (nombre, tipo) VALUES (%s, 'gasto') RETURNING id",
                (nombre,)).fetchone()
            self._categorias[nombre] = fila[0]
        return self._categorias[nombre]

    def estado_actual(self, cuenta_id: str) -> dict[str, tuple]:
        """
        Lo que ya está guardado de la cuenta: id_externo → (monto, glosa,
        categoría del banco). Con esto la sincronización escribe SOLO lo nuevo o
        lo que cambió, en vez de reescribir el historial completo cada vez.
        """
        return {
            ext: (monto, glosa, cat)
            for ext, monto, glosa, cat in self.conn.execute(
                """SELECT id_externo, monto, glosa_original, categoria_origen
                   FROM transaccion WHERE cuenta_id = %s AND id_externo IS NOT NULL""",
                (cuenta_id,))
        }

    def upsert_transacciones_bulk(self, cuenta_id: str, refs: list[str],
                                  datos_list: list[dict]) -> dict:
        """
        Inserta/actualiza MUCHOS movimientos en UNA sola sentencia. Devuelve
        cuántos fueron nuevos, cuántos actualizados y cuántos llegaron igual.

          nuevo       → no existía y se insertó.
          actualizado → ya existía y el banco lo mandó distinto (p. ej. una
                        compra que pasó de pendiente a confirmada).
          sin cambio  → ya existía exactamente igual; no se tocó.

        El WHERE del DO UPDATE distingue los dos últimos: sin él, el UPDATE se
        dispara en cada sincronización para TODOS los existentes y el conteo
        diría que se actualizaron cientos cuando cambiaron tres. IS DISTINCT FROM
        (en vez de <>) compara bien contra NULL.

        La categoría que propone el clasificador se guarda al insertar. Al
        actualizar se recalcula, salvo que el usuario la haya corregido.
        """
        if not datos_list:
            return {"insertadas": 0, "actualizadas": 0, "sin_cambio": 0}

        marcador = "(" + ",".join(["%s"] * len(_COLS_TX)) + ")"
        marcadores = ",".join([marcador] * len(datos_list))
        params: list = []
        for ref, d in zip(refs, datos_list):
            params.extend([
                cuenta_id, d["id_externo"], ref, d["monto"], d["moneda"],
                d["fecha"], d["glosa_original"], d["categoria_origen"],
                self.categoria_id(d.get("categoria_nombre")),
                d.get("confianza_clasificacion"), d["hash_dedup"], d["estado"],
            ])

        sql = (
            "INSERT INTO transaccion (" + ", ".join(_COLS_TX) + ") VALUES "
            + marcadores
            + " ON CONFLICT (cuenta_id, id_externo) WHERE id_externo IS NOT NULL"
            + " DO UPDATE SET monto = EXCLUDED.monto,"
            + "               hash_dedup = EXCLUDED.hash_dedup,"
            + "               payload_crudo_ref = EXCLUDED.payload_crudo_ref,"
            + "               glosa_original = EXCLUDED.glosa_original,"
            + "               categoria_origen = EXCLUDED.categoria_origen,"
            + "               categoria_id = CASE WHEN " + _CORREGIDO
            + "                   THEN transaccion.categoria_id ELSE EXCLUDED.categoria_id END,"
            + "               confianza_clasificacion = CASE WHEN " + _CORREGIDO
            + "                   THEN transaccion.confianza_clasificacion"
            + "                   ELSE EXCLUDED.confianza_clasificacion END"
            + " WHERE transaccion.monto            IS DISTINCT FROM EXCLUDED.monto"
            + "    OR transaccion.glosa_original   IS DISTINCT FROM EXCLUDED.glosa_original"
            + "    OR transaccion.categoria_origen IS DISTINCT FROM EXCLUDED.categoria_origen"
            + " RETURNING (xmax = 0) AS insertado"
        )
        filas = self.conn.execute(sql, params).fetchall()
        insertadas = sum(1 for f in filas if f[0])
        return {"insertadas": insertadas, "actualizadas": len(filas) - insertadas,
                "sin_cambio": len(datos_list) - len(filas)}

    def clasificar_sin_categoria(self, conexion_id: str, clasificar) -> int:
        """
        Pasa por el clasificador los gastos de la conexión que siguen sin
        categoría (llegaron antes de que existiera, o el modelo mejoró desde
        entonces). No toca los que corrigió el usuario. Devuelve cuántos
        quedaron clasificados.

        `clasificar(glosa, monto) -> (categoria, confianza)`.
        """
        filas = self.conn.execute(
            """
            SELECT t.id, t.glosa_original, t.monto
            FROM transaccion t JOIN cuenta c ON c.id = t.cuenta_id
            WHERE c.conexion_id = %s AND t.categoria_id IS NULL AND t.monto < 0
              AND NOT EXISTS (SELECT 1 FROM correccion co
                              WHERE co.transaccion_id = t.id AND co.tipo = 'recategorizar')
            """, (conexion_id,)).fetchall()
        cambios = []
        for tid, glosa, monto in filas:
            categoria, confianza = clasificar(glosa, monto)
            if categoria:
                cambios.append((self.categoria_id(categoria), confianza, tid))
        if cambios:
            with self.conn.cursor() as cur:
                cur.executemany(
                    "UPDATE transaccion SET categoria_id = %s, confianza_clasificacion = %s "
                    "WHERE id = %s", cambios)
        return len(cambios)

    # ───────────────────────── recurrencias ─────────────────────────
    # El detector vive en motor/recurrencias.py, que no sabe de base de datos.
    # Acá solo se le entregan los cargos y se persiste lo que devuelve.

    def cobros_del_usuario(self, usuario_id: str) -> list[tuple]:
        """
        Todos los cargos del usuario, para alimentar al detector.

        Se mira el historial completo y no solo lo recién traído: una serie de
        cobros se reconoce por su forma a lo largo del tiempo, así que una
        sincronización que trae un mes nuevo puede completar una periodicidad
        que antes no se veía.
        """
        return self.conn.execute(
            """
            SELECT t.id::text, t.fecha, -t.monto,
                   COALESCE(t.glosa_normalizada, t.glosa_original)
            FROM transaccion t
            JOIN cuenta c ON c.id = t.cuenta_id
            WHERE c.usuario_id = %s AND t.monto < 0 AND t.estado <> 'excluido'
            ORDER BY t.fecha
            """,
            (usuario_id,),
        ).fetchall()

    def guardar_suscripciones(self, usuario_id: str, recurrencias) -> int:
        """
        Persiste las recurrencias detectadas y enlaza sus movimientos.

        **Lo que el usuario ya decidió no se toca.** Una suscripción que él
        confirmó o descartó conserva su estado: el detector vuelve a correr en
        cada sincronización y, sin esta regla, cada corrida le borraría la
        decisión y volvería a preguntarle lo mismo. Solo se actualizan los
        datos observados (monto, periodicidad, próxima fecha).
        """
        vistas: list[str] = []
        for r in recurrencias:
            fila = self.conn.execute(
                """
                INSERT INTO suscripcion
                    (usuario_id, nombre, periodicidad, monto_esperado, proxima_fecha_estimada)
                VALUES (%(uid)s, %(nombre)s, %(per)s, %(monto)s, %(prox)s)
                ON CONFLICT (usuario_id, nombre) DO UPDATE
                   SET periodicidad           = EXCLUDED.periodicidad,
                       monto_esperado         = EXCLUDED.monto_esperado,
                       proxima_fecha_estimada = EXCLUDED.proxima_fecha_estimada
                RETURNING id
                """,
                {"uid": usuario_id, "nombre": r.nombre, "per": r.periodicidad,
                 "monto": r.monto_esperado, "prox": r.proxima_fecha_estimada},
            ).fetchone()
            suscripcion_id = fila[0]
            vistas.append(str(suscripcion_id))

            self.conn.execute(
                "UPDATE transaccion SET suscripcion_id = %s, es_recurrente = true "
                "WHERE id::text = ANY(%s)",
                (suscripcion_id, list(r.ids)),
            )

        # Lo que dejó de ser recurrente se desmarca, salvo que el usuario lo
        # haya confirmado a mano: su criterio manda sobre el del algoritmo.
        self.conn.execute(
            """
            UPDATE transaccion t
            SET es_recurrente = false, suscripcion_id = NULL
            FROM cuenta c
            WHERE t.cuenta_id = c.id AND c.usuario_id = %(uid)s
              AND t.suscripcion_id IS NOT NULL
              AND NOT (t.suscripcion_id::text = ANY(%(vistas)s))
              AND t.suscripcion_id NOT IN (
                    SELECT id FROM suscripcion
                    WHERE usuario_id = %(uid)s AND estado = 'confirmada')
            """,
            {"uid": usuario_id, "vistas": vistas},
        )
        return len(vistas)

    # ── Fuentes fuera del SFA: cartolas y carga manual (RF-09/12/13) ───────
    def insertar_sin_id(self, cuenta_id: str, fuente: str, filas: list[dict]) -> list[str]:
        """
        Inserta movimientos que no traen identificador de la institución
        (cartola o carga manual). La huella `hash_dedup` es la que evita
        duplicarlos: reimportar la misma cartola no inserta nada. Devuelve los
        ids insertados, en orden.

        `filas`: dicts con hash_dedup, payload_crudo_ref, monto, fecha,
        glosa_original y opcionalmente categoria_nombre y confianza_clasificacion.
        """
        ids = []
        for f in filas:
            fila = self.conn.execute(
                """INSERT INTO transaccion (cuenta_id, payload_crudo_ref, monto, moneda, fecha,
                                            glosa_original, categoria_id,
                                            confianza_clasificacion, hash_dedup, estado, fuente)
                   VALUES (%s, %s, %s, 'CLP', %s, %s, %s, %s, %s, 'confirmado', %s)
                   ON CONFLICT (hash_dedup) DO NOTHING
                   RETURNING id""",
                (cuenta_id, f.get("payload_crudo_ref"), f["monto"], f["fecha"],
                 f["glosa_original"], self.categoria_id(f.get("categoria_nombre")),
                 f.get("confianza_clasificacion"), f["hash_dedup"], fuente),
            ).fetchone()
            if fila:
                ids.append(str(fila[0]))
        return ids

    def registrar_origen(self, transaccion_id: str, fuente: str, payload_ref: str | None,
                         hash_fuente: str) -> None:
        """Otra fuente trajo un movimiento que ya estaba: se anota, no se duplica."""
        self.conn.execute(
            """INSERT INTO transaccion_origen (transaccion_id, fuente, payload_crudo_ref, hash_dedup)
               VALUES (%s, %s, %s, %s) ON CONFLICT (hash_dedup) DO NOTHING""",
            (transaccion_id, fuente, payload_ref, hash_fuente),
        )

    def hashes_conocidos(self, hashes: list[str]) -> set[str]:
        """De estas huellas, cuáles ya entraron (como movimiento o como origen adicional)."""
        if not hashes:
            return set()
        filas = self.conn.execute(
            """SELECT hash_dedup FROM transaccion WHERE hash_dedup = ANY(%s)
               UNION SELECT hash_dedup FROM transaccion_origen WHERE hash_dedup = ANY(%s)""",
            (hashes, hashes),
        ).fetchall()
        return {f[0] for f in filas}

    def candidatos_a_fusion(self, cuenta_id: str, fuente_entrante: str,
                            desde, hasta) -> list[tuple]:
        """
        Movimientos de la cuenta que podrían ser el mismo que uno que llega por
        `fuente_entrante`: los de OTRA fuente, en el rango de fechas, y que esa
        fuente todavía no haya reportado. (id, fecha, monto, glosa).
        """
        return self.conn.execute(
            """SELECT t.id::text, t.fecha, t.monto, COALESCE(t.glosa_original, '')
               FROM transaccion t
               WHERE t.cuenta_id = %(cuenta)s AND t.fuente <> %(fuente)s
                 AND t.fecha BETWEEN %(desde)s AND %(hasta)s
                 AND NOT EXISTS (SELECT 1 FROM transaccion_origen o
                                 WHERE o.transaccion_id = t.id AND o.fuente = %(fuente)s)""",
            {"cuenta": cuenta_id, "fuente": fuente_entrante, "desde": desde, "hasta": hasta},
        ).fetchall()

    def adoptar_desde_sfa(self, transaccion_id: str, d: dict, payload_ref: str) -> None:
        """
        La API del banco trajo un movimiento que ya había entrado por cartola.
        La API pasa a ser la fuente principal —trae el transactionID, que es
        lo que permite seguir la transición pendiente→confirmada— y la cartola
        queda como origen adicional, con su crudo. La categoría que tenía se
        conserva: puede haberla corregido la persona.
        """
        self.conn.execute(
            """INSERT INTO transaccion_origen (transaccion_id, fuente, payload_crudo_ref, hash_dedup)
               SELECT id, fuente, payload_crudo_ref, hash_dedup FROM transaccion WHERE id = %s
               ON CONFLICT (hash_dedup) DO NOTHING""",
            (transaccion_id,),
        )
        self.conn.execute(
            """UPDATE transaccion
               SET id_externo = %s, hash_dedup = %s, payload_crudo_ref = %s, monto = %s,
                   fecha = %s, glosa_original = %s, categoria_origen = %s, fuente = 'sfa'
               WHERE id = %s""",
            (d["id_externo"], d["hash_dedup"], payload_ref, d["monto"], d["fecha"],
             d["glosa_original"], d["categoria_origen"], transaccion_id),
        )

    def cuenta_del_usuario(self, usuario_id: str, cuenta_id: str) -> dict | None:
        fila = self.conn.execute(
            """SELECT c.id, c.conexion_id, c.id_externo, inst.nombre, inst.participante_sfa
               FROM cuenta c
               JOIN conexion cx      ON cx.id = c.conexion_id
               JOIN institucion inst ON inst.id = cx.institucion_id
               WHERE c.id::text = %s AND c.usuario_id = %s""",
            (cuenta_id, usuario_id),
        ).fetchone()
        if fila is None:
            return None
        return {"id": str(fila[0]), "conexion_id": str(fila[1]), "id_externo": fila[2],
                "institucion": fila[3], "participante_sfa": fila[4]}

    def institucion_por_nombre(self, nombre: str) -> tuple | None:
        """(id, nombre, participante_sfa) sin distinguir mayúsculas."""
        return self.conn.execute(
            "SELECT id, nombre, participante_sfa FROM institucion WHERE lower(nombre) = lower(%s)",
            (nombre,),
        ).fetchone()

    def cuenta_fuera_del_sfa(self, usuario_id: str, institucion: str, id_externo: str,
                             tipo_institucion: str, tipo_cuenta: str) -> dict:
        """
        Get-or-create de la cuenta de una institución que no está en el SFA (un
        banco del que solo hay cartolas, o el efectivo). Cuelga de una conexión
        como cualquier otra cuenta, así que los resúmenes, el borrado de la
        cuenta y la desvinculación la tratan igual.
        """
        inst = self.institucion_por_nombre(institucion)
        if inst is None:
            inst_id = self.conn.execute(
                """INSERT INTO institucion (nombre, tipo, participante_sfa)
                   VALUES (%s, %s, false) RETURNING id""",
                (institucion, tipo_institucion),
            ).fetchone()[0]
            nombre = institucion
        else:
            inst_id, nombre = inst[0], inst[1]
        conexion_id = asegurar_conexion(self.conn, usuario_id, inst_id)
        cuenta_id = self.upsert_cuenta(conexion_id, usuario_id, {
            "id_externo": id_externo, "tipo": tipo_cuenta, "moneda": "CLP", "saldo": None})
        return {"id": str(cuenta_id), "conexion_id": str(conexion_id),
                "id_externo": id_externo, "institucion": nombre, "participante_sfa": False}

    def marcar_sincronizacion(self, conexion_id: str):
        self.conn.execute(
            "UPDATE conexion SET ultima_sincronizacion = now() WHERE id = %s",
            (conexion_id,),
        )

    def commit(self):
        self.conn.commit()

    def close(self):
        # Lo que no se confirmó se descarta (no queda nada a medias) y la
        # conexión vuelve al pool. El cliente de Mongo es compartido: no se cierra.
        try:
            self.conn.rollback()
        finally:
            pool().putconn(self.conn)
