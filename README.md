# mlorente.dev

Web personal construida con Jekyll, contenerizada con Docker y desplegada utilizando Traefik para terminación SSL y proxy inverso.

## Características

- **Sitio web estático**: Construido con Jekyll para rendimiento óptimo
- **Diseño responsive**: Adaptado para todos los dispositivos
- **Contenerización completa**: Docker y Docker Compose para desarrollo y producción
- **CI/CD automatizado**: GitHub Actions para builds, tests y despliegue
- **SSL automático**: Certificados Let's Encrypt gestionados por Traefik
- **Infraestructura como código**: Configuración automatizada con Ansible
- **Multi-ambiente**: Soporte para local, staging y producción
- **Seguridad integrada**: Escaneo de secretos y vulnerabilidades
- **Monitoreo**: Dashboard de Traefik con autenticación

## Estructura del proyecto

```text
├── .github/workflows/          # Pipelines de CI/CD
│   ├─ ci-jekyll.yml             # CI del sitio estático
|   ├─ ci-frontend.yml           # CI del frontend
|   ├─ ci-backend.yml            # CI del backend
|   ├─ test-build-push.yml       # Job reutilizable de CI
|   ├─ deploy.yml                # Job reutilizable de CD
|   ├─ cd.yml                    # Despliegue auto staging/producción
|   └─ release.yml               # Release + retag + deploy
├── deployment/                # Configuración de despliegue
│   ├── ansible/                 # Playbooks y configuración
│   │   ├── inventory/              # Inventario de hosts
│   │   ├── playbooks/              # Playbooks de despliegue
│   │   └── templates/              # Plantillas de configuración
│   ├── docker/                  # Configuración Docker
│   └── traefik/                 # Configuración de proxy
├── src/                 # Servicios de la aplicación
│   ├── backend/                 # Servicio backend (futuro)
│   ├── frontend/                # Servicio frontend (futuro)
│   └── jekyll/                  # Sitio Jekyll estático
├── scripts/                  # Scripts de automatización
├── docs/                     # Documentación adicional
├── .env.example              # Plantilla de variables de entorno
└── Makefile                  # Comandos de automatización
```

## Prerrequisitos

- **Docker** y **Docker Compose** (v2.0+)
- **Git**
- **Make**
- **Ansible** (opcional, para despliegues remotos)
- **Cuenta DockerHub** para almacenar imágenes
- **Dominio** (para staging y producción)
- **Servidor con SSH** (para despliegues remotos)

## Instalación

### Dependencias del sistema

```bash
# Instalar todas las dependencias necesarias
make install-deps

# Instalar Ansible y colecciones (para despliegues remotos)
make install-ansible
```

### Configuración del entorno en local

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
   # Iniciar entorno de desarrollo
   make dev

   # El sitio estará disponible en:
   # - Sitio web: http://localhost
   # - Dashboard Traefik: http://localhost:8080
   ```

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

## Despliegue remoto

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
make deploy ENV=staging

# Ver logs de la aplicación
make logs ENV=staging

# Ver estado de los servicios
make status ENV=staging
```

Cuando se despliega en staging los certificados generados por Let's Encrypt son temporales y los navegadores pueden mostrar advertencias de seguridad. Para poder testar localmente el entorno de staging sin advertencias,  tienes que copiar los certificados generados a tu máquina local y añadirlos a tu almacén de certificados de confianza.

```bash
make copy-certificates ENV=staging
```

Por defecto ningún navegador acepta certificados autofirmados pero puedes añadirlos a tu almacén de certificados de confianza. En sistemas basados en Unix, como Ubuntu, puedes hacer lo siguiente:

```bash
google-chrome --ignore-certificate-errors --user-data-dir=/tmp/chrome-test
```

## Configuración del servidor

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

### Despliegue a un entorno de staging o producción

```bash
# Verificar requisitos previos
make check

# Configuración inicial (solo la primera vez)
make setup ENV=staging

# Desplegar la aplicación
make deploy ENV=staging

# Verificar estado
make status ENV=staging

# Ver logs
make logs ENV=staging
```

## CI/CD Pipeline

El proyecto incluye un workflow de GitHub Actions que:

| Etapa | Disparador | Pasos clave | Resultado |
|-------|------------|-------------|-----------|
| **CI de servicio** (`ci-jekyll`, `ci-frontend`, `ci-backend`) | Push / PR a `master`, `develop`, `feature/*`, `hotfix/*` | *Draft‑skip* → Linter → Tests → Gitleaks → **Build** multi‑arquitectura → Push a Docker Hub (etiquetas `version`, `sha`, `branch`) → Aviso Slack | Imagen fresca en Docker Hub |
| **CD automático** (`cd.yml`) | Push a `develop` → *staging*<br>Push a `master` → *production* | Llama a `deploy.yml` → Roles Ansible (Traefik + backups + certs + prune) → Smoke test → Aviso Slack | Contenedores actualizados en el VPS |
| **Release** (`release.yml`) | Push de tag `vX.Y.Z` | Crea Release en GitHub con notas → Comprime infra y la adjunta → Retag/push de imágenes `vX.Y.Z` → Despliegue en *production* con esa tag → Aviso Slack | Release inmutable + producción desplegada |

```text
Commit / PR
    │
    ├─► CI-Static ──┐
    ├─► CI-Frontend ├─► Tests → Buildx → Docker Hub → Slack
    └─► CI-Backend ─┘
                      │
                      ├─► Push a *develop* → Deploy (staging) → Health-check → Slack
                      └─► Push a *master*  → Deploy (production) → Health-check → Slack

Tag vX.Y.Z
    │
    └─► GitHub Release → Zip infra
                        │
                        └─► Retag imágenes (vX.Y.Z) → Deploy (prod vX.Y.Z) → Health-check → Slack
```

### Configuración de secretos de GitHub

El proyecto incluye un script automatizado para configurar todos los secretos necesarios en GitHub Actions desde tus archivos `.env`:

```bash
# Configurar secretos desde .env en el directorio raíz
make setup-secrets

# Configurar secretos desde un archivo específico
make setup-secrets ../tmp/.env.production
```

## Documentación adicional

- [Guía de contribución](docs/CONTRIBUTING.md)
- [Documentación de CubeLab](docs/CUBELAB.md)
- [Workflows de GitHub](.github/workflows/)

## 📄 Licencia

Este proyecto está bajo la Licencia MIT. Ver el archivo [LICENSE](LICENSE) para más detalles.

---

**Autor**: Manuel Lorente  
**Sitio web**: [mlorente.dev](https://mlorente.dev)  
**Email**: <info@mlorente.dev>
