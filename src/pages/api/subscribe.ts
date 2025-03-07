import { processSubscription } from './subscription.service';
import { SubscriptionSource } from './types';
import { validateEmail, logFunction } from './utils';

export const prerender = false;

import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, tag, utmSource } = await request.json();

    if (!email || !validateEmail(email)) {
      return new Response(JSON.stringify({ message: 'Correo electrónico inválido.' }), {
        status: 400,
      });
    }

    const result = await processSubscription(
      email,
      [tag],
      utmSource || SubscriptionSource.LandingPage
    );

    return new Response(
      JSON.stringify({
        message: result.message,
        alreadySubscribed: result.alreadySubscribed,
      }),
      { status: result.success ? 200 : 500 }
    );
  } catch (error) {
    logFunction('error', 'Error en endpoint de suscripción', error);
    return new Response(JSON.stringify({ message: 'Error interno del servidor' }), { status: 500 });
  }
};
