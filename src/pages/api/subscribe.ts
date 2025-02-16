import pino from "pino";

import pretty from "pino-pretty";

import * as dotenv from "dotenv";

import type { APIRoute } from "astro";

import { BEEHIIV_PUB_ID } from "../../../utils/consts";

dotenv.config();

export const prerender = false;

const BEEHIIV_API_SUBSCRIPTIONS = `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB_ID}/subscriptions`;
const BEEHIIV_API_AUTOMATIONS = `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB_ID}/automations`;

const enum Tag {
  NewSubscriber = "new",
  ExistingSubscriber = "existing",
}

const prettyStream = pretty({
  colorize: true,
  ignore: "pid,hostname",
  messageKey: "msg",
  singleLine: true,
});

const logger = pino(prettyStream);

interface GetSubscriber {
  id: string;
  email: string;
  tags: string[];
  [key: string]: any;
}

interface CreateSubscriber {
  id: string;
  email: string;
  [key: string]: any;
}

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, tag, aut_id } = await request.json();

    if (!email || !validateEmail(email)) {
      logFunction("warn", "Invalid email provided:", email);
      return new Response(
        JSON.stringify({ message: 'Correo electrónico inválido.' }),
        { status: 400 }
      );
    }

    if (!tag) {
      logFunction("warn", "Invalid tag provided:", tag);
      return new Response(
        JSON.stringify({ message: 'Etiqueta inválida.' }),
        { status: 400 }
      );
    }

    if (aut_id) {
      const automationResponse = await checkAutomation(aut_id);
      if (!automationResponse.success) {
        return new Response(
          JSON.stringify({ message: 'ID de automatización inválido.' }),
          { status: 400 }
        );
      }
    } else {
      logFunction("warn", "No automation ID provided.");
    }

    const response = await checkSubscriber(email);

    if (response.success && response.subscriber) {
      await addTagToSubscriber(response.subscriber.id, tag);
      if (aut_id) { await addSuscriberToAutomation(aut_id, response.subscriber.id, response.subscriber.email); }
      return new Response(
        JSON.stringify({ message: 'Ya estás suscrito. Revisa tu correo.', already_subscribed: true }),
        { status: 200 }
      );
    }
    else {
      const response = await subscribeUser(email);
      if (response.success && response.subscriber) {
        await addTagToSubscriber(response.subscriber.id, Tag.NewSubscriber);
        await addTagToSubscriber(response.subscriber.id, tag);
        if (aut_id) { await addSuscriberToAutomation(aut_id, response.subscriber.id, response.subscriber.email); }
        return new Response(
          JSON.stringify({ message: 'De arte. Revisa tu correo, por favor.', already_subscribed: true }),
          { status: 200 }
        );
      }
    }
    } catch (e) {
      logFunction("error", "Error in subscription process:", e);
      return new Response(JSON.stringify({ message: "Error interno del servidor" }), { status: 500 });
    }
    return new Response(JSON.stringify({ message: "Unexpected error" }), { status: 500 });
};

function logFunction(level: "info" | "warn" | "error", message: string, data?: any) {
  const stack = new Error().stack || "";
  const functionName = stack.split("\n")[2]?.trim().split(" ")[1] || "unknown function";
  logger[level](`${functionName}: ${message} ${data}`);
}

function validateEmail(email: string): boolean {
  const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return re.test(email);
}

async function checkSubscriber(email: string): Promise<{ success: boolean; subscriber?: GetSubscriber }> {
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


async function subscribeUser(email: string): Promise<{ success: boolean; subscriber?: CreateSubscriber }> {
  
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
    })

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

async function addTagToSubscriber(subscription_id: string, tag: string): Promise<boolean> {
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
      logFunction("error", "Error adding tag to subscriber:", subscriber.id);
      return false;
    }
    logFunction("info", "Tag added to new subscriber:", subscriber.id);
    return true;
  }
  catch (e) {
    logFunction("error", "Error adding tag to subscriber:", e);
    return false;
  }

}

async function checkAutomation(aut_id: string): Promise<{ success: boolean}> {
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
    return {success: true};
  } catch (e) {
    logFunction("error", "Error checking automation:", e);
    return { success: false };
  }
}

async function addSuscriberToAutomation(aut_id: string, subscription_id: string, email: string): Promise<boolean> {
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
  }
  catch (e) {
    logFunction("error", "Error adding subscriber to automation:", e);
    return false;
  }
}
