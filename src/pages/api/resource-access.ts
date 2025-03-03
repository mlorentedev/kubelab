// src/pages/api/resource-access.ts
import type { APIRoute } from "astro";
import { validateEmail } from "./utils";
import { logFunction } from "./logger";
import { checkSubscriber, subscribeUser, addTagToSubscriber } from "./beehiiv.service";
import { sendResourceEmail } from "./resourceEmail";
import type { ResourceMap } from "./types";

export const prerender = false;

// Configuración centralizada de recursos
export const RESOURCES: ResourceMap = {
  // DevOps Lead Magnets
  "devops-checklist": {
    id: "devops-checklist",
    title: "DevOps Checklist Completa",
    description: "Una guía exhaustiva para implementar DevOps en tu organización",
    fileId: "1ABC123xyz_GoogleDriveFileId", // ID del archivo en Google Drive
    tags: ["devops", "lead-magnet"] // Tags para Beehiiv
  },
  "cloud-architecture": {
    id: "cloud-architecture",
    title: "Patrones de Arquitectura Cloud",
    description: "Los patrones más utilizados en arquitecturas cloud modernas",
    fileId: "1DEF456xyz_GoogleDriveFileId",
    tags: ["cloud", "architecture", "lead-magnet"]
  },
  // Kubernetes Lead Magnets
  "kubernetes-cheatsheet": {
    id: "kubernetes-cheatsheet",
    title: "Kubernetes Cheatsheet Definitiva",
    description: "Todos los comandos esenciales de Kubernetes en una sola hoja",
    fileId: "1GHI789xyz_GoogleDriveFileId",
    tags: ["kubernetes", "devops", "lead-magnet"]
  },
  // IaC Lead Magnets
  "terraform-templates": {
    id: "terraform-templates",
    title: "Plantillas Terraform para AWS",
    description: "Plantillas listas para usar en tus proyectos de infraestructura",
    fileId: "1JKL012xyz_GoogleDriveFileId",
    tags: ["terraform", "iac", "aws", "lead-magnet"]
  }
};

export const POST: APIRoute = async ({ request }) => {
  try {
    const { email, resourceId, tags = [] } = await request.json();

    // Validar datos
    if (!email || !validateEmail(email)) {
      return new Response(
        JSON.stringify({ success: false, message: 'Email inválido' }),
        { status: 400 }
      );
    }

    const resource = RESOURCES[resourceId as string];
    if (!resourceId || !resource) {
      return new Response(
        JSON.stringify({ success: false, message: 'Recurso inválido' }),
        { status: 400 }
      );
    }

    // Verificar si el usuario ya está suscrito
    const subscriberCheck = await checkSubscriber(email);
    let subscriber;
    
    if (subscriberCheck.success && subscriberCheck.subscriber) {
      // Usuario ya suscrito
      subscriber = subscriberCheck.subscriber;
      logFunction("info", "Existing subscriber requesting resource:", { email, resourceId });
    } else {
      // Nuevo suscriptor - añadir a Beehiiv
      const subscribeResponse = await subscribeUser(email);
      
      if (!subscribeResponse.success || !subscribeResponse.subscriber) {
        return new Response(
          JSON.stringify({ success: false, message: 'Error al procesar la suscripción' }),
          { status: 500 }
        );
      }
      
      subscriber = subscribeResponse.subscriber;
      logFunction("info", "New subscriber added and requesting resource:", { email, resourceId });
    }

    // Añadir tags para seguimiento (tanto los del recurso como los adicionales)
    const allTags = [...(resource.tags || []), ...tags, "lead-magnet", `resource-${resourceId}`];
    
    // Eliminar posibles duplicados
    const uniqueTags = [...new Set(allTags)];
    
    // Añadir cada tag al suscriptor
    for (const tag of uniqueTags) {
      await addTagToSubscriber(subscriber.id, tag);
    }
    
    // Generar enlace de acceso directo al recurso
    const driveFileId = resource.fileId;
    const resourceLink = generateDirectDownloadLink(driveFileId);
    
    // Enviar email con acceso
    await sendResourceEmail({
      email,
      resourceId,
      resourceTitle: resource.title,
      resourceDescription: resource.description,
      resourceLink
    });

    return new Response(
      JSON.stringify({ 
        success: true, 
        message: 'Hemos enviado el recurso a tu email.',
      }),
      { status: 200 }
    );
  } catch (error) {
    logFunction("error", "Error in resource access process:", error);
    
    return new Response(
      JSON.stringify({ success: false, message: 'Error interno del servidor' }),
      { status: 500 }
    );
  }
};

/**
 * Genera un enlace de descarga directa para Google Drive
 */
function generateDirectDownloadLink(fileId: string): string {
  return `https://drive.google.com/uc?export=download&id=${fileId}`;
}