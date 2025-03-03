// utils/resourceEmail.ts
import nodemailer from 'nodemailer';
import { logFunction } from './logger';
import { SITE_TITLE, SITE_DOMAIN } from '../../../utils/consts';

// Configuración del transporte de email
const transporter = nodemailer.createTransport({
  host: process.env.EMAIL_HOST || 'smtp.gmail.com',
  port: parseInt(process.env.EMAIL_PORT || '587'),
  secure: process.env.EMAIL_SECURE === 'true',
  auth: {
    user: process.env.EMAIL_USER,
    pass: process.env.EMAIL_PASS,
  },
});

// Interfaces para tipado
interface ResourceEmailOptions {
  email: string;
  resourceId: string;
  resourceTitle: string;
  resourceDescription: string;
  resourceLink: string;
}

/**
 * Envía un email con el enlace al recurso solicitado
 */
export async function sendResourceEmail(options: ResourceEmailOptions): Promise<boolean> {
  const { email, resourceId, resourceTitle, resourceDescription, resourceLink } = options;
  
  try {
    const mailOptions = {
      from: `"${SITE_TITLE}" <${process.env.EMAIL_USER}>`,
      to: email,
      subject: `Tu recurso: ${resourceTitle}`,
      html: getEmailTemplate({
        resourceTitle,
        resourceDescription,
        resourceLink,
        email
      })
    };

    await transporter.sendMail(mailOptions);
    logFunction("info", "Resource email sent successfully", { email, resourceId });
    return true;
  } catch (error) {
    logFunction("error", "Error sending resource email", error);
    return false;
  }
}

/**
 * Plantilla de email para recursos
 */
function getEmailTemplate({ 
  resourceTitle, 
  resourceDescription, 
  resourceLink, 
  email 
}: {
  resourceTitle: string;
  resourceDescription: string;
  resourceLink: string;
  email: string;
}) {
  const year = new Date().getFullYear();
  
  return `
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
      <div style="background-color: #0097a7; padding: 20px; text-align: center; border-radius: 8px 8px 0 0;">
        <h1 style="color: white; margin: 0; font-size: 24px;">${resourceTitle}</h1>
      </div>
      
      <div style="background-color: #f9f9f9; padding: 30px; border-radius: 0 0 8px 8px; border: 1px solid #eee; border-top: none;">
        <p style="margin-top: 0;">Hola,</p>
        
        <p>Gracias por tu interés en <strong>${resourceTitle}</strong>.</p>
        
        <p>${resourceDescription}</p>
        
        <div style="margin: 30px 0; text-align: center;">
          <a href="${resourceLink}" 
             style="background-color: #0097a7; color: white; padding: 12px 25px; text-decoration: none; border-radius: 4px; font-weight: bold; display: inline-block;">
            Descargar recurso
          </a>
        </div>
        
        <p style="margin-top: 30px; font-size: 14px; color: #666;">
          Si tienes problemas para acceder al recurso, copia y pega este enlace en tu navegador:
        </p>
        
        <p style="background-color: #eee; padding: 10px; border-radius: 4px; word-break: break-all; font-size: 12px;">
          <a href="${resourceLink}" style="color: #0097a7; text-decoration: none;">${resourceLink}</a>
        </p>
      </div>
      
      <div style="text-align: center; margin-top: 20px; color: #666; font-size: 12px;">
        <p>
          © ${year} ${SITE_DOMAIN}<br>
          Este email fue enviado a ${email} porque solicitaste este recurso.
        </p>
        
        <p>
          <a href="https://${SITE_DOMAIN}" style="color: #0097a7; text-decoration: none;">Visita mi web</a> |
          <a href="https://twitter.com/mlorentedev" style="color: #0097a7; text-decoration: none;">Twitter</a> |
          <a href="https://www.youtube.com/@mlorentedev" style="color: #0097a7; text-decoration: none;">YouTube</a>
        </p>
      </div>
    </div>
  `;
}