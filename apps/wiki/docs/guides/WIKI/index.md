# 📚 Wiki - Índice de Documentación

## 🔍 Búsqueda Rápida por Categorías

| Categoría | Documento | Descripción | Tiempo de lectura |
|-----------|-----------|-------------|------------------|
| ⚡ **Referencia Rápida** | [HOW-TO](../HOW-TO/index.md) | Comandos y tareas comunes | 2 min |
| 🏗️ **Arquitectura** | [ADR](../ARCHITECTURE-AND-DECISIONS/index.md) | Decisiones arquitecturales (10 ADRs) | 15 min |
| 📋 **Versionado** | [VERSIONING](../VERSIONING/index.md) | Estrategia de versionado por ramas | 10 min |
| 🐛 **Resolución Problemas** | [TROUBLESHOOTING](../TROUBLESHOOTING/index.md) | Debug y solución de problemas | 20 min |
| 🚀 **Despliegue Avanzado** | [DEPLOYMENT](../DEPLOYMENT/index.md) | Configuración servidores y despliegues | 30 min |
| ⚙️ **Internos CI/CD** | [CI-CD](../CI-CD/index.md) | Funcionamiento interno workflows | 25 min |
| 👥 **Contribución** | [CONTRIBUTING](../CONTRIBUTING/index.md) | Guías de desarrollo y código | 20 min |
| 🎯 **CubeLab Project** | [CUBELAB](../CUBELAB/index.md) | Documentación específica del proyecto CubeLab | 10 min |
| 🏛️ **Arquitectura General** | [ARCHITECTURE](../ARCHITECTURE-AND-DECISIONS/index.md) | Visión general del sistema | 15 min |

---

## 🎯 Búsqueda por Necesidad

### 🆘 "Tengo un problema"

| Problema | Ve directamente a | Solución rápida |
|----------|------------------|-----------------|
| La app no arranca | [TROUBLESHOOTING → Docker](../TROUBLESHOOTING/index.md#docker-y-docker-compose) | `make down && make up` |
| Dominios locales no funcionan | [HOW-TO → DNS](../HOW-TO/index.md#-dns-y-dominios) | Añadir a `/etc/hosts` |
| CI/CD falló | [HOW-TO → CI/CD](../HOW-TO/index.md#-cicd) | `gh run view <run-id> --log` |
| Deploy no funciona | [TROUBLESHOOTING → Deploy](../TROUBLESHOOTING/index.md#problemas-de-despliegue) | Verificar SSH y permisos |
| Certificados SSL errores | [HOW-TO → DNS](../HOW-TO/index.md#-dns-y-dominios) | `curl -vvI https://domain.com` |
| Contenedor no arranca | [HOW-TO → Docker](../HOW-TO/index.md#-docker) | `docker logs container_name` |

### 🚀 "Quiero hacer algo"

| Tarea | Documento | Comando |
|-------|-----------|---------|
| Setup inicial completo | [HOW-TO → Setup](../HOW-TO/index.md#setup-inicial) | `make install-precommit-hooks && make up` |
| Desplegar a producción | [HOW-TO → Despliegue](../HOW-TO/index.md#-despliegue) | `make deploy ENV=production` |
| Ver logs de una app | [HOW-TO → Debugging](../HOW-TO/index.md#-debugging) | `make logs APP=api` |
| Rollback urgente | [HOW-TO → Despliegue](../HOW-TO/index.md#-despliegue) | `make emergency-rollback ENV=production` |
| Añadir nueva app | [CI-CD → Añadir apps](../CI-CD/index.md#añadir-nuevas-apps-al-pipeline) | Seguir 4 pasos documentados |
| Configurar servidor nuevo | [DEPLOYMENT → Setup](../DEPLOYMENT/index.md#configuración-inicial-del-servidor) | `make setup ENV=production` |

### 🎓 "Quiero entender cómo funciona"

| Aspecto | Documento | Sección clave |
|---------|-----------|---------------|
| Arquitectura general | [ADR → Visión general](../ARCHITECTURE-AND-DECISIONS/index.md#índice-de-decisiones) | 10 decisiones fundamentales |
| Versionado de imágenes | [VERSIONING → Estrategias](../VERSIONING/index.md#estrategia-de-versionado-por-rama) | Patrones por rama |
| Pipeline CI/CD | [CI-CD → Arquitectura](../CI-CD/index.md#arquitectura-de-workflows) | Diagramas y flujos |
| Configuración Docker | [ADR-002](../ARCHITECTURE-AND-DECISIONS/index.md#adr-002-docker-containerization) | Decisión containerización |
| Por qué Traefik | [ADR-003](../ARCHITECTURE-AND-DECISIONS/index.md#adr-003-traefik-reverse-proxy) | Comparativa vs Nginx |
| Por qué Ansible | [ADR-007](../ARCHITECTURE-AND-DECISIONS/index.md#adr-007-ansible-para-despliegues) | Vs otras herramientas |

### 👥 "Quiero contribuir"

| Tarea | Documento | Tiempo necesario |
|-------|-----------|------------------|
| Setup entorno desarrollo | [CONTRIBUTING → Desarrollo](../CONTRIBUTING/index.md#guías-de-codificación) | 10 min |
| Entender convenciones código | [CONTRIBUTING → Convenciones](../CONTRIBUTING/index.md#convenciones-de-código) | 15 min |
| Crear nueva feature | [CONTRIBUTING → Pull Request](../CONTRIBUTING/index.md#proceso-de-pull-request) | Proceso completo |
| Escribir tests | [CONTRIBUTING → Pruebas](../CONTRIBUTING/index.md#pruebas) | Ejemplos por lenguaje |
| Modificar CI/CD | [CI-CD → Añadir apps](../CI-CD/index.md#añadir-nuevas-apps-al-pipeline) | 4 pasos documentados |

---

## 📖 Mapa de Lectura por Roles

### 👩‍💻 **Desarrollador Frontend (Web)**

1. [HOW-TO](../HOW-TO/index.md) - Setup básico
2. [CONTRIBUTING](../CONTRIBUTING/index.md) - Convenciones JavaScript/TypeScript
3. [HOW-TO](../HOW-TO/index.md) - Comandos diarios
4. [TROUBLESHOOTING](../TROUBLESHOOTING/index.md) - Problemas comunes web

**Stack**: Astro, Node.js 20, npm 10

### 🔧 **Desarrollador Backend (API)**

1. [HOW-TO](../HOW-TO/index.md) - Setup básico
2. [CONTRIBUTING](../CONTRIBUTING/index.md) - Convenciones Go
3. [HOW-TO](../HOW-TO/index.md) - Debugging contenedores
4. [CI-CD](../CI-CD/index.md) - Pipeline builds

**Stack**: Go 21, Docker, API REST

### 📝 **Content Creator (Blog)**

1. [HOW-TO](../HOW-TO/index.md) - Levantar blog local
2. [CONTRIBUTING](../CONTRIBUTING/index.md) - Convenciones Ruby/Jekyll
3. [HOW-TO](../HOW-TO/index.md) - Comandos blog
4. [TROUBLESHOOTING](../TROUBLESHOOTING/index.md) - Problemas Jekyll

**Stack**: Jekyll, Ruby 3.3, Markdown

### 🔧 **DevOps/SRE**

1. [ADR](../ARCHITECTURE-AND-DECISIONS/index.md) - Entender decisiones arquitecturales
2. [CI-CD](../CI-CD/index.md) - Funcionamiento completo pipeline
3. [DEPLOYMENT](../DEPLOYMENT/index.md) - Configuración servidores
4. [TROUBLESHOOTING](../TROUBLESHOOTING/index.md) - Debug producción
5. [VERSIONING](../VERSIONING/index.md) - Gestión releases

**Stack**: Docker, Ansible, Traefik, GitHub Actions

### 🎯 **Product Owner/Manager**

1. [ARCHITECTURE](../ARCHITECTURE-AND-DECISIONS/index.md) - Visión general del proyecto
2. [ADR](../ARCHITECTURE-AND-DECISIONS/index.md) - Decisiones de negocio y técnicas
3. [VERSIONING](../VERSIONING/index.md) - Estrategia de releases
4. [DEPLOYMENT](../DEPLOYMENT/index.md) - Capacidades de despliegue

**Foco**: Strategy, releases, capabilities, trade-offs

---

## 🔗 Enlaces Cruzados por Conceptos

### Docker & Contenedores

- [ADR-002: Containerización](../ARCHITECTURE-AND-DECISIONS/index.md#adr-002-docker-containerization) - Por qué Docker
- [HOW-TO: Docker](../HOW-TO/index.md#-docker) - Comandos útiles
- [TROUBLESHOOTING: Docker](../TROUBLESHOOTING/index.md#docker-y-docker-compose) - Problemas comunes
- [CONTRIBUTING: Docker](../CONTRIBUTING/index.md#docker-y-contenedores) - Mejores prácticas

### CI/CD & GitHub Actions

- [ADR-004: GitHub Actions](../ARCHITECTURE-AND-DECISIONS/index.md#adr-004-github-actions-para-cicd) - Decisión original
- [CI-CD: Internos](../CI-CD/index.md) - Funcionamiento completo (1,388 líneas)
- [HOW-TO: CI/CD](../HOW-TO/index.md#-cicd) - Comandos rápidos
- [TROUBLESHOOTING: CI/CD](../TROUBLESHOOTING/index.md#problemas-de-cicd) - Debug workflows

### Versionado & Releases

- [ADR-009: Semantic Versioning](../ARCHITECTURE-AND-DECISIONS/index.md#adr-009-versionado-semántico-automático) - Estrategia
- [VERSIONING: Completo](../VERSIONING/index.md) - Patrones por rama
- [CI-CD: Version Calculation](../CI-CD/index.md#cálculo-complejo-de-versión-390-líneas) - Implementación
- [HOW-TO: Debug Versioning](../HOW-TO/index.md#debug-version-calculation) - Comandos debug

### Despliegue & Operaciones  

- [ADR-006: CD Manual](../ARCHITECTURE-AND-DECISIONS/index.md#adr-006-estrategia-de-cd-manual) - Por qué manual
- [ADR-007: Ansible](../ARCHITECTURE-AND-DECISIONS/index.md#adr-007-ansible-para-despliegues) - Herramienta elegida
- [DEPLOYMENT: Avanzado](../DEPLOYMENT/index.md) - Configuración completa servidores
- [HOW-TO: Deploy](../HOW-TO/index.md#-despliegue) - Comandos rápidos
- [TROUBLESHOOTING: Deploy](../TROUBLESHOOTING/index.md#problemas-de-despliegue) - Problemas comunes

### Networking & DNS

- [ADR-003: Traefik](../ARCHITECTURE-AND-DECISIONS/index.md#adr-003-traefik-reverse-proxy) - Por qué Traefik vs Nginx
- [HOW-TO: DNS](../HOW-TO/index.md#-dns-y-dominios) - Comandos útiles
- [TROUBLESHOOTING: DNS](../TROUBLESHOOTING/index.md#problemas-de-dns-y-conectividad) - Debug DNS
- [DEPLOYMENT: Network](../DEPLOYMENT/index.md#configuración-de-red) - Puertos y firewall

---

## 🎯 Escenarios de Uso Comunes

### Scenario 1: "Nuevo desarrollador se une al equipo"

**Ruta de lectura**: ⏱️ ~30 minutos

1. [ARCHITECTURE](../ARCHITECTURE-AND-DECISIONS/index.md) - Entender el proyecto (5 min)
2. [ADR](../ARCHITECTURE-AND-DECISIONS/index.md) - Por qué tomamos estas decisiones (10 min)  
3. [CONTRIBUTING](../CONTRIBUTING/index.md) - Cómo trabajamos (10 min)
4. [HOW-TO](../HOW-TO/index.md) - Comandos básicos (5 min)

**Setup práctico**:

```bash
git clone <repo>
make install-precommit-hooks
make up
# Leer HOW-TO para comandos diarios
```

### Scenario 2: "Problema en producción, debug urgente"

**Ruta de diagnóstico**: ⏱️ ~5 minutos  

1. [HOW-TO: Debugging](../HOW-TO/index.md#-debugging) - Comandos básicos
2. [TROUBLESHOOTING](../TROUBLESHOOTING/index.md#problemas-comunes) - Problemas específicos
3. Si necesario: [DEPLOYMENT](../DEPLOYMENT/index.md#configuración-del-servidor) - Config servidores

**Comandos inmediatos**:

```bash
make status ENV=production
make logs ENV=production
curl -f https://mlorente.dev/health
```

### Scenario 3: "Quiero añadir nueva funcionalidad"

**Proceso completo**: ⏱️ ~45 minutos

1. [CONTRIBUTING: Pull Request](../CONTRIBUTING/index.md#proceso-de-pull-request) - Proceso (10 min)
2. [CONTRIBUTING: Convenciones](../CONTRIBUTING/index.md#convenciones-de-código) - Código (15 min)
3. [HOW-TO: CI/CD](../HOW-TO/index.md#-cicd) - Testing (10 min)
4. [CI-CD: Workflows](../CI-CD/index.md#workflows) - Si toca CI/CD (10 min)

### Scenario 4: "Setup servidor nuevo"

**Proceso completo**: ⏱️ ~2 horas

1. [DEPLOYMENT: Requisitos](../DEPLOYMENT/index.md#requisitos-del-servidor) - Hardware/OS (10 min)
2. [DEPLOYMENT: Setup Inicial](../DEPLOYMENT/index.md#configuración-inicial-del-servidor) - Usuario/SSH (20 min)
3. [DEPLOYMENT: Configuración](../DEPLOYMENT/index.md#configuraciones-específicas-por-entorno) - Env específico (30 min)
4. [HOW-TO: Deploy](../HOW-TO/index.md#-despliegue) - Primer deploy (20 min)
5. [DEPLOYMENT: Monitoring](../DEPLOYMENT/index.md#monitorización-y-verificaciones-de-salud) - Setup monitoring (20 min)

---

## 🎯 Accesos Rápidos

### 🆘 Emergencias

- [Rollback producción](../HOW-TO/index.md#rollback-de-emergencia) - `make emergency-rollback ENV=production`
- [Debug contenedores](../HOW-TO/index.md#ver-logs-de-una-app-específica) - `docker logs container_name -f`  
- [Verificar estado producción](../HOW-TO/index.md#verificar-estado-del-despliegue) - `make status ENV=production`

### ⚡ Comandos Diarios  

- [Setup local](../HOW-TO/index.md#setup-inicial) - `make up`
- [Ver logs](../HOW-TO/index.md#ver-logs-de-una-app-específica) - `make logs`
- [Deploy staging](../HOW-TO/index.md#desplegar-nueva-versión-a-staging) - `make deploy ENV=staging`

### 📚 Referencias

- [Conventional Commits](../CONTRIBUTING/index.md#mensajes-de-commit-según-conventional-commits)
- [Docker best practices](../CONTRIBUTING/index.md#mejores-prácticas-para-dockerfile)
- [Semantic Versioning](../ARCHITECTURE-AND-DECISIONS/index.md#adr-009-versionado-semántico-automático)

---

*💡 **Tip**: Guarda esta página como bookmark. Es tu punto de entrada a toda la documentación del proyecto. Utiliza Ctrl+F para buscar rápidamente conceptos específicos.*
