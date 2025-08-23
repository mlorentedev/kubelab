# 📚 Wiki - Índice de Documentación

## 🔍 Búsqueda Rápida por Categorías

| Categoría | Documento | Descripción | Tiempo de lectura |
|-----------|-----------|-------------|------------------|
| 🚀 **Inicio Rápido** | [README.md](../README.md) | Puesta en marcha y comandos básicos | 5 min |
| ⚡ **Referencia Rápida** | [HOW-TO.md](HOW-TO.md) | Comandos y tareas comunes | 2 min |
| 🏗️ **Arquitectura** | [ADR.md](ADR.md) | Decisiones arquitecturales (10 ADRs) | 15 min |
| 📋 **Versionado** | [VERSIONING.md](VERSIONING.md) | Estrategia de versionado por ramas | 10 min |
| 🐛 **Resolución Problemas** | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Debug y solución de problemas | 20 min |
| 🚀 **Despliegue Avanzado** | [DEPLOYMENT.md](DEPLOYMENT.md) | Configuración servidores y despliegues | 30 min |
| ⚙️ **Internos CI/CD** | [CI-CD.md](CI-CD.md) | Funcionamiento interno workflows | 25 min |
| 👥 **Contribución** | [CONTRIBUTING.md](CONTRIBUTING.md) | Guías de desarrollo y código | 20 min |

---

## 🎯 Búsqueda por Necesidad

### 🆘 "Tengo un problema"

| Problema | Ve directamente a | Solución rápida |
|----------|------------------|-----------------|
| La app no arranca | [TROUBLESHOOTING → Docker](TROUBLESHOOTING.md#docker-y-docker-compose) | `make down && make up` |
| Dominios locales no funcionan | [HOW-TO → DNS](HOW-TO.md#-dns-y-dominios) | Añadir a `/etc/hosts` |
| CI/CD falló | [HOW-TO → CI/CD](HOW-TO.md#-cicd) | `gh run view <run-id> --log` |
| Deploy no funciona | [TROUBLESHOOTING → Deploy](TROUBLESHOOTING.md#problemas-de-despliegue) | Verificar SSH y permisos |
| Certificados SSL errores | [HOW-TO → DNS](HOW-TO.md#-dns-y-dominios) | `curl -vvI https://domain.com` |
| Contenedor no arranca | [HOW-TO → Docker](HOW-TO.md#-docker) | `docker logs container_name` |

### 🚀 "Quiero hacer algo"

| Tarea | Documento | Comando |
|-------|-----------|---------|
| Setup inicial completo | [README → Puesta en marcha](../README.md#puesta-en-marcha-rápida) | `make env-setup && make up` |
| Desplegar a producción | [HOW-TO → Despliegue](HOW-TO.md#-despliegue) | `make deploy ENV=production` |
| Ver logs de una app | [HOW-TO → Debugging](HOW-TO.md#-debugging) | `make logs APP=api` |
| Rollback urgente | [HOW-TO → Despliegue](HOW-TO.md#-despliegue) | `make emergency-rollback ENV=production` |
| Añadir nueva app | [CI-CD → Añadir apps](CI-CD.md#añadir-nuevas-apps-al-pipeline) | Seguir 4 pasos documentados |
| Configurar servidor nuevo | [DEPLOYMENT → Setup](DEPLOYMENT.md#configuración-inicial-del-servidor) | `make setup ENV=production` |

### 🎓 "Quiero entender cómo funciona"

| Aspecto | Documento | Sección clave |
|---------|-----------|---------------|
| Arquitectura general | [ADR → Visión general](ADR.md#índice-de-decisiones) | 10 decisiones fundamentales |
| Versionado de imágenes | [VERSIONING → Estrategias](VERSIONING.md#estrategia-de-versionado-por-rama) | Patrones por rama |
| Pipeline CI/CD | [CI-CD → Arquitectura](CI-CD.md#arquitectura-de-workflows) | Diagramas y flujos |
| Configuración Docker | [ADR-002](ADR.md#adr-002-docker-containerization) | Decisión containerización |
| Por qué Traefik | [ADR-003](ADR.md#adr-003-traefik-reverse-proxy) | Comparativa vs Nginx |
| Por qué Ansible | [ADR-007](ADR.md#adr-007-ansible-para-despliegues) | Vs otras herramientas |

### 👥 "Quiero contribuir"

| Tarea | Documento | Tiempo necesario |
|-------|-----------|------------------|
| Setup entorno desarrollo | [CONTRIBUTING → Desarrollo](CONTRIBUTING.md#guías-de-codificación) | 10 min |
| Entender convenciones código | [CONTRIBUTING → Convenciones](CONTRIBUTING.md#convenciones-de-código) | 15 min |
| Crear nueva feature | [CONTRIBUTING → Pull Request](CONTRIBUTING.md#proceso-de-pull-request) | Proceso completo |
| Escribir tests | [CONTRIBUTING → Pruebas](CONTRIBUTING.md#pruebas) | Ejemplos por lenguaje |
| Modificar CI/CD | [CI-CD → Añadir apps](CI-CD.md#añadir-nuevas-apps-al-pipeline) | 4 pasos documentados |

---

## 📖 Mapa de Lectura por Roles

### 👩‍💻 **Desarrollador Frontend (Web)**

1. [README.md](../README.md) - Setup básico
2. [CONTRIBUTING.md](CONTRIBUTING.md) - Convenciones JavaScript/TypeScript
3. [HOW-TO.md](HOW-TO.md) - Comandos diarios
4. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Problemas comunes web

**Stack**: Astro, Node.js 20, npm 10

### 🔧 **Desarrollador Backend (API)**

1. [README.md](../README.md) - Setup básico
2. [CONTRIBUTING.md](CONTRIBUTING.md) - Convenciones Go
3. [HOW-TO.md](HOW-TO.md) - Debugging contenedores
4. [CI-CD.md](CI-CD.md) - Pipeline builds

**Stack**: Go 21, Docker, API REST

### 📝 **Content Creator (Blog)**

1. [README.md](../README.md) - Levantar blog local
2. [CONTRIBUTING.md](CONTRIBUTING.md) - Convenciones Ruby/Jekyll
3. [HOW-TO.md](HOW-TO.md) - Comandos blog
4. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Problemas Jekyll

**Stack**: Jekyll, Ruby 3.3, Markdown

### 🔧 **DevOps/SRE**

1. [ADR.md](ADR.md) - Entender decisiones arquitecturales
2. [CI-CD.md](CI-CD.md) - Funcionamiento completo pipeline
3. [DEPLOYMENT.md](DEPLOYMENT.md) - Configuración servidores
4. [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Debug producción
5. [VERSIONING.md](VERSIONING.md) - Gestión releases

**Stack**: Docker, Ansible, Traefik, GitHub Actions

### 🎯 **Product Owner/Manager**

1. [README.md](../README.md) - Visión general del proyecto
2. [ADR.md](ADR.md) - Decisiones de negocio y técnicas
3. [VERSIONING.md](VERSIONING.md) - Estrategia de releases
4. [DEPLOYMENT.md](DEPLOYMENT.md) - Capacidades de despliegue

**Foco**: Strategy, releases, capabilities, trade-offs

---

## 🔗 Enlaces Cruzados por Conceptos

### Docker & Contenedores

- [ADR-002: Containerización](ADR.md#adr-002-docker-containerization) - Por qué Docker
- [HOW-TO: Docker](HOW-TO.md#-docker) - Comandos útiles
- [TROUBLESHOOTING: Docker](TROUBLESHOOTING.md#docker-y-docker-compose) - Problemas comunes
- [CONTRIBUTING: Docker](CONTRIBUTING.md#docker-y-contenedores) - Mejores prácticas

### CI/CD & GitHub Actions

- [ADR-004: GitHub Actions](ADR.md#adr-004-github-actions-para-cicd) - Decisión original
- [CI-CD: Internos](CI-CD.md) - Funcionamiento completo (1,388 líneas)
- [HOW-TO: CI/CD](HOW-TO.md#-cicd) - Comandos rápidos
- [TROUBLESHOOTING: CI/CD](TROUBLESHOOTING.md#problemas-de-cicd) - Debug workflows

### Versionado & Releases

- [ADR-009: Semantic Versioning](ADR.md#adr-009-versionado-semántico-automático) - Estrategia
- [VERSIONING: Completo](VERSIONING.md) - Patrones por rama
- [CI-CD: Version Calculation](CI-CD.md#cálculo-complejo-de-versión-390-líneas) - Implementación
- [HOW-TO: Debug Versioning](HOW-TO.md#debug-version-calculation) - Comandos debug

### Despliegue & Operaciones  

- [ADR-006: CD Manual](ADR.md#adr-006-estrategia-de-cd-manual) - Por qué manual
- [ADR-007: Ansible](ADR.md#adr-007-ansible-para-despliegues) - Herramienta elegida
- [DEPLOYMENT: Avanzado](DEPLOYMENT.md) - Configuración completa servidores
- [HOW-TO: Deploy](HOW-TO.md#-despliegue) - Comandos rápidos
- [TROUBLESHOOTING: Deploy](TROUBLESHOOTING.md#problemas-de-despliegue) - Problemas comunes

### Networking & DNS

- [ADR-003: Traefik](ADR.md#adr-003-traefik-reverse-proxy) - Por qué Traefik vs Nginx
- [HOW-TO: DNS](HOW-TO.md#-dns-y-dominios) - Comandos útiles
- [TROUBLESHOOTING: DNS](TROUBLESHOOTING.md#problemas-de-dns-y-conectividad) - Debug DNS
- [DEPLOYMENT: Network](DEPLOYMENT.md#configuración-de-red) - Puertos y firewall

---

## 🎯 Escenarios de Uso Comunes

### Scenario 1: "Nuevo desarrollador se une al equipo"

**Ruta de lectura**: ⏱️ ~30 minutos
1. [README.md](../README.md) - Entender el proyecto (5 min)
2. [ADR.md](ADR.md) - Por qué tomamos estas decisiones (10 min)  
3. [CONTRIBUTING.md](CONTRIBUTING.md) - Cómo trabajamos (10 min)
4. [HOW-TO.md](HOW-TO.md) - Comandos básicos (5 min)

**Setup práctico**:
```bash
git clone <repo>
make env-setup
make up
# Leer HOW-TO para comandos diarios
```

### Scenario 2: "Problema en producción, debug urgente"

**Ruta de diagnóstico**: ⏱️ ~5 minutos  
1. [HOW-TO: Debugging](HOW-TO.md#-debugging) - Comandos básicos
2. [TROUBLESHOOTING](TROUBLESHOOTING.md) - Problemas específicos
3. Si necesario: [DEPLOYMENT](DEPLOYMENT.md) - Config servidores

**Comandos inmediatos**:
```bash
make status ENV=production
make logs ENV=production
curl -f https://mlorente.dev/health
```

### Scenario 3: "Quiero añadir nueva funcionalidad"

**Proceso completo**: ⏱️ ~45 minutos
1. [CONTRIBUTING: Pull Request](CONTRIBUTING.md#proceso-de-pull-request) - Proceso (10 min)
2. [CONTRIBUTING: Convenciones](CONTRIBUTING.md#convenciones-de-código) - Código (15 min)
3. [HOW-TO: CI/CD](HOW-TO.md#-cicd) - Testing (10 min)
4. [CI-CD: Workflows](CI-CD.md) - Si toca CI/CD (10 min)

### Scenario 4: "Setup servidor nuevo"

**Proceso completo**: ⏱️ ~2 horas
1. [DEPLOYMENT: Requisitos](DEPLOYMENT.md#requisitos-del-servidor) - Hardware/OS (10 min)
2. [DEPLOYMENT: Setup Inicial](DEPLOYMENT.md#configuración-inicial-del-servidor) - Usuario/SSH (20 min)
3. [DEPLOYMENT: Configuración](DEPLOYMENT.md#configuraciones-específicas-por-entorno) - Env específico (30 min)
4. [HOW-TO: Deploy](HOW-TO.md#-despliegue) - Primer deploy (20 min)
5. [DEPLOYMENT: Monitoring](DEPLOYMENT.md#monitorización-y-verificaciones-de-salud) - Setup monitoring (20 min)

---

## 📊 Estadísticas de Documentación

| Métrica | Valor | Notas |
|---------|-------|-------|
| **Documentos totales** | 8 | + README principal |
| **Líneas de doc** | ~4,500 | Incluyendo ejemplos de código |
| **ADRs documentados** | 10 | Decisiones arquitecturales |
| **How-Tos cubiertos** | 47 | Tareas comunes |
| **Tiempo lectura total** | ~2 horas | Para leer todo |
| **Tiempo setup nuevo dev** | 30 min | Solo docs esenciales |
| **Cobertura troubleshooting** | ~95% | Problemas conocidos |

---

## 🔍 Índice de Búsqueda por Palabras Clave

### A-C
- **Ansible**: [ADR-007](ADR.md#adr-007-ansible-para-despliegues), [DEPLOYMENT](DEPLOYMENT.md)
- **API**: [CONTRIBUTING: Go](CONTRIBUTING.md#para-go-api), [HOW-TO: Debug](HOW-TO.md#-debugging)
- **Architecture**: [ADR.md](ADR.md), [README: Estructura](../README.md#estructura-del-repositorio)
- **Backup**: [DEPLOYMENT: Backup](DEPLOYMENT.md#copias-de-seguridad-y-recuperación-ante-desastres)
- **Blog**: [CONTRIBUTING: Ruby](CONTRIBUTING.md#para-ruby-blog-jekyll), [TROUBLESHOOTING: Jekyll](TROUBLESHOOTING.md#blog-jekyll)
- **CI/CD**: [CI-CD.md](CI-CD.md), [ADR-004](ADR.md#adr-004-github-actions-para-cicd)
- **Containers**: [ADR-002](ADR.md#adr-002-docker-containerization), [HOW-TO: Docker](HOW-TO.md#-docker)

### D-M
- **Deployment**: [DEPLOYMENT.md](DEPLOYMENT.md), [HOW-TO: Deploy](HOW-TO.md#-despliegue)
- **DNS**: [HOW-TO: DNS](HOW-TO.md#-dns-y-dominios), [TROUBLESHOOTING: DNS](TROUBLESHOOTING.md#problemas-de-dns-y-conectividad)
- **Docker**: [HOW-TO: Docker](HOW-TO.md#-docker), [TROUBLESHOOTING: Docker](TROUBLESHOOTING.md#docker-y-docker-compose)
- **Environment**: [HOW-TO: Variables](HOW-TO.md#-secretos-y-variables)
- **GitHub Actions**: [CI-CD.md](CI-CD.md), [ADR-004](ADR.md#adr-004-github-actions-para-cicd)
- **Makefile**: [ADR-010](ADR.md#adr-010-makefile-como-interfaz-unificada), [README: Comandos](../README.md#referencia-de-comandos-makefile)
- **Monitoring**: [HOW-TO: Monitoring](HOW-TO.md#-monitorización), [DEPLOYMENT: Monitoring](DEPLOYMENT.md#monitorización-y-verificaciones-de-salud)

### N-Z
- **Production**: [DEPLOYMENT: Production](DEPLOYMENT.md#entorno-de-producción), [TROUBLESHOOTING: Production](TROUBLESHOOTING.md#problemas-específicos-de-producción)
- **Rollback**: [HOW-TO: Rollback](HOW-TO.md#rollback-de-emergencia), [DEPLOYMENT: Rollback](DEPLOYMENT.md#procedimientos-de-rollback)
- **Security**: [CONTRIBUTING: Security](CONTRIBUTING.md#seguridad), [DEPLOYMENT: Security](DEPLOYMENT.md#endurecimiento-de-seguridad)
- **SSL/TLS**: [HOW-TO: DNS](HOW-TO.md#verificar-certificados-ssl), [TROUBLESHOOTING: SSL](TROUBLESHOOTING.md#ssltls-errors)
- **Staging**: [DEPLOYMENT: Staging](DEPLOYMENT.md#entorno-de-staging)
- **Testing**: [CONTRIBUTING: Tests](CONTRIBUTING.md#pruebas)
- **Traefik**: [ADR-003](ADR.md#adr-003-traefik-reverse-proxy), [TROUBLESHOOTING: Traefik](TROUBLESHOOTING.md#problemas-de-traefik)
- **Troubleshooting**: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)
- **Versioning**: [VERSIONING.md](VERSIONING.md), [ADR-009](ADR.md#adr-009-versionado-semántico-automático)

---

## 🎯 Accesos Rápidos

### 🆘 Emergencias
- [Rollback producción](HOW-TO.md#rollback-de-emergencia) - `make emergency-rollback ENV=production`
- [Debug contenedores](HOW-TO.md#ver-logs-de-una-app-específica) - `docker logs container_name -f`  
- [Verificar estado producción](HOW-TO.md#verificar-estado-del-despliegue) - `make status ENV=production`

### ⚡ Comandos Diarios  
- [Setup local](../README.md#puesta-en-marcha-rápida) - `make up`
- [Ver logs](HOW-TO.md#ver-logs-de-una-app-específica) - `make logs`
- [Deploy staging](HOW-TO.md#desplegar-nueva-versión-a-staging) - `make deploy ENV=staging`

### 📚 Referencias
- [Conventional Commits](CONTRIBUTING.md#mensajes-de-commit-según-conventional-commits)
- [Docker best practices](CONTRIBUTING.md#mejores-prácticas-para-dockerfile)
- [Semantic Versioning](ADR.md#adr-009-versionado-semántico-automático)

---

*💡 **Tip**: Guarda esta página como bookmark. Es tu punto de entrada a toda la documentación del proyecto. Utiliza Ctrl+F para buscar rápidamente conceptos específicos.*