// src/config/constants.ts

/**
 * URLs y endpoints
 */
export const URLS = {
  SUCCESS_PAGES: {
    SUBSCRIPTION: '/subscription-success',
    RESOURCE: '/resource-success',
    UNSUBSCRIBE: '/unsubscribe-success',
    BOOKING: '/booking-success',
  },
  ERROR_PAGES: {
    NOT_FOUND: '/404',
  },
  API: {
    SUBSCRIBE: '/api/subscribe',
    UNSUBSCRIBE: '/api/unsubscribe',
    LEAD_MAGNET: '/api/lead-magnet',
    RESOURCE_EMAIL: '/api/resource-email',
  },
};

/**
 * Mensajes de respuesta para el frontend (en español)
 */
export const FRONTEND_MESSAGES = {
  ERRORS: {
    INVALID_EMAIL: 'Correo electrónico inválido.',
    INCOMPLETE_DATA: 'Datos incompletos para completar la operación.',
    SERVER_ERROR: 'Error interno del servidor.',
    EMAIL_NOT_SUBSCRIBED: 'Este email no está suscrito.',
    EMAIL_CONFIG_ERROR: 'Error en la configuración de email.',
    TAGS_UPDATE_ERROR: 'Error al actualizar los tags del suscriptor.',
    SUBSCRIPTION_ERROR: 'No se pudo completar la suscripción.',
  },
  SUCCESS: {
    SUBSCRIPTION_NEW: 'Nuevo suscriptor añadido.',
    SUBSCRIPTION_UPDATED: 'Suscriptor existente actualizado.',
    UNSUBSCRIPTION: 'Se ha cancelado tu suscripción correctamente.',
    RESOURCE_SENT: 'Recurso enviado correctamente.',
    EMAIL_SENT: 'Email enviado correctamente.',
  },
};

/**
 * Mensajes de log internos (en inglés)
 */
export const SERVER_MESSAGES = {
  ERRORS: {
    INVALID_EMAIL: 'Invalid email format',
    INCOMPLETE_DATA: 'Incomplete data for operation',
    SERVER_ERROR: 'Internal server error',
    EMAIL_NOT_SUBSCRIBED: 'Email not subscribed',
    EMAIL_CONFIG_ERROR: 'Email configuration error',
    API_ERROR: 'API error',
    SUBSCRIPTION_ERROR: 'Subscription error',
  },
  INFO: {
    SUBSCRIBER_EXISTS: 'Subscriber already exists',
    SUBSCRIBER_NOT_FOUND: 'Subscriber not found',
    NEW_SUBSCRIBER: 'New subscriber created',
    TAG_ADDED: 'Tag added to subscriber',
    USER_UNSUBSCRIBED: 'User unsubscribed successfully',
    EMAIL_SENT: 'Email sent successfully',
    REQUEST_PROCESSING: 'Processing request',
  },
  WARN: {
    EMPTY_TAG: 'Empty tag not added',
    EMAIL_DELIVERY_ISSUE: 'Email delivery issue',
  },
};

/**
 * Configuración de tiempos
 */
export const TIMING = {
  EMAIL_DELAY_MS: 60 * 1000, // 1 minuto
};
