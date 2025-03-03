import * as dotenv from "dotenv";
import type { APIRoute } from "astro";
import { validateEmail } from "./utils";
import { logFunction } from "./logger";
import { Tag } from "./newsletter/types";
import {
  checkSubscriber,
  subscribeUser,
  addTagToSubscriber,
  checkAutomation,
  addSubscriberToAutomation,
} from "./beehiiv.service";

dotenv.config();
export const prerender = false;

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, tag, autId } = await request.json();

    logFunction("info", "Received request with data:", { email, tag, autId });

    if (!email || !validateEmail(email)) {
      logFunction("warn", "Invalid email provided:", email);
      return new Response(
        JSON.stringify({ message: 'Correo electrónico inválido.' }),
        { status: 400 }
      );
    }

    if (!tag) {
      logFunction("warn", "Invalid tag provided:", tag);
      return new Response(
        JSON.stringify({ message: 'Etiqueta inválida.' }),
        { status: 400 }
      );
    }

    if (autId) {
      const automationResponse = await checkAutomation(autId);
      if (!automationResponse.success) {
        return new Response(
          JSON.stringify({ message: 'ID de automatización inválido.' }),
          { status: 400 }
        );
      }
    } else {
      logFunction("warn", "No automation ID provided.");
    }

    const response = await checkSubscriber(email);

    if (response.success && response.subscriber) {
      await addTagToSubscriber(response.subscriber.id, tag);
      if (autId) {
        await addSubscriberToAutomation(autId, response.subscriber.id, response.subscriber.email);
      }
      return new Response(
        JSON.stringify({ message: 'Ya estás suscrito. Revisa tu correo.', already_subscribed: true }),
        { status: 200 }
      );
    } else {
      const response = await subscribeUser(email);
      if (response.success && response.subscriber) {
        await addTagToSubscriber(response.subscriber.id, Tag.NewSubscriber);
        await addTagToSubscriber(response.subscriber.id, tag);
        if (autId) {
          await addSubscriberToAutomation(autId, response.subscriber.id, response.subscriber.email);
        }
        return new Response(
          JSON.stringify({ message: 'De arte. Revisa tu correo, por favor.', already_subscribed: true }),
          { status: 200 }
        );
      }
    }

    return new Response(
      JSON.stringify({ message: "Error procesando la suscripción" }),
      { status: 500 }
    );
  } catch (e) {
    logFunction("error", "Error in subscription process:", e);
    return new Response(
      JSON.stringify({ message: "Error interno del servidor" }),
      { status: 500 }
    );
  }
};