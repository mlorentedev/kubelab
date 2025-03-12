// src/domain/business.ts
import { SubscriptionTag } from './models';

/**
 * Reglas de negocio puras relacionadas con suscripciones
 */

/**
 * Determina si un email tiene formato válido (regla de negocio básica)
 */
export function isValidEmailFormat(email: string): boolean {
  return /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(email);
}

/**
 * Determina qué tags aplicar a un nuevo suscriptor
 */
export function getTagsForNewSubscriber(customTags: string[] = []): string[] {
  // Un nuevo suscriptor siempre debe tener el tag NewSubscriber
  return [SubscriptionTag.NewSubscriber, ...customTags];
}

/**
 * Genera el título para un recurso basado en su ID
 */
export function generateResourceTitle(resourceId: string, customTitle?: string): string {
  if (customTitle && customTitle.trim().length > 0) {
    return customTitle;
  }
  return `Recurso ${resourceId}`;
}

/**
 * Genera la URL de un recurso basado en su fileId
 */
export function generateResourceUrl(fileId: string): string {
  return `https://drive.google.com/file/d/${fileId}/view?usp=drive_link`;
}

/**
 * Calcula un retraso para envío de emails (en milisegundos)
 */
export function getEmailDelay(minutes: number = 1): number {
  return minutes * 60 * 1000;
}
