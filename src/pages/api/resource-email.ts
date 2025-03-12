// src/api/resource-email.ts

import type { APIRoute } from 'astro';
import { FRONTEND_MESSAGES } from '../../config/constants';
import { generateResourceTitle } from '../../domain/business';
import { validateEmailConfiguration, sendResourceEmail } from '../../services/email.service';
import { logFunction } from '../../utils/logging';
import { validateEmail } from '../../utils/validation';

export const prerender = false;

/**
 * Endpoint POST para enviar email con recurso
 */
export const POST: APIRoute = async ({ request }) => {
  try {
    // Validar configuración de email
    if (!validateEmailConfiguration()) {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.EMAIL_CONFIG_ERROR,
        }),
        { status: 500 }
      );
    }

    const { email, resourceId, resourceTitle, resourceLink } = await request.json();

    // Validar datos requeridos
    if (!email || !resourceId || !resourceLink) {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.INCOMPLETE_DATA,
        }),
        { status: 400 }
      );
    }

    // Validar email
    if (!validateEmail(email)) {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.INVALID_EMAIL,
        }),
        { status: 400 }
      );
    }

    // Enviar email con recurso
    const emailSent = await sendResourceEmail({
      email,
      resourceId,
      resourceTitle: resourceTitle || generateResourceTitle(resourceId),
      resourceLink,
    });

    if (emailSent) {
      logFunction('info', 'Resource email sent successfully', { email, resourceId });
      return new Response(
        JSON.stringify({
          success: true,
          message: FRONTEND_MESSAGES.SUCCESS.EMAIL_SENT,
        }),
        { status: 200 }
      );
    } else {
      return new Response(
        JSON.stringify({
          success: false,
          message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
        }),
        { status: 500 }
      );
    }
  } catch (error) {
    logFunction('error', 'Error in resource email endpoint', error);
    return new Response(
      JSON.stringify({
        success: false,
        message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
      }),
      { status: 500 }
    );
  }
};
