# Scripts y Herramientas del Proyecto

¡Hola! Aquí tienes todos los scripts que me ayudan a mantener este proyecto funcionando sin quebraderos de cabeza. Son mis pequeños ayudantes automatizados que se encargan de las tareas pesadas.

## 🛠️ Lo que encontrarás aquí

### **wiki.sh** - El generador de documentación

Mi script favorito para generar la wiki automáticamente. Recoge todo el contenido markdown del monorepo y lo organiza de forma bonita.

**¿Qué hace?**

- Recopila todos los README y documentos markdown
- Los organiza por secciones (apps, infra, guías)
- Genera índices automáticamente con numeración secuencial
- Crea el sitio estático con MkDocs Material

**Cómo usarlo:**

```bash
# Generar la wiki completa
./scripts/wiki.sh build-all

# Solo una rama específica
./scripts/wiki.sh build-one mi-rama

# Limpiar todo y empezar de cero
./scripts/wiki.sh clean
```

### **utils.sh** - Funciones comunes

El cerebro compartido de todos los demás scripts. Aquí tengo funciones útiles que uso en varios sitios.

**Incluye:**

- Funciones de logging con colores bonitos
- Carga de variables de entorno
- Validaciones comunes
- Utilidades para manejar archivos

### **env-setup.sh** - Configuración inicial

Te prepara todo el entorno de desarrollo de una tacada. Perfecto para cuando empiezas desde cero.

**Instala:**

- Node.js y npm
- Ruby y Bundler para Jekyll
- Go para la API
- Docker y Docker Compose
- Otras herramientas necesarias

```bash
./scripts/env-setup.sh
```

### **generate-traefik-config.sh** - Configuración de Traefik

Genera toda la configuración de Traefik basándose en plantillas. Muy útil cuando añado nuevos servicios.

**Genera:**

- Configuración dinámica
- Certificados SSL
- Rutas y middleware
- Configuración específica por entorno

### **generate-ansible-config.sh** - Configuración de Ansible

Crea los inventarios y configuraciones de Ansible para los despliegues.

**Genera:**

- Inventarios por entorno
- Variables de grupo
- Configuraciones específicas de servidor

### **setup-gh-secrets.sh** - Secretos de GitHub

Sincroniza las variables del archivo `.env` con los secretos de GitHub Actions. Muy cómodo para CI/CD.

```bash
./scripts/setup-gh-secrets.sh production
```

### **create-env-example.sh** - Ejemplos de configuración

Genera archivos `.env.example` basándose en los `.env` reales, pero sin los valores sensibles.

### **generate-traefik-credentials.sh** - Credenciales de Traefik

Genera las credenciales básicas para acceder al dashboard de Traefik de forma segura.

### **replace-placeholders.sh** - Reemplazar placeholders

Utilidad para sustituir placeholders en archivos de configuración. La uso en varios scripts.

## 🚀 Cómo usar los scripts

### Preparar el entorno (primera vez)

```bash
# Instalar todas las herramientas necesarias
./scripts/env-setup.sh

# Generar configuraciones iniciales
./scripts/generate-traefik-config.sh
./scripts/generate-ansible-config.sh
```

### Generar documentación

```bash
# Wiki completa
./scripts/wiki.sh build-all

# Solo una rama específica
./scripts/wiki.sh build-one develop
```

### Configurar CI/CD

```bash
# Subir secretos a GitHub
./scripts/setup-gh-secrets.sh production

# Crear archivos de ejemplo
./scripts/create-env-example.sh
```

## 💡 Tips y trucos

**Para desarrolladores:**

- Todos los scripts usan `set -euo pipefail` para ser más robustos
- Cargan variables de entorno automáticamente
- Tienen logging con colores para facilitar el debug
- Están documentados internamente con comentarios

**Para usuarios:**

- Si un script falla, revisa que tienes todas las variables de entorno configuradas
- Los logs en colores te ayudan a entender qué está pasando
- Puedes ejecutar `./script.sh --help` en la mayoría para ver opciones

## 🔧 Dependencias

La mayoría de scripts necesitan:

- **zsh** - Shell por defecto
- **Docker** y **Docker Compose**
- **jq** - Para procesar JSON
- **gh CLI** - Para interactuar con GitHub (opcional)

## 📝 Notas importantes

- **Siempre revisa las variables de entorno** antes de ejecutar scripts
- **Los scripts modifican archivos** - haz backup si es crítico
- **Algunos requieren permisos** de administrador para instalar paquetes
- **Están optimizados para Ubuntu/Debian** pero deberían funcionar en otras distribuciones

---

> **Pro tip:** Si vas a modificar algún script, échale un vistazo a `utils.sh` primero. Probablemente ya tengo una función que hace lo que necesitas.
