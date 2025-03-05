import { processSubscription } from './subscription.service';
import { SubscriptionSource } from './types';
import { sendResourceEmail } from './resourceEmail';
import { logFunction } from './utils';
import type { APIRoute } from 'astro';

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, resourceId, fileId, tags = [] } = await request.json();

    if (!email || !resourceId || !fileId) {
      return new Response(
        JSON.stringify({
          success: false,
          message: 'Datos incompletos',
        }),
        { status: 400 }
      );
    }

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

    const emailSent = await sendResourceEmail({
      email,
      resourceId,
      resourceTitle: `Recurso ${resourceId}`,
      resourceLink: `https://drive.google.com/uc?export=download&id=${fileId}`,
    });

    return new Response(
      JSON.stringify({
        success: true,
        message: emailSent ? 'Recurso enviado exitosamente' : 'Recurso suscrito, email pendiente',
      }),
      { status: 200 }
    );
  } catch (error) {
    logFunction('error', 'Error en lead magnet', error);
    return new Response(
      JSON.stringify({
        success: false,
        message: 'Error interno',
      }),
      { status: 500 }
    );
  }
};
