// src/services/subscription.service.ts
import { checkSubscriber, subscribeUser, addTagToSubscriber } from './beehiiv.service';
import { logFunction } from '../utils/logging';
import { SERVER_MESSAGES, FRONTEND_MESSAGES } from '../config/constants';
import { type SubscriptionResult, SubscriptionSource, SubscriptionTag } from '../domain/models';

/**
 * Procesa una suscripción completa (verificación, creación, etiquetado)
 * Orquesta el flujo completo de suscripción usando el servicio de BeeHiiv
 */
export async function processSubscription(
  email: string,
  tags: string[] = [],
  utmSource: SubscriptionSource = SubscriptionSource.LandingPage
): Promise<SubscriptionResult> {
  try {
    logFunction('info', SERVER_MESSAGES.INFO.REQUEST_PROCESSING, {
      action: 'process_subscription',
      email,
      utmSource,
    });

    // Verificar si el suscriptor ya existe
    const subscriberCheck = await checkSubscriber(email);

    if (subscriberCheck.success && subscriberCheck.subscriber) {
      // Actualizar tags para un suscriptor existente
      const tagResults = await Promise.all(
        tags.map((tag) => addTagToSubscriber(subscriberCheck.subscriber!.id, tag))
      );

      if (tagResults.some((result) => !result)) {
        return {
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.TAGS_UPDATE_ERROR,
        };
      }

      return {
        success: true,
        message: FRONTEND_MESSAGES.SUCCESS.SUBSCRIPTION_UPDATED,
        subscriberId: subscriberCheck.subscriber.id,
        alreadySubscribed: true,
      };
    }

    // Crear un nuevo suscriptor
    const newSubscription = await subscribeUser(email, utmSource);

    if (newSubscription.success && newSubscription.subscriber) {
      // Añadir etiquetas al nuevo suscriptor
      const allTags = [SubscriptionTag.NewSubscriber, ...tags];

      const tagResults = await Promise.all(
        allTags.map((tag) => addTagToSubscriber(newSubscription.subscriber!.id, tag))
      );

      if (tagResults.some((result) => !result)) {
        return {
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.TAGS_UPDATE_ERROR,
        };
      }

      return {
        success: true,
        message: FRONTEND_MESSAGES.SUCCESS.SUBSCRIPTION_NEW,
        subscriberId: newSubscription.subscriber.id,
      };
    }

    return {
      success: false,
      message: FRONTEND_MESSAGES.ERRORS.SUBSCRIPTION_ERROR,
    };
  } catch (error) {
    logFunction('error', SERVER_MESSAGES.ERRORS.SUBSCRIPTION_ERROR, error);
    return {
      success: false,
      message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
    };
  }
}
