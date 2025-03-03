import { logFunction } from './logger';
import type { CreateSubscriber, GetSubscriber, Tag } from './newsletter/types';
import { BEEHIIV_PUB_ID } from "../../../utils/consts";

const BEEHIIV_API_SUBSCRIPTIONS = `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB_ID}/subscriptions`;
const BEEHIIV_API_AUTOMATIONS = `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB_ID}/automations`;

export async function checkSubscriber(email: string): Promise<{ success: boolean; subscriber?: GetSubscriber }> {
  try {
    const response = await fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/by_email/${email}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.BEEHIIV_API_KEY}`,
      },
    });

    const subscriber = (await response.json()).data;

    if (!subscriber) {
      logFunction("warn", "Subscriber not found:", email);
      return { success: false };
    }
    logFunction("info", "Subscriber already exists:", email);
    return {
      success: !!subscriber.id,
      subscriber: subscriber,
    };
  } catch (e) {
    logFunction("error", "Error checking subscriber:", e);
    return { success: false };
  }
}

export async function subscribeUser(email: string): Promise<{ success: boolean; subscriber?: CreateSubscriber }> {
  try {
    const response = await fetch(BEEHIIV_API_SUBSCRIPTIONS, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.BEEHIIV_API_KEY}`,
      },
      body: JSON.stringify({
        email: email,
        utm_source: "landing_page",
      }),
    });

    const subscriber = (await response.json()).data;

    if (subscriber) {
      logFunction("info", "New subscriber:", email);
      return {
        success: true,
        subscriber: subscriber,
      };
    } else {
      logFunction("error", "Error subscribing user:", subscriber);
      return { success: false };
    }
  } catch (e) {
    logFunction("error", "Error subscribing user:", e);
    return { success: false };
  }
}

export async function addTagToSubscriber(subscription_id: string, tag: string): Promise<boolean> {
  try {
    const response = await fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/${subscription_id}/tags`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.BEEHIIV_API_KEY}`,
      },
      body: JSON.stringify({
        tags: [tag],
      }),
    });

    const subscriber = (await response.json()).data;

    if (!subscriber) {
      logFunction("error", "Error adding tag to subscriber:", subscription_id);
      return false;
    }
    logFunction("info", "Tag added to subscriber:", subscription_id);
    return true;
  } catch (e) {
    logFunction("error", "Error adding tag to subscriber:", e);
    return false;
  }
}

export async function checkAutomation(aut_id: string): Promise<{ success: boolean }> {
  try {
    const response = await fetch(`${BEEHIIV_API_AUTOMATIONS}/${aut_id}`, {
      method: "GET",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.BEEHIIV_API_KEY}`,
      },
    });

    const automation = (await response.json()).data;

    if (!automation) {
      logFunction("error", "Automation not found:", aut_id);
      return { success: false };
    }
    logFunction("info", "Automation found:", automation.id);
    return { success: true };
  } catch (e) {
    logFunction("error", "Error checking automation:", e);
    return { success: false };
  }
}

export async function addSubscriberToAutomation(aut_id: string, subscription_id: string, email: string): Promise<boolean> {
  try {
    const response = await fetch(`${BEEHIIV_API_AUTOMATIONS}/${aut_id}/journeys`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${process.env.BEEHIIV_API_KEY}`,
      },
      body: JSON.stringify({
        email: email,
        subscription_id: subscription_id,
      }),
    });

    const automation = await response.json();

    if (!automation) {
      logFunction("error", "Error adding subscriber to automation:", aut_id);
      return false;
    }
    logFunction("info", "Subscriber added to automation:", aut_id);
    return true;
  } catch (e) {
    logFunction("error", "Error adding subscriber to automation:", e);
    return false;
  }
}