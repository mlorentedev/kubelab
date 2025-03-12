// src/api/subscribe.ts

import { FRONTEND_MESSAGES } from '../../config/constants';
import type { APIRoute } from 'astro';
import { SubscriptionSource } from '../../domain/models';
import { processSubscription } from '../../services/subscription.service';
import { logFunction } from '../../utils/logging';
import { validateEmail } from '../../utils/validation';

export const prerender = false;

/**
 * Endpoint POST para suscribir usuarios
 */
export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, tag, utmSource } = await request.json();

    // Validar entrada
    if (!email || !validateEmail(email)) {
      return new Response(JSON.stringify({ message: FRONTEND_MESSAGES.ERRORS.INVALID_EMAIL }), {
        status: 400,
      });
    }

    // Procesar suscripción
    const result = await processSubscription(
      email,
      tag ? [tag] : [],
      utmSource || SubscriptionSource.LandingPage
    );

    // Devolver respuesta
    return new Response(
      JSON.stringify({
        message: result.message,
        alreadySubscribed: result.alreadySubscribed,
      }),
      { status: result.success ? 200 : 500 }
    );
  } catch (error) {
    logFunction('error', 'Error in subscription endpoint', error);
    return new Response(JSON.stringify({ message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR }), {
      status: 500,
    });
  }
};
