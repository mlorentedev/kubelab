import { processSubscription } from './subscription.service';
import { SubscriptionSource } from './types';
import { sendResourceEmail } from './resourceEmail';
import { logFunction } from './utils';
import type { APIRoute } from 'astro';

export const prerender = false;

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

    scheduleResourceEmail({
      email,
      resourceId,
      fileId,
    });

    return new Response(
      JSON.stringify({
        success: true,
        message: 'Recurso enviado',
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

const scheduleResourceEmail = async ({
  email,
  resourceId,
  fileId,
}: {
  email: string;
  resourceId: string;
  fileId: string;
}) => {
  return new Promise<void>((resolve, reject) => {
    setTimeout(
      async () => {
        try {
          const emailSent = await sendResourceEmail({
            email,
            resourceId,
            resourceTitle: `Recurso ${resourceId}`,
            resourceLink: `https://drive.google.com/file/d/${fileId}/view?usp=drive_link`,
          });

          if (emailSent) {
            logFunction('info', 'Delayed email sent successfully', { email, resourceId });
            resolve();
          } else {
            logFunction('warn', 'Delayed email not sent', { email, resourceId, fileId });
            reject(new Error('Email could not be sent'));
          }
        } catch (error) {
          logFunction('error', 'Error sending delayed email', error);
          reject(error);
        }
      },
      1000 * 60 * 1
    );
  });
};
