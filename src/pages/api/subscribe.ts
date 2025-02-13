export const prerender = false;

import type { APIRoute } from "astro";

import { BEEHIIV_PUB_ID } from "../../../utils/consts";

const BEEHIIV_API_SUBSCRIPTIONS = `https://api.beehiiv.com/v2/publications/${BEEHIIV_PUB_ID}/subscriptions`;

interface Subscriber {
  id: string;
  email: string;
  tags: string[];
  [key: string]: any;
}

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, tag } = await request.json();

    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({ message: 'Correo electrónico inválido.' }),
        { status: 400 }
      );
    }

    if (!tag) {
      return new Response(
        JSON.stringify({ message: 'Etiqueta inválida.' }),
        { status: 400 }
      );
    }

    const response = await checkSubscriber(email);

    if (response.success && response.subscriber) {
      await addTagToSubscriber(response.subscriber.id, tag);
      return new Response(
        JSON.stringify({ message: 'Ya estás suscrito. Revisa tu correo.', already_subscribed: true }),
        { status: 200 }
      );
    }
    else {
      await subscribeUser(email, tag);
        return new Response(
          JSON.stringify({ message: 'De arte. Revisa tu correo, por favor.', already_subscribed: true }),
          { status: 200 }
        );
    }
    } catch (error) {
      return new Response(JSON.stringify({ message: "Error interno del servidor" }), { status: 500 });
    }
};

function validateEmail(email: string): boolean {
  const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return re.test(email);
}

function checkSubscriber(email: string): Promise<{ success: boolean; subscriber?: Subscriber }> {
  return fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/by_email/${email}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${import.meta.env.BEEHIIV_API_KEY}`,
    },
  })
    .then((res) => res.json())
    .then((data) => data.subscriber);
}

function subscribeUser(email: string, tag: string): Promise<boolean> {
  return fetch(BEEHIIV_API_SUBSCRIPTIONS, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${import.meta.env.BEEHIIV_API_KEY}`,
    },
    body: JSON.stringify({
      email: email,
      utm_source: "landing_page",
      tag: tag,
    }),
  })
    .then((res) => res.json())
    .then((data) => data.success);
}

function addTagToSubscriber(subscription_id: string, tag: string): Promise<boolean> {
  return fetch(`${BEEHIIV_API_SUBSCRIPTIONS}/${subscription_id}/tags`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${import.meta.env.BEEHIIV_API_KEY}`,
    },
    body: JSON.stringify({
      tags: [tag],
    }),
  })
    .then((res) => res.json())
    .then((data) => data.success);
}