# mlorente.dev

Web personal construida con Jekyll, contenerizada con Docker y desplegada utilizando Traefik para terminación SSL y proxy inverso.

## Características

- Sitio web estático construido con Jekyll
- Diseño totalmente responsive
- Contenerizado con Docker
- Compilaciones automatizadas via GitHub Actions
- Certificados SSL gestionados por Traefik vía Let's Encrypt
- Categorías y etiquetas para el contenido
- Estimación de tiempo de lectura
- Soporte para Markdown
- Optimizado para SEO

## Estructura del proyecto

```bash
├── .github/                       # Configuraciones de workflows de GitHub Actions
├── ansible/                       # Configuración de Ansible para despliegues
│   ├── inventory/                 # Inventario de hosts y variables
│   ├── playbooks/                 # Playbooks para diferentes tareas
│   └── templates/                 # Plantillas para configuración
├── core/
│   └── infrastructure/            # Archivos de infraestructura
│       ├── docker-compose/        # Configuraciones de Docker Compose
│       ├── scripts/               # Scripts de utilidad (legacy)
│       └── traefik/               # Plantillas de configuración de Traefik
├── frontend/                      # Directorio principal del sitio Jekyll
│   ├── _config.yml                # Configuración de Jekyll
│   ├── _data                      # Archivos de datos para Jekyll
│   ├── _includes                  # Includes de plantillas
│   ├── _layouts                   # Layouts de páginas
│   ├── _posts                     # Contenido de posts del blog
│   ├── 404.html                   # Página de error 404
│   ├── aboutme.html               # Página "Sobre mí"
│   ├── assets                     # Activos estáticos
│   │   ├── css                    # Hojas de estilo
│   │   ├── cv                     # Archivos de CV/currículum
│   │   ├── img                    # Recursos de imágenes
│   │   ├── js                     # Archivos JavaScript
│   │   └── pdf                    # Documentos PDF
│   ├── Dockerfile                 # Definición de imagen Docker
│   ├── Gemfile                    # Dependencias de Ruby
│   └── index.html                 # Página de inicio
├── .env.example                   # Ejemplo de variables de entorno
├── Makefile                       # Makefile para automatización
├── README.md                      # Documentación del proyecto
└── LICENSE                        # Archivo de licencia
```

## Prerrequisitos

- Docker y Docker Compose
- Git
- Make
- Ansible (opcional, para despliegues remotos)
- Una cuenta de DockerHub para almacenar las imágenes de contenedor
- Un nombre de dominio (para entornos de staging y producción)
- Un servidor con acceso SSH (para staging y producción)

## Instalación de dependencias

Para instalar todas las dependencias necesarias:

```bash
make install-deps
```

Para instalar Ansible y sus colecciones (necesario para despliegues remotos):

```bash
make install-ansible
```

## Desarrollo local

Para ejecutar el proyecto localmente:

1. Clona el repositorio

2. Crea un archivo de entorno local

   ```bash
   cp .env.example .env.local
   ```

3. Edita `.env.local` con tu configuración local

   ```env
   # Site
   ENVIRONMENT=local
   ARTIFACT_NAME=blog-site
   DOMAIN=localhost
   EMAIL=your-email@example.com

   # DockerHub
   DOCKERHUB_USERNAME=your-dockerhub-username

   # Environment
   TRAEFIK_DASHBOARD=true
   TRAEFIK_INSECURE=true
   ```

4. Inicia el entorno de desarrollo

   ```bash
   make dev
   ```

5. Accede al sitio en <http://localhost>

## Comandos disponibles

El Makefile proporciona una interfaz unificada para todas las operaciones:

### Comandos de desarrollo

```bash
# Iniciar entorno de desarrollo local
make dev

# Limpiar recursos locales
make clean

# Generar configuración de Traefik
make generate-config

# Generar credenciales de autenticación para acceso al dashboard de Traefik
make generate-auth
```

### Configuracion SSH

Primero, asegúrate de tener configurada tu clave SSH para acceder a los servidores remotos. Si no tienes una clave SSH, puedes generarla con el siguiente comando:

```bash
ssh-keygen -t rsa -b 4096 -C "tu-correo@ejemplo.com"
```

Cuando se te pregunte dónde guardar la clave, puedes presionar Enter para aceptar la ubicación predeterminada (`~/.ssh/id_rsa`). También puedes establecer una frase de contraseña para mayor seguridad.
Esto generará dos archivos: `id_rsa` (clave privada) y `id_rsa.pub` (clave pública).
Asegúrate de que el agente SSH esté en ejecución y agrega tu clave privada:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_rsa
```

Si no tienes el agente SSH en ejecución, puedes iniciarlo con el comando anterior. Luego, agrega tu clave privada al agente SSH:

```bash
ssh-add ~/.ssh/id_rsa
```

Si ya tienes una clave SSH, asegúrate de que esté en el directorio `~/.ssh/` y que tenga los permisos correctos:

```bash
chmod 600 ~/.ssh/id_rsa
chmod 644 ~/.ssh/id_rsa.pub
```

Asegúrate de que el archivo `~/.ssh/config` tenga la siguiente configuración:

```bash
Host servidor-remoto
    HostName ip-del-servidor
    User usuario
    IdentityFile ~/.ssh/id_rsa
```

Esto te permitirá conectarte al servidor remoto usando el alias `servidor-remoto` en lugar de la dirección IP completa.
Asegúrate de que el archivo `~/.ssh/config` tenga los permisos correctos:

```bash
chmod 644 ~/.ssh/config
```

Si no tienes el archivo `~/.ssh/config`, puedes crearlo con el siguiente comando:

```bash
touch ~/.ssh/config
```

Luego, edítalo con tu editor de texto favorito y agrega la configuración anterior.
Asegúrate de que el archivo `~/.ssh/config` tenga los permisos correctos:

```bash
chmod 644 ~/.ssh/config
```

Si el servidor remoto no tiene tu clave pública SSH, puedes copiarla manualmente o usar el siguiente comando para agregarla automáticamente:

```bash
ssh-copy-id usuario@servidor-remoto
```

Este comando te pedirá la contraseña del usuario en el servidor remoto. Una vez ingresada, se copiará tu clave pública al servidor remoto y se agregará al archivo `~/.ssh/authorized_keys`, permitiéndote conectarte sin necesidad de ingresar una contraseña.

Asegúrate de que tu usuario tenga permisos para ejecutar comandos de Docker y Ansible así como permisos de sudo.

```bash
sudo usermod -aG sudo $USER
```

### Comandos de despliegue

```bash
# Verificar requisitos previos
make check

# Configuración inicial del entorno (staging o production)
make setup ENV=staging

# Desplegar aplicación (staging o production)
make deploy ENV=production

# Actualizar aplicación sin reiniciar servicios
make update ENV=staging

# Rollback al despliegue anterior
make rollback ENV=production

# Ver logs de la aplicación
make logs ENV=staging

# Ver estado de los servicios
make status ENV=production
```

Cuando se despliega en staging los certificados generados por Let's Encrypt son temporales y los navegadores pueden mostrar advertencias de seguridad. Para poder testar localmente el entorno de staging sin advertencias,  tienes que copiar los certificados generados a tu máquina local y añadirlos a tu almacén de certificados de confianza.

```bash
make copy-certificates ENV=staging
```

Por defecto ningún navegador acepta certificados autofirmados pero puedes añadirlos a tu almacén de certificados de confianza. En sistemas basados en Unix, como Ubuntu, puedes hacer lo siguiente:

```bash
google-chrome --ignore-certificate-errors --user-data-dir=/tmp/chrome-test
```

## Despliegue

Antes de desplegar a staging o producción, asegúrate de tener configurados los archivos de entorno necesarios y tener acceso a tu servidor.

### Configuración inicial del servidor

Para preparar un servidor nuevo:

```bash
make setup ENV=staging
```

Este comando:

- Actualiza los paquetes del sistema
- Instala Docker y Docker Compose
- Configura el firewall
- Crea la estructura de directorios necesaria
- Configura la red de Docker

### Despliegue a entornos remotos

Para desplegar la aplicación:

```bash
make deploy ENV=production
```

Este comando:

- Crea un respaldo de la configuración actual
- Copia todos los archivos necesarios al servidor
- Genera la configuración de Traefik
- Inicia los contenedores de Docker
- Verifica que el despliegue se haya completado correctamente

### Actualización de la aplicación

Para actualizar la aplicación sin una reconstrucción completa:

```bash
make update ENV=staging
```

### Rollback

Si necesitas volver a una versión anterior:

```bash
make rollback ENV=production
```

Este comando restaura la configuración desde el último respaldo disponible.

## Monitoreo

Para verificar el estado de los servicios:

```bash
make status ENV=production
```

Para ver los logs de la aplicación:

```bash
make logs ENV=staging
```

## CI/CD Pipeline

El proyecto incluye un workflow de GitHub Actions que:

1. Construye el sitio Jekyll
2. Crea una imagen Docker
3. Sube la imagen a DockerHub
4. Crea artefactos de despliegue
5. Genera una nueva versión

El workflow se activa por:

- Push a la rama `master`
- Diariamente a medianoche `(cron: '0 0 * * *')`
- Ejecución manual via workflow_dispatch

### Versionado

El proyecto sigue el Versionado Semántico a través de mensajes de commit:

- **Versión Mayor** incrementa con cambios incompatibles:
  - Mensajes conteniendo "BREAKING CHANGE:" o "!:"
  - Ejemplo: `feat!: descripción de cambio incompatible`

- **Versión Menor** incrementa con nuevas características:
  - Mensajes comenzando con `feat:`
  - Ejemplo: `feat: agregar nueva funcionalidad de búsqueda`

- **Versión Parche** incrementa con correcciones/cambios pequeños:
  - Mensajes comenzando con `fix:`, `docs:`, `chore:`, `style:`, etc.
  - Ejemplo: `fix: corregir error en formulario de contacto`

Ver [CONTRIBUTING.md](CONTRIBUTING.md) para más detalles sobre convenciones de mensajes de commit y versionado.

## Solución de problemas

Si encuentras problemas con el despliegue:

1. Verifica los requisitos previos:

   ```bash
   make check
   ```

2. Revisa el estado de los contenedores:

   ```bash
   make status ENV=staging
   ```

3. Verifica los logs:

   ```bash
   make logs ENV=production
   ```

4. Limpia los recursos locales y vuelve a intentar:

   ```bash
   make clean
   make dev
   ```

5. Si es necesario, realiza un rollback a la versión anterior:

   ```bash
   make rollback ENV=production
   ```

## Ejemplos de uso

### Desarrollo completo en local

```bash
# Instalar dependencias
make install-deps

# Iniciar entorno de desarrollo
make dev

# Realizar cambios en los archivos del proyecto...

# Ver los cambios en http://localhost

# Limpiar recursos cuando termines
make clean
```

### Despliegue a producción

```bash
# Verificar requisitos previos
make check

# Configuración inicial (solo la primera vez)
make setup ENV=production

# Desplegar la aplicación
make deploy ENV=production

# Verificar estado
make status ENV=production

# Ver logs
make logs ENV=production
```

### Actualización y rollback

```bash
# Actualizar aplicación
make update ENV=staging

# Si hay problemas, hacer rollback
make rollback ENV=staging
```

## Licencia

Este proyecto está licenciado bajo la Licencia MIT - ver [LICENSE](LICENSE) para más detalles.