import pino from 'pino';
import pretty from 'pino-pretty';

const prettyStream = pretty({
  colorize: true,
  ignore: 'pid,hostname',
  messageKey: 'msg',
  singleLine: true,
});

export const logger = pino(prettyStream);

export function logFunction(level: 'info' | 'warn' | 'error', message: string, data?: any) {
  const stack = new Error().stack || '';
  const functionName = stack.split('\n')[2]?.trim().split(' ')[1] || 'unknown function';
  logger[level](`${functionName}: ${message} ${data !== undefined ? JSON.stringify(data) : ''}`);
}
