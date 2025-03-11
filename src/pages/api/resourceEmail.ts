import { ENV } from '../../config/env';
import nodemailer from 'nodemailer';
import { logFunction } from './utils';

const siteTitle = ENV.SITE.TITLE;
const siteUrl = ENV.SITE.URL;

export interface ResourceEmailOptions {
  email: string;
  resourceId: string;
  resourceTitle: string;
  resourceLink: string;
}

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

export async function sendResourceEmail(options: ResourceEmailOptions): Promise<boolean> {
  try {
    if (!options.email || !options.resourceLink) {
      logFunction('error', 'Datos incompletos para envío de email', options);
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

    logFunction('info', 'Email de recurso enviado exitosamente', {
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

export function validateEmailConfiguration() {
  const requiredVars = ['EMAIL_HOST', 'EMAIL_PORT', 'EMAIL_USER', 'EMAIL_PASS'];

  const missingVars = requiredVars.filter((varName) => !process.env[varName]);

  if (missingVars.length > 0) {
    throw new Error(`Faltan configuraciones de email: ${missingVars.join(', ')}`);
  }
}

validateEmailConfiguration();
