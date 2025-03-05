import { ENV } from '../api/env';

import nodemailer from 'nodemailer';
import { logFunction } from './utils';

const siteTitle = ENV.SITE.TITLE;
const siteDomain = ENV.SITE.DOMAIN;
const siteUrl = ENV.SITE.URL;

export interface ResourceEmailOptions {
  email: string;
  resourceId: string;
  resourceTitle: string;
  resourceDescription?: string;
  resourceLink: string;
}

function createEmailTransporter() {
  return nodemailer.createTransport({
    host: ENV.EMAIL.HOST,
    port: parseInt(ENV.EMAIL.PORT),
    secure: ENV.EMAIL.SECURE,
    auth: {
      user: ENV.EMAIL.USER,
      pass: ENV.EMAIL.PASS,
    },
  });
}

function generateResourceEmailHTML(options: ResourceEmailOptions): string {
  const {
    resourceTitle,
    resourceDescription = 'Recurso solicitado',
    resourceLink,
    email,
  } = options;
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
          © ${year} ${siteTitle}<br>
          Este email fue enviado a ${email} porque solicitaste este recurso.
        </p>
        
        <p>
          <a href="${siteUrl}" style="color: #0097a7; text-decoration: none;">Visita mi web</a> |
          <a href="https://twitter.com/mlorentedev" style="color: #0097a7; text-decoration: none;">Twitter</a> |
          <a href="https://www.youtube.com/@mlorentedev" style="color: #0097a7; text-decoration: none;">YouTube</a>
        </p>
      </div>
    </div>
  `;
}

export async function sendResourceEmail(options: ResourceEmailOptions): Promise<boolean> {
  try {
    if (!options.email || !options.resourceLink) {
      logFunction('error', 'Datos incompletos para envío de email', options);
      return false;
    }

    const transporter = createEmailTransporter();

    const mailOptions = {
      from: `"${siteTitle}" <${ENV.EMAIL.USER}>`,
      to: options.email,
      subject: `Tu recurso: ${options.resourceTitle}`,
      html: generateResourceEmailHTML(options),
    };

    await transporter.sendMail(mailOptions);

    logFunction('info', 'Email de recurso enviado exitosamente', {
      email: options.email,
      resourceId: options.resourceId,
    });

    return true;
  } catch (error) {
    logFunction('error', 'Error al enviar email de recurso', error);
    return false;
  }
}

export function validateEmailConfiguration() {
  const requiredVars = ['EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USER', 'EMAIL_PASS'];

  const missingVars = requiredVars.filter((varName) => !process.env[varName]);

  if (missingVars.length > 0) {
    throw new Error(`Faltan configuraciones de email: ${missingVars.join(', ')}`);
  }
}

validateEmailConfiguration();
