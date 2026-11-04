-- =============================================================================
-- Velvet Wallet — Esquema relacional (modelo canónico)  ·  PostgreSQL
-- -----------------------------------------------------------------------------
-- Proyecto APT: Velvet Wallet — App de finanzas personales consumidora del SFA
-- Asignatura : Capstone APT122 · Ingeniería en Informática · Duoc UC Pto. Montt
-- Integrantes: PADRON JOSSUE · TORRES PEDRO
-- Fase       : 1 (esquema preliminar) — corresponde al diagrama F1 de BD
-- Fecha      : 2026-09-15
--
-- Notas de diseño:
--  · Motor canónico en PostgreSQL. Los payloads crudos, logs y versiones de
--    modelos viven en MongoDB; aquí solo se referencian por ObjectId (texto).
--  · Se usan CHECK con conjuntos de valores en vez de tipos ENUM nativos,
--    porque ALTER de un CHECK es reversible sin recrear el tipo (RNF-37:
--    migraciones versionadas y reversibles).
--  · Los importes se guardan como NUMERIC. En CLP no hay decimales (RNF-29),
--    pero NUMERIC deja el esquema abierto a otras monedas sin cambios.
--  · Cifrado en reposo (RNF-16 / RF-31), en dos capas: el almacenamiento del
--    motor cifra el disco completo, y la aplicación cifra con AES-256-GCM las
--    columnas más sensibles antes de escribirlas (backend/ingesta/cifrado.py).
--    Esas columnas son texto con el formato enc:v1:... (ver COMMENT ON). La
--    clave vive fuera de la base, en VELVET_CLAVE_CIFRADO.
-- =============================================================================

BEGIN;

-- Extensiones -----------------------------------------------------------------
-- gen_random_uuid() es núcleo desde PostgreSQL 13. citext da un email
-- case-insensitive sin tener que normalizar a mano en cada consulta.
CREATE EXTENSION IF NOT EXISTS citext;

-- =============================================================================
-- 1. USUARIO
-- =============================================================================
CREATE TABLE usuario (
    id               uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    email            citext        NOT NULL UNIQUE,
    nombre           varchar(120)  NOT NULL,
    hash_password    varchar(255)  NOT NULL,
    sueldo_declarado text,
    created_at       timestamptz   NOT NULL DEFAULT now()
);

COMMENT ON TABLE  usuario                  IS 'Titular de la cuenta Velvet Wallet.';
COMMENT ON COLUMN usuario.hash_password    IS 'Hash de la contraseña (Argon2/bcrypt). Nunca la contraseña en claro.';
COMMENT ON COLUMN usuario.sueldo_declarado IS 'Sueldo configurado por el usuario (RF-36). Dato sensible: cifrado por la aplicación (RF-31), por eso es texto. La validación del monto la hace la API.';

-- =============================================================================
-- 2. INSTITUCION
-- =============================================================================
CREATE TABLE institucion (
    id               uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre           varchar(120)  NOT NULL,
    tipo             varchar(40)            CHECK (tipo IN ('banco','emisor_tarjeta','afp','fintech','otro')),
    participante_sfa boolean       NOT NULL DEFAULT false
);

COMMENT ON TABLE  institucion                  IS 'Institución financiera. participante_sfa distingue las que exponen APIs del estándar de las que solo entran por CSV.';
COMMENT ON COLUMN institucion.participante_sfa IS 'true = proveedor de información del SFA; false = ingesta por cartola/manual (RF-12).';

-- =============================================================================
-- 3. CATEGORIA  (jerárquica: subcategoría vía padre_id)
-- =============================================================================
CREATE TABLE categoria (
    id       uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    padre_id uuid         REFERENCES categoria(id) ON DELETE SET NULL,
    nombre   varchar(80)  NOT NULL,
    tipo     varchar(20)  NOT NULL CHECK (tipo IN ('gasto','ingreso'))
);

COMMENT ON TABLE  categoria          IS 'Catálogo de categorías de gasto/ingreso. padre_id modela subcategorías.';
COMMENT ON COLUMN categoria.padre_id IS 'Autoreferencia: categoría padre. NULL = categoría raíz.';

-- =============================================================================
-- 4. CONEXION  (usuario ↔ institución autorizada)
-- =============================================================================
CREATE TABLE conexion (
    id                    uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id            uuid         NOT NULL REFERENCES usuario(id)     ON DELETE CASCADE,
    institucion_id        uuid         NOT NULL REFERENCES institucion(id) ON DELETE RESTRICT,
    estado                varchar(20)  NOT NULL DEFAULT 'activa'
                                       CHECK (estado IN ('activa','expirada','revocada','error')),
    ultima_sincronizacion timestamptz
);

COMMENT ON TABLE  conexion                       IS 'Vínculo autorizado entre un usuario y una institución del SFA.';
COMMENT ON COLUMN conexion.estado                IS 'El consentimiento expirado/revocado es un estado del usuario, no un error técnico (RF-03).';
COMMENT ON COLUMN conexion.ultima_sincronizacion IS 'Base para advertir antigüedad del dato (RF-35 / RNF-09).';

-- =============================================================================
-- 5. CUENTA
-- =============================================================================
CREATE TABLE cuenta (
    id                 uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    conexion_id        uuid          NOT NULL REFERENCES conexion(id) ON DELETE CASCADE,
    usuario_id         uuid          NOT NULL REFERENCES usuario(id)  ON DELETE CASCADE,
    id_externo         varchar(64),
    tipo               varchar(40)            CHECK (tipo IN ('corriente','vista','ahorro','credito','tarjeta','otro')),
    numero_enmascarado varchar(40),
    moneda             varchar(3)    NOT NULL DEFAULT 'CLP',
    saldo              numeric(15,2),
    actualizado_at     timestamptz
);

COMMENT ON TABLE  cuenta                    IS 'Cuenta o producto financiero obtenido vía SFA o cartola (RF-05).';
COMMENT ON COLUMN cuenta.numero_enmascarado IS 'Solo dígitos finales enmascarados. No se almacena el número completo.';
COMMENT ON COLUMN cuenta.id_externo         IS 'accountId tal como lo entrega la institución. Único por conexión. NULL en carga manual.';

-- =============================================================================
-- 6. CONSENTIMIENTO  (alcance RAR por conexión)
-- =============================================================================
CREATE TABLE consentimiento (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    conexion_id      uuid         NOT NULL REFERENCES conexion(id) ON DELETE CASCADE,
    alcance_rar      jsonb        NOT NULL,
    fecha_inicio     timestamptz  NOT NULL DEFAULT now(),
    fecha_expiracion timestamptz,
    estado           varchar(20)  NOT NULL DEFAULT 'vigente'
                                  CHECK (estado IN ('vigente','expirado','revocado'))
);

COMMENT ON TABLE  consentimiento             IS 'Consentimiento granular otorgado por el usuario (RF-02 / RF-27).';
COMMENT ON COLUMN consentimiento.alcance_rar IS 'Detalle RAR: a qué cuentas y datos se accede y por cuánto tiempo (Rich Authorization Requests). refreshToken, rutCliente y nombreCliente van cifrados por la aplicación (RF-31).';

-- =============================================================================
-- 6b. CONSENTIMIENTO_TRATAMIENTO  (finalidades distintas del acceso bancario)
-- =============================================================================
-- Autorizar a Velvet a LEER los datos del banco no autoriza a USARLOS para
-- otra cosa. La Ley 21.719 exige consentimiento **específico por finalidad**:
-- entrenar un modelo con los gastos de alguien es un fin distinto de
-- mostrárselos, y necesita su propio permiso, otorgado por separado y
-- revocable por separado.
--
-- Por qué una tabla y no una columna booleana en `usuario`: un consentimiento
-- tiene fecha, vigencia y puede revocarse, y la ley obliga a poder **demostrar**
-- cuándo y a qué consintió la persona. Un booleano no guarda nada de eso.
--
-- Al revocar NO se borra la fila: se marca `revocado` con su fecha. El registro
-- de que hubo consentimiento, y de cuándo terminó, es parte de la bitácora de
-- tratamiento.
--
-- La ausencia de fila significa que NO hay consentimiento. Es opt-in por
-- construcción: nadie queda autorizado por omisión.
CREATE TABLE consentimiento_tratamiento (
    id               uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id       uuid         NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    finalidad        varchar(60)  NOT NULL
                                  CHECK (finalidad IN ('entrenamiento_modelos')),
    estado           varchar(20)  NOT NULL DEFAULT 'vigente'
                                  CHECK (estado IN ('vigente','expirado','revocado')),
    version_texto    varchar(20)  NOT NULL,
    fecha_inicio     timestamptz  NOT NULL DEFAULT now(),
    fecha_expiracion timestamptz  NOT NULL,
    revocado_at      timestamptz
);

COMMENT ON TABLE  consentimiento_tratamiento IS 'Consentimiento por finalidad de tratamiento, separado del acceso bancario (Ley 21.719).';
COMMENT ON COLUMN consentimiento_tratamiento.finalidad     IS 'Para qué se usan los datos. Cada finalidad se consiente aparte; no hay consentimiento general.';
COMMENT ON COLUMN consentimiento_tratamiento.version_texto IS 'Qué versión del texto aceptó la persona. Si el texto cambia, el consentimiento anterior no cubre la finalidad nueva y hay que volver a pedirlo.';
COMMENT ON COLUMN consentimiento_tratamiento.revocado_at   IS 'Cuándo se revocó. La fila no se borra: queda como registro de que hubo consentimiento y de cuándo terminó.';

-- Un solo consentimiento vigente por finalidad y persona. Los revocados y
-- expirados quedan como historia y no estorban.
CREATE UNIQUE INDEX uq_tratamiento_vigente
    ON consentimiento_tratamiento (usuario_id, finalidad)
    WHERE estado = 'vigente';

CREATE INDEX idx_tratamiento_usuario ON consentimiento_tratamiento (usuario_id);

-- =============================================================================
-- 7. SUSCRIPCION  (recurrencias detectadas)
-- =============================================================================
CREATE TABLE suscripcion (
    id                     uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id             uuid          NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    nombre                 varchar(120)  NOT NULL,
    periodicidad           varchar(20)            CHECK (periodicidad IN ('semanal','quincenal','mensual','bimestral','trimestral','anual','otra')),
    monto_esperado         numeric(15,2),
    proxima_fecha_estimada date,
    estado                 varchar(20)   NOT NULL DEFAULT 'detectada'
                                         CHECK (estado IN ('detectada','confirmada','descartada'))
);

COMMENT ON TABLE  suscripcion        IS 'Gasto recurrente detectado por el algoritmo (RF-20…RF-22).';
COMMENT ON COLUMN suscripcion.estado IS 'detectada hasta que el usuario la confirma o descarta (RF-22).';

-- Una suscripción por comercio y persona. El detector vuelve a correr en cada
-- sincronización: sin esta restricción, cada corrida crearía duplicados de la
-- misma suscripción y la decisión del usuario se perdería entre copias.
CREATE UNIQUE INDEX uq_suscripcion_usuario_nombre ON suscripcion (usuario_id, nombre);

-- =============================================================================
-- 8. META  (metas de ahorro)
-- =============================================================================
CREATE TABLE meta (
    id                    uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id            uuid          NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    nombre                varchar(120)  NOT NULL,
    monto_objetivo        numeric(15,2) NOT NULL CHECK (monto_objetivo > 0),
    monto_ahorrado        numeric(15,2) NOT NULL DEFAULT 0 CHECK (monto_ahorrado >= 0),
    fecha_objetivo        date,
    probabilidad_estimada numeric(5,4)           CHECK (probabilidad_estimada BETWEEN 0 AND 1),
    meses_estimados       smallint               CHECK (meses_estimados > 0),
    proyectada_en         timestamptz,
    creada_en             timestamptz   NOT NULL DEFAULT now()
);

COMMENT ON TABLE  meta                       IS 'Meta de ahorro del usuario (RF-26).';
COMMENT ON COLUMN meta.monto_ahorrado        IS 'Lo que la persona lleva reunido. Punto de partida de la proyección.';
COMMENT ON COLUMN meta.fecha_objetivo        IS 'Plazo que se propuso la persona, si se propuso alguno. La proyección responde con qué probabilidad llega a esa fecha.';
COMMENT ON COLUMN meta.probabilidad_estimada IS 'Probabilidad de cumplimiento que entrega la proyección Monte Carlo (RF-24). 0..1.';
COMMENT ON COLUMN meta.meses_estimados       IS 'Meses necesarios para alcanzarla con 80% de probabilidad. null si no se alcanza dentro del horizonte.';
COMMENT ON COLUMN meta.proyectada_en         IS 'Cuándo se calculó la proyección guardada. Cambia con cada mes nuevo de historial.';

-- =============================================================================
-- 9. TRANSACCION  (ledger canónico)
-- =============================================================================
CREATE TABLE transaccion (
    id                      uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    cuenta_id               uuid          NOT NULL REFERENCES cuenta(id)      ON DELETE CASCADE,
    categoria_id            uuid                   REFERENCES categoria(id)   ON DELETE SET NULL,
    suscripcion_id          uuid                   REFERENCES suscripcion(id) ON DELETE SET NULL,
    payload_crudo_ref       varchar(24),
    id_externo              varchar(64),
    monto                   numeric(15,2) NOT NULL CHECK (monto <> 0),
    moneda                  varchar(3)    NOT NULL DEFAULT 'CLP',
    fecha                   date          NOT NULL,
    glosa_original          varchar(255),
    glosa_normalizada       varchar(255),
    categoria_origen        varchar(80),
    estado                  varchar(20)   NOT NULL DEFAULT 'confirmado'
                                          CHECK (estado IN ('pendiente','confirmado','excluido')),
    hash_dedup              varchar(64)   NOT NULL UNIQUE,
    confianza_clasificacion numeric(5,4)           CHECK (confianza_clasificacion BETWEEN 0 AND 1),
    es_recurrente           boolean       NOT NULL DEFAULT false,
    created_at              timestamptz   NOT NULL DEFAULT now()
);

COMMENT ON TABLE  transaccion                         IS 'Movimiento normalizado al modelo canónico (RF-08).';
COMMENT ON COLUMN transaccion.categoria_id            IS 'NULL permitido: el clasificador se abstiene cuando la confianza es baja (RF-17 / RNF-33).';
COMMENT ON COLUMN transaccion.payload_crudo_ref       IS 'ObjectId del documento en MongoDB (PAYLOAD_CRUDO) del que se originó (RF-06 / RNF-32).';
COMMENT ON COLUMN transaccion.hash_dedup              IS 'Clave de deduplicación entre fuentes: un movimiento canónico por hash (RF-09).';
COMMENT ON COLUMN transaccion.confianza_clasificacion IS 'Confianza [0..1] del clasificador para categoria_id.';
COMMENT ON COLUMN transaccion.glosa_normalizada       IS 'Glosa limpia (p. ej. "UBER *EATS 8829" → "Uber Eats") (RF-10).';
COMMENT ON COLUMN transaccion.categoria_origen        IS 'Categoría tal como la manda la institución (merchantDetails.category del estándar). Es OPCIONAL y cada proveedor usa su propia taxonomía, sin equivalencia común: por eso se guarda aparte de categoria_id en vez de mezclarse con ella. Entra como señal del clasificador, que además de clasificar debe normalizar taxonomías distintas entre instituciones.';
COMMENT ON COLUMN transaccion.id_externo              IS 'transactionID tal como lo entrega la institución. Clave de actualización (upsert) para fuentes SFA. NULL en carga manual.';
COMMENT ON COLUMN transaccion.monto                   IS 'Con signo: negativo = cargo, positivo = abono. No existe movimiento de monto cero. El dato original queda en payload_crudo (Mongo).';

-- =============================================================================
-- 10. CORRECCION  (capa de correcciones del usuario, no sobrescribe el origen)
-- =============================================================================
CREATE TABLE correccion (
    id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    transaccion_id uuid         NOT NULL REFERENCES transaccion(id) ON DELETE CASCADE,
    usuario_id     uuid         NOT NULL REFERENCES usuario(id)     ON DELETE CASCADE,
    tipo           varchar(30)  NOT NULL CHECK (tipo IN ('recategorizar','marcar_duplicado','excluir','dividir')),
    valor          jsonb,
    created_at     timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  correccion       IS 'Corrección del usuario como capa separada; el dato de origen no se modifica (RF-14 / RNF-31).';
COMMENT ON COLUMN correccion.valor IS 'Detalle de la corrección (nueva categoría, particiones al dividir, etc.).';

-- =============================================================================
-- 11. BITACORA_AUDITORIA  (registro inmutable de accesos a datos personales)
-- =============================================================================
CREATE TABLE bitacora_auditoria (
    id          uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    usuario_id  uuid         REFERENCES usuario(id) ON DELETE SET NULL,
    accion      varchar(60)  NOT NULL,
    recurso     varchar(120) NOT NULL,
    ip_origen   inet,
    ocurrido_at timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE  bitacora_auditoria            IS 'Registro de actividades de tratamiento (RNF-18 / RF-28). Solo INSERT; no se actualiza ni borra.';
COMMENT ON COLUMN bitacora_auditoria.usuario_id IS 'ON DELETE SET NULL: al suprimir la cuenta el registro se anonimiza pero sobrevive (RNF-22).';

-- =============================================================================
-- 11b. CREDITO  (operaciones de crédito traídas por el SFA)
-- =============================================================================
-- Cuelga de `conexion` igual que `cuenta`: un crédito pertenece a la relación
-- con una institución, no al usuario directamente. Si se desvincula el banco,
-- se van sus créditos con él.
--
-- Los campos son los que entrega el estándar (API de Operaciones de Crédito,
-- Anexo 3). **No hay CAE ni tabla de amortización**: el estándar no los expone
-- —`amortizationScheduleLink` es solo una URL al calendario del proveedor— y
-- calcularlos sería un motor propio, fuera del alcance comprometido. Guardar
-- columnas vacías esperando datos que la fuente no da sería diseñar contra una
-- API que no existe.
CREATE TABLE credito (
    id                   uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    conexion_id          uuid          NOT NULL REFERENCES conexion(id) ON DELETE CASCADE,
    usuario_id           uuid          NOT NULL REFERENCES usuario(id)  ON DELETE CASCADE,
    id_externo           varchar(64)   NOT NULL,
    producto             varchar(120)  NOT NULL,
    tipo                 varchar(40),
    moneda               varchar(3)    NOT NULL DEFAULT 'CLP',
    estado               varchar(20),
    monto_original       numeric(15,2),
    cuota_mensual        numeric(15,2),
    plazo_meses          smallint,
    cuotas_restantes     smallint,
    saldo_actual         numeric(15,2),
    tasa_interes         numeric(7,4),
    tipo_tasa            varchar(20),
    proposito            varchar(160),
    dia_de_pago          smallint,
    en_mora              boolean       NOT NULL DEFAULT false,
    calendario_url       varchar(300),
    actualizado_at       timestamptz
);

COMMENT ON TABLE  credito                IS 'Crédito del usuario obtenido vía la API de Operaciones de Crédito del SFA.';
COMMENT ON COLUMN credito.id_externo     IS 'loanID tal como lo entrega la institución. Único por conexión.';
COMMENT ON COLUMN credito.cuotas_restantes IS 'Lo entrega la institución. El estándar NO da las cuotas ya pagadas ni su desglose.';
COMMENT ON COLUMN credito.calendario_url IS 'amortizationScheduleLink: el estándar entrega solo el enlace, no la tabla.';

-- =============================================================================
-- 12. INCIDENTE_SEGURIDAD  (brechas de datos personales)
-- =============================================================================
-- La Ley 21.719 obliga a notificar las vulneraciones de seguridad que afecten
-- datos personales: a la autoridad y, cuando hay riesgo para los titulares,
-- también a cada uno de ellos. El plazo corre desde que se TOMA CONOCIMIENTO,
-- no desde que ocurre el hecho, por eso se guardan las dos fechas por separado.
--
-- Guardar el incidente en la base y no en un documento aparte es lo que
-- permite demostrar el cumplimiento: cuándo se supo, a quién se avisó y
-- cuándo. Un procedimiento escrito que no deja rastro no prueba nada.
CREATE TABLE incidente_seguridad (
    id                 uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    ocurrido_at        timestamptz,
    detectado_at       timestamptz  NOT NULL DEFAULT now(),
    titulo             varchar(160) NOT NULL,
    descripcion        text         NOT NULL,
    datos_afectados    varchar(300) NOT NULL,
    medidas            text,
    gravedad           varchar(20)  NOT NULL DEFAULT 'media'
                                    CHECK (gravedad IN ('baja','media','alta')),
    estado             varchar(20)  NOT NULL DEFAULT 'detectado'
                                    CHECK (estado IN ('detectado','notificado','cerrado')),
    notificado_at      timestamptz,
    autoridad_avisada_at timestamptz
);

COMMENT ON TABLE  incidente_seguridad                   IS 'Brecha de seguridad de datos personales (Ley 21.719). El plazo de 72 horas corre desde detectado_at.';
COMMENT ON COLUMN incidente_seguridad.ocurrido_at       IS 'Cuándo pasó, si se sabe. Puede ser anterior a cuándo se detectó.';
COMMENT ON COLUMN incidente_seguridad.detectado_at      IS 'Cuándo se tomó conocimiento. Es la fecha que inicia el plazo legal.';
COMMENT ON COLUMN incidente_seguridad.datos_afectados   IS 'Qué categorías de datos se vieron comprometidas, en lenguaje para el titular.';
COMMENT ON COLUMN incidente_seguridad.autoridad_avisada_at IS 'Cuándo se notificó a la autoridad de protección de datos.';

-- Quiénes quedaron afectados y si ya lo vieron. Es una tabla aparte y no una
-- marca global porque una brecha rara vez afecta a todos: hay que poder
-- demostrar a QUIÉN se le avisó, uno por uno.
CREATE TABLE incidente_afectado (
    incidente_id uuid        NOT NULL REFERENCES incidente_seguridad(id) ON DELETE CASCADE,
    usuario_id   uuid        NOT NULL REFERENCES usuario(id) ON DELETE CASCADE,
    avisado_at   timestamptz NOT NULL DEFAULT now(),
    visto_at     timestamptz,
    PRIMARY KEY (incidente_id, usuario_id)
);

COMMENT ON TABLE  incidente_afectado          IS 'Titulares afectados por una brecha y constancia de que se les avisó (RF-29).';
COMMENT ON COLUMN incidente_afectado.visto_at IS 'Cuándo el titular leyó el aviso dentro de la aplicación.';

-- =============================================================================
-- Índices  (además de los UNIQUE/PK ya creados)
-- =============================================================================
CREATE INDEX idx_incidente_afectado_usuario ON incidente_afectado (usuario_id);
CREATE INDEX idx_credito_usuario ON credito (usuario_id);
-- loanID único por conexión: la sincronización hace upsert y no duplica.
CREATE UNIQUE INDEX uq_credito_conexion_externo ON credito (conexion_id, id_externo);
CREATE INDEX idx_conexion_usuario        ON conexion (usuario_id);
CREATE INDEX idx_conexion_institucion    ON conexion (institucion_id);
CREATE INDEX idx_cuenta_conexion         ON cuenta (conexion_id);
CREATE INDEX idx_cuenta_usuario          ON cuenta (usuario_id);
-- accountId único por conexión (upsert en cada sincronización, no crea cuentas duplicadas).
CREATE UNIQUE INDEX uq_cuenta_conexion_externo ON cuenta (conexion_id, id_externo) WHERE id_externo IS NOT NULL;
CREATE INDEX idx_consentimiento_conexion ON consentimiento (conexion_id);
CREATE INDEX idx_suscripcion_usuario     ON suscripcion (usuario_id);
CREATE INDEX idx_meta_usuario            ON meta (usuario_id);
CREATE INDEX idx_categoria_padre         ON categoria (padre_id);

-- Transacción: los filtros más frecuentes son por cuenta y por rango de fecha.
CREATE INDEX idx_transaccion_cuenta      ON transaccion (cuenta_id);
CREATE INDEX idx_transaccion_categoria   ON transaccion (categoria_id);
CREATE INDEX idx_transaccion_suscripcion ON transaccion (suscripcion_id);
CREATE INDEX idx_transaccion_fecha       ON transaccion (fecha);
CREATE INDEX idx_transaccion_cuenta_fecha ON transaccion (cuenta_id, fecha DESC);
-- transactionID único por cuenta: soporta el upsert pendiente→confirmada (mismo ID, otro monto).
CREATE UNIQUE INDEX uq_transaccion_cuenta_externo ON transaccion (cuenta_id, id_externo) WHERE id_externo IS NOT NULL;
-- Bandeja "Por revisar": movimientos sin categoría (RF-18).
CREATE INDEX idx_transaccion_sin_categoria ON transaccion (cuenta_id) WHERE categoria_id IS NULL;

CREATE INDEX idx_correccion_transaccion  ON correccion (transaccion_id);
CREATE INDEX idx_correccion_usuario      ON correccion (usuario_id);
CREATE INDEX idx_bitacora_usuario        ON bitacora_auditoria (usuario_id);
CREATE INDEX idx_bitacora_ocurrido       ON bitacora_auditoria (ocurrido_at DESC);

COMMIT;

-- =============================================================================
-- Fin del esquema.
-- Fuera de alcance en Fase 1 (según el diagrama entregado): no hay tabla
-- CREDITO independiente. Los productos de crédito se ingieren como CUENTA
-- (tipo='credito'); la cuota mensual entra al excedente vía RF-23. Si en Fase 2
-- se decide persistir plazo/tasa/saldo del crédito, se agrega en una migración.
-- =============================================================================