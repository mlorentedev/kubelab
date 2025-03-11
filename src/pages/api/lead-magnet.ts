import type { APIRoute } from 'astro';
import { scheduleResourceEmail, validateEmailConfiguration } from '../../services/email.service';
import { FRONTEND_MESSAGES } from '../../config/constants';
import { validateEmail } from '../../utils/validation';
import { processSubscription } from '../../services/subscription.service';
import { SubscriptionSource } from '../../domain/models';
import { logFunction } from '../../utils/logging';

export const prerender = false;

/**
 * Endpoint POST para procesar lead magnet (suscripción + envío de recurso)
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

    const { email, resourceId, fileId, tags = [] } = await request.json();

    // Validar entrada
    if (!email || !resourceId || !fileId) {
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

    // Procesar suscripción
    const subscriptionResult = await processSubscription(
      email,
      [...tags, `resource-${resourceId}`],
      SubscriptionSource.LeadMagnet
    );

    if (!subscriptionResult.success) {
      return new Response(
        JSON.stringify({
          success: false,
          message: subscriptionResult.message,
        }),
        { status: 500 }
      );
    }

    // Si la suscripción fue exitosa, programar el envío del email con recurso
    scheduleResourceEmail({
      email,
      resourceId,
      fileId,
      delayMinutes: 1,
    }).catch((error) => {
      logFunction('error', 'Error scheduling resource email', error);
    });

    logFunction('info', 'Lead magnet processed successfully', { email, resourceId });

    // Devolver respuesta
    return new Response(
      JSON.stringify({
        success: true,
        message: FRONTEND_MESSAGES.SUCCESS.RESOURCE_SENT,
      }),
      { status: 200 }
    );
  } catch (error) {
    logFunction('error', 'Error in lead magnet endpoint', error);
    return new Response(
      JSON.stringify({
        success: false,
        message: FRONTEND_MESSAGES.ERRORS.SERVER_ERROR,
      }),
      { status: 500 }
    );
  }
};
