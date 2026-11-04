/**
 * Modelo de datos que consume la aplicación.
 *
 * ESTE ARCHIVO ES EL CONTRATO CON EL BACKEND. Lo que está definido acá es lo
 * que la API debe devolver; la app no sabe ni le importa de dónde salió
 * (SFA, cartola, carga manual). Cualquier cambio se acuerda entre ambos.
 *
 * Fechas: siempre texto ISO 8601 con zona horaria ("2026-09-21T14:32:00-03:00").
 * Montos: enteros en pesos chilenos, con signo (negativo = cargo).
 */

// ─────────────────────────── Usuario y sesión ───────────────────────────

/**
 * El usuario tal como lo ve la app. NO incluye la contraseña ni su hash:
 * el backend nunca los devuelve.
 */
export type Usuario = {
  id: string;
  nombre: string;
  email: string;
  /** Sueldo configurado por el usuario (RF-36). null hasta que lo defina. */
  sueldoDeclarado: number | null;
  creadoEn: string;
};

/**
 * Lo que devuelven POST /api/auth/registro y POST /api/auth/sesion.
 *
 * El token viaja después en cada petición como `Authorization: Bearer <token>`.
 * La app lo guarda en el almacenamiento seguro del sistema; la contraseña no
 * se guarda nunca.
 */
export type SesionIniciada = {
  token: string;
  /** Cuándo expira el token, para saber si hay que renovarlo. */
  expiraEn: string;
  usuario: Usuario;
};

/** Credenciales de inicio de sesión. */
export type Credenciales = {
  email: string;
  password: string;
};

/** Datos de registro. */
export type DatosRegistro = Credenciales & {
  nombre: string;
};

/** Estado de la conexión con una institución. Es un estado del usuario, no un error técnico. */
export type EstadoConexion =
  | "al_dia"                // la última sincronización funcionó
  | "sin_respuesta"         // la institución no respondió; el dato es de la última vez
  | "autorizacion_vencida"; // el consentimiento expiró; el usuario debe reautorizar

export type Conexion = {
  id: string;
  institucion: string;
  /**
   * Cómo llegan sus datos: por la API del SFA, por cartolas que importa la
   * persona, o anotados a mano (efectivo). Solo las del SFA tienen un permiso
   * que vence y que hay que reautorizar.
   */
  fuente?: OrigenMovimiento;
  /** Fecha del movimiento más reciente. En una cartola, hasta dónde llega el dato. */
  datosHasta?: string | null;
  estado: EstadoConexion;
  /** Última vez que se obtuvieron datos con éxito. null si nunca se sincronizó. */
  ultimaSincronizacion: string | null;
  /** Solo cuando estado = "autorizacion_vencida", y solo si se sabe la fecha. */
  autorizacionVencioEl?: string | null;
  /**
   * El dato ya no es confiable: nunca se sincronizó, o lo que hay es más viejo
   * que la ventana de frescura. Se advierte en vez de mostrar un total que
   * parece completo cuando no lo está (RF-35).
   */
  datoAntiguo: boolean;
  cuentas: CuentaConectada[];
};

export type CuentaConectada = {
  /** Id interno de Velvet. */
  id: string;
  /**
   * Id que le da la institución. Es el que viaja en `Movimiento.cuentaId`, así
   * que es el que hay que usar para cruzar un movimiento con su cuenta.
   */
  idExterno: string | null;
  /** Tipo ya legible: "Cuenta Corriente", "Cuenta Vista"… */
  tipo: string;
  /**
   * Últimos dígitos, como los entrega la institución. El número completo no se
   * guarda. null si el banco no lo informó.
   */
  numeroEnmascarado: string | null;
  /** null si la institución no entregó saldo para esa cuenta. */
  saldo: number | null;
  moneda: string;
};

/** Por qué camino entró el movimiento al sistema. */
export type OrigenMovimiento = "sfa" | "cartola" | "manual";

/** Cómo quedó la categoría: la puso el clasificador, la corrigió el usuario, o no hay. */
export type EstadoCategoria = "automatica" | "corregida" | "sin_categoria";

/**
 * Quién decidió la categoría. Es trazabilidad de la decisión, no una métrica:
 * permite responder "¿por qué esto quedó en Supermercado?".
 *
 *   regla    → una regla reconoció el comercio. Sin modelo, alta precisión.
 *   modelo   → lo clasificó el modelo entrenado, con su confianza.
 *   banco    → la institución ya lo mandó categorizado.
 *   usuario  → lo corrigió la persona.
 */
export type OrigenClasificacion = "regla" | "modelo" | "banco" | "usuario";

/** Corrección hecha por el usuario. Se guarda aparte; el dato original no se modifica. */
export type Correccion = {
  tipo: "recategorizar" | "marcar_duplicado" | "excluir" | "dividir";
  fecha: string;
  detalle?: string;
  /** Esta fila deshace la anterior del mismo tipo. La historia no se borra. */
  deshecha?: boolean;
};

/** Una parte de un gasto repartido entre categorías. Las partes suman el monto. */
export type Parte = {
  /** Con signo, como el movimiento. */
  monto: number;
  categoria: string;
};

/**
 * Un movimiento ya normalizado al modelo canónico.
 *
 * Se guardan por separado lo que dijo el banco (glosaOriginal, categoriaBanco)
 * y lo que el sistema entendió (comercio, categoria). El dato original nunca
 * se pierde; las correcciones se aplican encima.
 */
export type Movimiento = {
  id: string;
  /** El id que le da la INSTITUCIÓN a la cuenta: calza con `CuentaConectada.idExterno`. */
  cuentaId: string;
  institucion: string;
  fecha: string;
  /** Con signo: negativo = cargo, positivo = abono. */
  monto: number;
  moneda: "CLP";
  /** Nombre normalizado ("Uber Eats"). null si no se pudo identificar. */
  comercio: string | null;
  /** Tal como la mandó la institución ("UBER *EATS 8829 SANTIAGO"). */
  glosaOriginal: string;
  /** Categoría de Velvet Wallet. null = sin categorizar; se muestra en Por revisar. */
  categoria: string | null;
  /** Categoría que mandó la institución, si la mandó. Sin taxonomía común entre bancos. */
  categoriaBanco: string | null;
  estadoCategoria: EstadoCategoria;
  /** Quién decidió la categoría. null mientras no haya clasificador. */
  origenClasificacion: OrigenClasificacion | null;
  /**
   * Qué tan seguro estaba el modelo, entre 0 y 1. Solo cuando
   * `origenClasificacion` es "modelo"; las reglas y el usuario no tienen
   * confianza parcial. Bajo el umbral, el sistema se abstiene y no clasifica.
   */
  confianza: number | null;
  /** Detectado como cargo recurrente (suscripción, arriendo, cuenta del hogar). */
  esRecurrente: boolean;
  /** No es gasto: transferencia entre cuentas propias, por ejemplo. */
  excluido: boolean;
  /** Por qué no cuenta: lo dijo la persona, o es duplicado de otro. null si cuenta. */
  motivoExclusion?: "no_es_gasto" | "duplicado" | null;
  /** Si es duplicado: el id del movimiento que sí cuenta. */
  duplicadoDe?: string | null;
  /**
   * Si la persona lo repartió entre categorías. El total sigue siendo `monto`;
   * cambia en qué categorías cuenta. null si no está dividido.
   */
  partes?: Parte[] | null;
  /** Por dónde entró primero. */
  origen: OrigenMovimiento;
  /**
   * Todas las fuentes que lo trajeron, empezando por `origen`. Un movimiento
   * que llegó por la API y por una cartola es UNO solo, con las dos (RF-09).
   */
  fuentes?: OrigenMovimiento[];

  // ── Trazabilidad (Ley 21.719: registro de tratamiento) ──
  /** Cuándo lo recibió Velvet Wallet. Distinto de `fecha`, que es la del banco. */
  recibidoEn: string;
  /** Referencia al documento crudo en MongoDB tal como llegó (también lo anotado a mano). */
  payloadCrudoRef: string | null;
  /** Correcciones del usuario, en orden. Vacío si no hay. */
  correcciones: Correccion[];
};

// ───────────────────────── Metas de ahorro ─────────────────────────

/**
 * En qué quedó la proyección. Hay que mirarlo antes que los meses: salvo en
 * "proyectada", los plazos vienen en null y la app tiene que decir otra cosa.
 *
 *   cumplida      → el ahorro ya llegó al objetivo.
 *   sin_historial → faltan meses observados; el motor se abstiene de proyectar.
 *   improbable    → se simuló y ni la mitad de los futuros llega a tiempo.
 *   proyectada    → hay respuesta con probabilidad.
 */
export type EstadoProyeccion = "cumplida" | "sin_historial" | "improbable" | "proyectada";

/**
 * Resultado de la simulación de Monte Carlo (RF-24).
 *
 * No es "te faltan N meses" sino "en N meses con tanta probabilidad". El
 * excedente mensual no es constante, y una sola cifra lo escondería.
 */
export type Proyeccion = {
  estado: EstadoProyeccion;
  /** Meses completos de historial que alimentaron la simulación. */
  mesesObservados: number;
  /** Cuántos hacen falta como mínimo para que el motor proyecte. */
  mesesMinimos: number;
  excedenteMediano: number;
  excedentePeor: number;
  excedenteMejor: number;
  /** curva[i] = probabilidad de haberla alcanzado en el mes i+1. No decrece. */
  curva: number[];
  /** Meses para alcanzarla con esa probabilidad. null = no se alcanza en el horizonte. */
  mesesP50: number | null;
  mesesP80: number | null;
  mesesP95: number | null;
  /** Probabilidad de llegar al plazo que se propuso la persona. null si no se propuso ninguno. */
  probabilidadALaFecha: number | null;
  simulaciones: number;
  horizonteMeses: number;
};

export type Meta = {
  id: string;
  nombre: string;
  montoObjetivo: number;
  montoAhorrado: number;
  /** Plazo que se propuso la persona. null si no se propuso ninguno. */
  fechaObjetivo: string | null;
  creadaEn: string;
  /** Fracción reunida, entre 0 y 1. */
  avance: number;
  proyeccion: Proyeccion;
};
