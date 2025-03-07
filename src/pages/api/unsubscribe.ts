import { unsubscribeUser } from './beehiiv.service';
import { validateEmail, logFunction } from './utils';
import type { APIRoute } from 'astro';

export const prerender = false;

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email } = await request.json();

    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({
          success: false,
          message: 'Correo electrónico inválido.',
        }),
        { status: 400 }
      );
    }

    const result = await unsubscribeUser(email);

    return new Response(
      JSON.stringify({
        success: result.success,
        message: result.message,
      }),
      { status: result.success ? 200 : 500 }
    );
  } catch (error) {
    logFunction('error', 'Error en endpoint de cancelación de suscripción', error);
    return new Response(
      JSON.stringify({
        success: false,
        message: 'Error interno del servidor',
      }),
      { status: 500 }
    );
  }
};

export const GET: APIRoute = async ({ url }) => {
  try {
    const email = url.searchParams.get('email');

    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({
          success: false,
          message: 'Correo electrónico inválido o token no válido.',
        }),
        { status: 400 }
      );
    }

    const result = await unsubscribeUser(email);

    return new Response(null, {
      status: 302,
      headers: {
        Location: result.success ? '/unsubscribe-success' : '/404',
      },
    });
  } catch (error) {
    logFunction('error', 'Error en endpoint GET de cancelación de suscripción', error);
    return new Response(null, {
      status: 302,
      headers: {
        Location: '/404',
      },
    });
  }
};
