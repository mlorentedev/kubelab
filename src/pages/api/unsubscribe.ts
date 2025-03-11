// src/api/unsubscribe.ts

import type { APIRoute } from 'astro';
import { FRONTEND_MESSAGES, URLS } from '../../config/constants';
import { unsubscribeUser } from '../../services/beehiiv.service';
import { logFunction } from '../../utils/logging';
import { validateEmail } from '../../utils/validation';

export const prerender = false;

/**
 * Endpoint POST para cancelar suscripción
 */
export const POST: APIRoute = async ({ request }) => {
  try {
    const { email } = await request.json();

    // Validar entrada
    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.INVALID_EMAIL,
        }),
        { status: 400 }
      );
    }

    // Procesar cancelación
    const result = await unsubscribeUser(email);

    // Devolver respuesta
    return new Response(
      JSON.stringify({
        success: result.success,
        message: result.message,
      }),
      { status: result.success ? 200 : 500 }
    );
  } catch (error) {
    logFunction('error', 'Error in unsubscribe endpoint', error);
    return new Response(
      JSON.stringify({
        success: false,
        message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
      }),
      { status: 500 }
    );
  }
};

/**
 * Endpoint GET para cancelar suscripción con redirección
 */
export const GET: APIRoute = async ({ url }) => {
  try {
    const email = url.searchParams.get('email');

    // Validar entrada
    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.INVALID_EMAIL,
        }),
        { status: 400 }
      );
    }

    // Procesar cancelación
    const result = await unsubscribeUser(email);

    // Redireccionar según resultado
    return new Response(null, {
      status: 302,
      headers: {
        Location: result.success ? URLS.SUCCESS_PAGES.UNSUBSCRIBE : URLS.ERROR_PAGES.NOT_FOUND,
      },
    });
  } catch (error) {
    logFunction('error', 'Error in GET unsubscribe endpoint', error);
    return new Response(null, {
      status: 302,
      headers: {
        Location: URLS.ERROR_PAGES.NOT_FOUND,
      },
    });
  }
};
