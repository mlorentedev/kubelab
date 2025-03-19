FROM nginx:alpine

# Eliminar la configuración por defecto
RUN rm /etc/nginx/conf.d/default.conf

# Copiar configuraciones personalizadas
COPY docker/nginx/conf.d /etc/nginx/conf.d

# Configurar permisos para ejecutar como usuario no-root
RUN chown -R nginx:nginx /var/cache/nginx && \
    chown -R nginx:nginx /var/log/nginx && \
    chown -R nginx:nginx /etc/nginx/conf.d && \
    touch /var/run/nginx.pid && \
    chown -R nginx:nginx /var/run/nginx.pid

# Configurar usuario no-root
USER nginx

# Exponer puertos
EXPOSE 80 443

# Verificar la configuración de nginx al inicio
CMD ["nginx", "-g", "daemon off;"]