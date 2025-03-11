// src/services/beehiiv.service.ts
import { ENV } from '../config/env';
import { logFunction } from '../utils/logging';
import { SERVER_MESSAGES, FRONTEND_MESSAGES } from '../config/constants';
import type { Subscriber, SubscriptionResult } from '../domain/models';

const BEEHIIV_API_SUBSCRIPTIONS = `https://api.beehiiv.com/v2/publications/${ENV.BEEHIIV.PUB_ID}/subscriptions`;

/**
 * Verifica si un suscriptor existe por email
 */
export async function checkSubscriber(
  email: string
): Promise<{ success: boolean; subscriber?: Subscriber }> {
  try {
    const response = await fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/by_email/${email}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ENV.BEEHIIV.API_KEY}`,
      },
    });

    const result = await response.json();
    const subscriber = result.data;

    if (!subscriber || !subscriber.id) {
      logFunction('warn', SERVER_MESSAGES.INFO.SUBSCRIBER_NOT_FOUND, email);
      return { success: false };
    }

    logFunction('info', SERVER_MESSAGES.INFO.SUBSCRIBER_EXISTS, email);
    return {
      success: true,
      subscriber: subscriber,
    };
  } catch (e) {
    logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} checking subscriber:`, e);
    return { success: false };
  }
}

/**
 * Crea un nuevo suscriptor
 */
export async function subscribeUser(
  email: string,
  utm_source = 'landing_page'
): Promise<{ success: boolean; subscriber?: Subscriber }> {
  try {
    logFunction('info', `Subscribing user with utm_source: ${utm_source}`, email);

    const response = await fetch(BEEHIIV_API_SUBSCRIPTIONS, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ENV.BEEHIIV.API_KEY}`,
      },
      body: JSON.stringify({
        email: email,
        utm_source: utm_source,
        reactivate_existing: true,
        send_welcome_email: true,
      }),
    });

    const result = await response.json();
    const subscriber = result.data;

    if (subscriber && subscriber.id) {
      logFunction('info', SERVER_MESSAGES.INFO.NEW_SUBSCRIBER, email);
      return {
        success: true,
        subscriber: subscriber,
      };
    } else {
      logFunction('error', 'Error subscribing user, API response:', result);
      return { success: false };
    }
  } catch (e) {
    logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} subscribing user:`, e);
    return { success: false };
  }
}

/**
 * Añade una etiqueta a un suscriptor existente
 */
export async function addTagToSubscriber(subscription_id: string, tag: string): Promise<boolean> {
  try {
    if (tag === '') {
      logFunction('warn', SERVER_MESSAGES.WARN.EMPTY_TAG, subscription_id);
      return false;
    }

    const response = await fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/${subscription_id}/tags`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ENV.BEEHIIV.API_KEY}`,
      },
      body: JSON.stringify({
        tags: [tag],
      }),
    });

    const result = await response.json();
    const subscriber = result.data;

    if (!subscriber || !subscriber.id) {
      logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} adding tag to subscriber:`, {
        subscription_id,
        tag,
        response: result,
      });
      return false;
    }

    logFunction('info', `${SERVER_MESSAGES.INFO.TAG_ADDED}: "${tag}"`, subscription_id);
    return true;
  } catch (e) {
    logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} adding tag to subscriber:`, {
      subscription_id,
      tag,
      error: e,
    });
    return false;
  }
}

/**
 * Cancela la suscripción de un usuario
 */
export async function unsubscribeUser(email: string): Promise<SubscriptionResult> {
  try {
    const subscriberCheck = await checkSubscriber(email);

    if (!subscriberCheck.success || !subscriberCheck.subscriber) {
      logFunction('warn', SERVER_MESSAGES.INFO.SUBSCRIBER_NOT_FOUND, {
        action: 'unsubscribe',
        email,
      });
      return {
        success: false,
        message: FRONTEND_MESSAGES.ERRORS.EMAIL_NOT_SUBSCRIBED,
      };
    }

    const subscriptionId = subscriberCheck.subscriber.id;
    logFunction('info', `Unsubscribing user with id: ${subscriptionId}`, email);

    const response = await fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/${subscriptionId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${ENV.BEEHIIV.API_KEY}`,
      },
    });

    if (response.status === 204) {
      logFunction('info', SERVER_MESSAGES.INFO.USER_UNSUBSCRIBED, email);
      return {
        success: true,
        message: FRONTEND_MESSAGES.SUCCESS.UNSUBSCRIPTION,
      };
    } else {
      let errorData;
      try {
        errorData = await response.json();
      } catch (e) {
        errorData = { status: response.status };
      }

      logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} unsubscribing user:`, errorData);
      return {
        success: false,
        message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
      };
    }
  } catch (e) {
    logFunction('error', `${SERVER_MESSAGES.ERRORS.API_ERROR} unsubscribing user:`, e);
    return {
      success: false,
      message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
    };
  }
}
