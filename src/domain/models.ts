// src/domain/models.ts

/**
 * Fuentes de suscripción
 */
export enum SubscriptionSource {
  LandingPage = 'landing_page',
  LeadMagnet = 'lead_magnet',
  Newsletter = 'newsletter',
}

/**
 * Tags de suscripción
 */
export enum SubscriptionTag {
  NewSubscriber = 'new',
  ExistingSubscriber = 'existing',
}

/**
 * Interfaces para suscriptores
 */
export interface Subscriber {
  id: string;
  email: string;
  tags: string[];
}

/**
 * Resultado de operaciones de suscripción
 */
export interface SubscriptionResult {
  success: boolean;
  message: string;
  subscriberId?: string;
  alreadySubscribed?: boolean;
}

/**
 * Opciones para envío de email con recurso
 */
export interface ResourceEmailOptions {
  email: string;
  resourceId: string;
  resourceTitle: string;
  resourceLink: string;
}
