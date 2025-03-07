import { ENV } from './env';
import { logFunction } from './utils';
import type { CreateSubscriber, GetSubscriber } from './types';

const BEEHIIV_API_SUBSCRIPTIONS = `https://api.beehiiv.com/v2/publications/${ENV.BEEHIIV.PUB_ID}/subscriptions`;

export async function checkSubscriber(
  email: string
): Promise<{ success: boolean; subscriber?: GetSubscriber }> {
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
      logFunction('warn', 'Subscriber not found:', email);
      return { success: false };
    }

    logFunction('info', 'Subscriber already exists:', email);
    return {
      success: true,
      subscriber: subscriber,
    };
  } catch (e) {
    logFunction('error', 'Error checking subscriber:', e);
    return { success: false };
  }
}

export async function subscribeUser(
  email: string,
  utm_source = 'landing_page'
): Promise<{ success: boolean; subscriber?: CreateSubscriber }> {
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
      logFunction('info', 'New subscriber created:', email);
      return {
        success: true,
        subscriber: subscriber,
      };
    } else {
      logFunction('error', 'Error subscribing user, API response:', result);
      return { success: false };
    }
  } catch (e) {
    logFunction('error', 'Exception subscribing user:', e);
    return { success: false };
  }
}

export async function addTagToSubscriber(subscription_id: string, tag: string): Promise<boolean> {
  try {
    if (tag === '') {
      logFunction('warn', 'Empty tag not added to subscriber:', subscription_id);
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
      logFunction('error', 'Error adding tag to subscriber:', {
        subscription_id,
        tag,
        response: result,
      });
      return false;
    }

    logFunction('info', `Tag "${tag}" added to subscriber:`, subscription_id);
    return true;
  } catch (e) {
    logFunction('error', 'Error adding tag to subscriber:', { subscription_id, tag, error: e });
    return false;
  }
}

export async function unsubscribeUser(
  email: string
): Promise<{ success: boolean; message: string }> {
  try {
    const subscriberCheck = await checkSubscriber(email);

    if (!subscriberCheck.success || !subscriberCheck.subscriber) {
      logFunction('warn', 'Subscriber not found for unsubscribe:', email);
      return {
        success: false,
        message: 'Este email no está suscrito',
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
      logFunction('info', 'User unsubscribed successfully:', email);
      return {
        success: true,
        message: 'User unsubscribed successfully',
      };
    } else {
      let errorData;
      try {
        errorData = await response.json();
      } catch (e) {
        errorData = { status: response.status };
      }

      logFunction('error', 'Error unsubscribing user, API response:', errorData);
      return {
        success: false,
        message: 'Error unsubscribing user',
      };
    }
  } catch (e) {
    logFunction('error', 'Exception unsubscribing user:', e);
    return {
      success: false,
      message: 'Internal server error during unsubscribe process',
    };
  }
}
