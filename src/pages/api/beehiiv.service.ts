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
