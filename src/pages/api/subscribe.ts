export const prerender = false;

import type { APIRoute } from "astro";

import { BEEHIIV_API_URL } from "../../../utils/consts";

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email } = await request.json();

    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({ message: 'Correo electrónico inválido.' }),
        { status: 400 }
      );
    }

    const response = await fetch(BEEHIIV_API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${import.meta.env.BEEHIIV_API_KEY}`,
      },
      body: JSON.stringify({ email }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      return new Response(JSON.stringify({ message: `Error: ${errorText}` }), { status: 500 });
    }

    return new Response(JSON.stringify({ message: "De arte. Revisa tu correo, por favor." }), { status: 200 });
  } catch (error) {
    return new Response(JSON.stringify({ message: "Error interno del servidor" }), { status: 500 });
  }
};

function validateEmail(email: string): boolean {
  const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
  return re.test(email);
}