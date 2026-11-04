// ============================================================================
// Velvet Wallet — Inicialización de MongoDB (documental)
// ----------------------------------------------------------------------------
// Se ejecuta UNA sola vez, cuando el volumen de datos está vacío.
// Crea las tres colecciones del diagrama de Fase 1 con validadores $jsonSchema.
//
// Nota de diseño: en PAYLOAD_CRUDO el campo `payload` NO se restringe: su razón
// de ser es guardar el JSON tal como lo entregó la institución, sea cual sea su
// forma (RF-06 / RNF-32). Solo se valida el "sobre" (de dónde vino y cuándo).
// La aplicación guarda ese JSON cifrado con AES-256-GCM (RF-31) como
// { cifrado: "enc:v1:..." }: se recupera idéntico y cualquier alteración se
// detecta al descifrar. El sobre queda en claro para buscar y borrar.
// ============================================================================

// El init corre ya posicionado en la base MONGO_INITDB_DATABASE.
db = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE || "velvet_wallet");

// ---------------------------------------------------------------------------
// PAYLOAD_CRUDO — respuesta cruda de la API/cartola, sin modificar (RF-06)
// ---------------------------------------------------------------------------
db.createCollection("payload_crudo", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["conexion_id", "endpoint_origen", "payload", "recibido_at"],
      properties: {
        conexion_id:     { bsonType: "string",  description: "UUID de la conexión en Postgres (referencia lógica)" },
        endpoint_origen: { bsonType: "string",  description: "Endpoint o fuente de la que provino (p. ej. /accounts, cartola-csv)" },
        payload:         { bsonType: "object",  description: "Cuerpo crudo tal como llegó. Esquema libre a propósito." },
        procesado:       { bsonType: "bool",    description: "true una vez normalizado al modelo canónico" },
        recibido_at:     { bsonType: "date",    description: "Marca de tiempo de recepción" }
      }
    }
  },
  validationLevel: "moderate",
  validationAction: "error"
});
db.payload_crudo.createIndex({ conexion_id: 1 });
db.payload_crudo.createIndex({ procesado: 1 });          // buscar lo aún no normalizado
db.payload_crudo.createIndex({ recibido_at: -1 });

// ---------------------------------------------------------------------------
// LOG — registro técnico de la aplicación
// ---------------------------------------------------------------------------
db.createCollection("log", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["nivel", "mensaje", "ocurrido_at"],
      properties: {
        nivel:       { enum: ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], description: "Nivel del log" },
        mensaje:     { bsonType: "string" },
        contexto:    { bsonType: "object", description: "Datos adicionales del evento" },
        ocurrido_at: { bsonType: "date" }
      }
    }
  },
  validationLevel: "moderate",
  validationAction: "error"
});
db.log.createIndex({ ocurrido_at: -1 });
db.log.createIndex({ nivel: 1 });

// ---------------------------------------------------------------------------
// VERSION_MODELO — cada versión del clasificador con sus métricas (RNF-38)
// ---------------------------------------------------------------------------
db.createCollection("version_modelo", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["version", "fecha_entrenamiento"],
      properties: {
        version:             { bsonType: "string", description: "Identificador de versión del modelo" },
        metricas:            { bsonType: "object", description: "Precisión, recall, etc. para comparar y revertir" },
        ruta_artefacto:      { bsonType: "string", description: "Ruta al artefacto serializado del modelo" },
        fecha_entrenamiento: { bsonType: "date" }
      }
    }
  },
  validationLevel: "moderate",
  validationAction: "error"
});
db.version_modelo.createIndex({ version: 1 }, { unique: true });
db.version_modelo.createIndex({ fecha_entrenamiento: -1 });

print("Velvet Wallet: colecciones creadas -> " +
      db.getCollectionNames().join(", "));
