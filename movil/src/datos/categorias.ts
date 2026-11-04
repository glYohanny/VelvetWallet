/**
 * Las categorías de gasto de Velvet Wallet.
 *
 * Es la misma lista que backend/clasificador/taxonomia.py (CATEGORIAS): el
 * backend rechaza una categoría que no esté ahí. Si se agrega una, se agrega
 * en los dos lados.
 */
export const CATEGORIAS_DE_GASTO = [
  "Supermercado",
  "Delivery",
  "Restaurantes",
  "Transporte",
  "Servicios",
  "Entretención",
  "Suscripciones",
  "Salud",
  "Gimnasio",
  "Vivienda",
  "Vestuario",
  "Educación",
  "Hogar",
] as const;
