// src/services/email.service.ts
import { ENV } from '../config/env';
import nodemailer from 'nodemailer';
import { logFunction } from '../utils/logging';
import { SERVER_MESSAGES } from '../config/constants';
import type { ResourceEmailOptions } from '../domain/models';
import { generateResourceTitle, generateResourceUrl } from '../domain/business';

const siteTitle = ENV.SITE.TITLE;
const siteUrl = ENV.SITE.URL;

/**
 * Crea un transporter de email
 */
function createEmailTransporter() {
  return nodemailer.createTransport({
    host: ENV.EMAIL.HOST,
    port: parseInt(ENV.EMAIL.PORT),
    secure: ENV.EMAIL.SECURE,
    from: `"${ENV.SITE.AUTHOR}" <${ENV.SITE.MAIL}>`,
    auth: {
      user: ENV.EMAIL.USER,
      pass: ENV.EMAIL.PASS,
    },
  });
}

/**
 * Genera el HTML para el email de recurso
 */
function generateResourceEmailHTML(options: ResourceEmailOptions): string {
  const { resourceTitle, resourceLink } = options;
  const year = new Date().getFullYear();

  return `
    <div>
      <p>Hola,</p>
      <p>Aquí tienes tu ${resourceTitle}.</p>
      <p><a href="${resourceLink}">Ver</a></p>
      <p>Si el enlace no funciona, copia esta URL: ${resourceLink}</p>
      <p>---</p>
      <p>© ${year} ${siteTitle} | <a href="${siteUrl}">${siteUrl}</a></p>
    </div>
  `;
}

/**
 * Maneja errores de envío de email
 */
function handleEmailError(error: any): void {
  const errorDetails = {
    code: error.code,
    response: error.response,
    responseCode: error.responseCode,
    command: error.command,
  };

  if (error.code === 'EAUTH') {
    logFunction('error', 'Authentication failed. Check credentials.', errorDetails);
  } else if (error.code === 'ECONNECTION') {
    logFunction('error', 'Connection error. Check network or firewall.', errorDetails);
  } else if (error.code === 'ETIMEDOUT') {
    logFunction('error', 'Connection timed out. Check network.', errorDetails);
  } else if (error.responseCode >= 500) {
    logFunction('error', 'Server error from mail provider.', errorDetails);
  } else if (error.responseCode >= 400) {
    logFunction('error', 'Client error in email sending.', errorDetails);
  } else {
    logFunction('error', 'Unknown error during email sending', errorDetails);
  }
}

/**
 * Envía un email con un recurso
 */
export async function sendResourceEmail(options: ResourceEmailOptions): Promise<boolean> {
  try {
    if (!options.email || !options.resourceLink) {
      logFunction('error', 'Incomplete data for email sending', options);
      return false;
    }

    const transporter = createEmailTransporter();

    const mailOptions = {
      from: `"${ENV.SITE.AUTHOR}" <${ENV.EMAIL.USER}>`,
      to: options.email,
      subject: `Aquí tienes: ${options.resourceTitle}`,
      html: generateResourceEmailHTML(options),

      headers: {
        Precedence: 'bulk',
        'X-Auto-Response-Suppress': 'All',
        'List-Unsubscribe': `<${siteUrl}/unsubscribe>`,
        'X-Site-Origin': siteTitle,
      },

      dsn: {
        id: `resource-${options.resourceId}`,
        return: 'full',
        notify: ['failure', 'delay'],
        recipient: ENV.EMAIL.USER,
      },
    };

    const info = await transporter.sendMail(mailOptions);

    logFunction('info', SERVER_MESSAGES.INFO.EMAIL_SENT, {
      email: options.email,
      resourceId: options.resourceId,
      accepted: info.accepted,
      rejected: info.rejected,
    });

    return true;
  } catch (error) {
    handleEmailError(error);
    return false;
  }
}

/**
 * Programa el envío de un email con recurso (con delay)
 */
export async function scheduleResourceEmail({
  email,
  resourceId,
  fileId,
  delayMinutes = 1,
}: {
  email: string;
  resourceId: string;
  fileId: string;
  delayMinutes?: number;
}): Promise<void> {
  return new Promise<void>((resolve, reject) => {
    setTimeout(
      async () => {
        try {
          const emailSent = await sendResourceEmail({
            email,
            resourceId,
            resourceTitle: generateResourceTitle(resourceId),
            resourceLink: generateResourceUrl(fileId),
          });

          if (emailSent) {
            logFunction('info', 'Delayed email sent successfully', { email, resourceId });
            resolve();
          } else {
            logFunction('warn', SERVER_MESSAGES.WARN.EMAIL_DELIVERY_ISSUE, {
              email,
              resourceId,
              fileId,
            });
            reject(new Error('Email could not be sent'));
          }
        } catch (error) {
          logFunction('error', 'Error sending delayed email', error);
          reject(error);
        }
      },
      delayMinutes * 60 * 1000
    );
  });
}

/**
 * Valida que exista la configuración de email
 */
export function validateEmailConfiguration(): boolean {
  try {
    const requiredVars = ['EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USER', 'EMAIL_PASS'];
    const missingVars = requiredVars.filter((varName) => !process.env[varName]);

    if (missingVars.length > 0) {
      logFunction('error', `Missing email configuration: ${missingVars.join(', ')}`);
      return false;
    }

    return true;
  } catch (error) {
    logFunction('error', 'Error validating email configuration', error);
    return false;
  }
}
