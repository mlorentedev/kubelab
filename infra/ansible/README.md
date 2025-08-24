# Ansible - Automatización de Despliegue

Herramientas de automatización y orquestación para el despliegue de aplicaciones en entornos de producción usando Ansible.

## 🏗️ Arquitectura

- **Herramienta**: Ansible 2.9+
- **Inventario**: Dinámico con variables por entorno
- **Playbooks**: Despliegue automatizado de aplicaciones Docker
- **Gestión de Configuración**: Variables centralizadas y plantillas
- **Backup Automático**: Respaldo antes de cada despliegue

## 📁 Estructura del Proyecto

```
infra/ansible/
├── README.md                    # Esta documentación
├── inventories/                 # Configuración de inventarios
│   ├── hosts.yml               # Definición de hosts y grupos
│   └── group_vars/             # Variables por grupos
│       └── all.yml             # Variables globales
├── playbooks/                   # Playbooks de Ansible
│   ├── deploy.yml              # Despliegue principal de aplicaciones
│   └── setup.yml               # Configuración inicial del servidor
└── templates/                   # Plantillas de configuración
    ├── hosts.template.yml       # Plantilla para hosts
    └── group_vars/
        └── all.template.yml     # Plantilla para variables
```

## 🚀 Características

### Despliegue Automatizado

- **Multi-aplicación**: Despliega todas las aplicaciones del stack
- **Gestión de Servicios**: Control de Docker Compose por aplicación
- **Networking**: Configuración automática de redes Docker
- **Health Checks**: Verificación de salud post-despliegue
- **Rollback**: Capacidades de rollback en caso de fallo

### Gestión de Configuración

- **Variables Centralizadas**: Configuración unificada por entorno
- **Plantillas Dinámicas**: Generación de archivos de configuración
- **Secretos**: Gestión segura de credenciales y API keys
- **Multi-entorno**: Soporte para desarrollo, staging y producción
- **Inventario Dinámico**: Configuración flexible de hosts

### Backup y Seguridad

- **Backup Automático**: Respaldo antes de cada despliegue
- **Timestamping**: Versionado con marcas de tiempo únicas
- **Validación**: Verificación de configuraciones antes del despliegue
- **Logs Detallados**: Registro completo de operaciones
- **Recuperación**: Procedimientos de restauración documentados

## 🔧 Configuración

### Variables de Entorno

Configura las variables en `group_vars/all.yml`:

```yaml
# Configuración del Dominio
domain: tudominio.com
subdomain_prefix: ""

# Rutas de Despliegue
deploy_path: /opt/apps
traefik_path: /opt/traefik

# Configuración de Aplicaciones
apps_to_deploy:
  - api
  - blog
  - web
  - n8n
  - monitoring
  - portainer

# Configuración Docker
docker_network: proxy
registry_url: docker.io
image_prefix: tuorganizacion

# Configuración de Backup
backup_retention_days: 30
backup_path: /opt/backups

# Health Check Configuration
health_check_timeout: 30
health_check_retries: 3
```

### Inventario de Hosts

Configura tus servidores en `inventories/hosts.yml`:

```yaml
all:
  children:
    production:
      hosts:
        prod-server:
          ansible_host: 192.168.1.100
          ansible_user: deploy
          ansible_ssh_private_key_file: ~/.ssh/id_rsa_deploy
          domain: mlorente.dev
          deploy_path: /opt/mlorente-prod
      vars:
        env: production
        ssl_enabled: true
        
    development:
      hosts:
        dev-server:
          ansible_host: 192.168.1.101
          ansible_user: develop
          domain: dev.mlorente.dev
          deploy_path: /opt/mlorente-dev
      vars:
        env: development
        ssl_enabled: false

    staging:
      hosts:
        stage-server:
          ansible_host: 192.168.1.102
          ansible_user: deploy
          domain: staging.mlorente.dev
          deploy_path: /opt/mlorente-stage
      vars:
        env: staging
        ssl_enabled: true
```

## 🚀 Playbooks

### Playbook de Despliegue (deploy.yml)

Funcionalidades principales:

- **Backup Automático**: Crea respaldo con timestamp único
- **Configuración Traefik**: Despliega proxy reverso y SSL
- **Despliegue de Apps**: Orquesta el despliegue de todas las aplicaciones
- **Health Checks**: Verifica que los servicios estén funcionando
- **Red Docker**: Configura networking entre servicios

### Playbook de Setup (setup.yml)

Configuración inicial del servidor:

- **Dependencias del Sistema**: Instala Docker y herramientas
- **Usuarios y Permisos**: Configura usuarios de despliegue
- **Firewall**: Configuración de seguridad básica
- **Directorios**: Crea estructura de directorios
- **Servicios Base**: Configura servicios del sistema

## 🛠️ Uso

### Configuración Inicial

```bash
# Clonar configuraciones desde plantillas
cp templates/hosts.template.yml inventories/hosts.yml
cp templates/group_vars/all.template.yml inventories/group_vars/all.yml

# Editar configuración de hosts
nano inventories/hosts.yml

# Editar variables globales
nano inventories/group_vars/all.yml
```

### Setup Inicial del Servidor

```bash
# Preparar servidor para primera vez
ansible-playbook -i inventories/hosts.yml playbooks/setup.yml --limit production

# Verificar conectividad
ansible -i inventories/hosts.yml production -m ping

# Verificar variables
ansible-playbook -i inventories/hosts.yml playbooks/setup.yml --limit production --check
```

### Despliegue de Aplicaciones

```bash
# Despliegue completo en producción
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit production

# Despliegue en desarrollo
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit development

# Despliegue con verificaciones adicionales
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit production --check --diff

# Despliegue verbose para debugging
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit production -vvv
```

### Comandos de Mantenimiento

```bash
# Verificar estado de servicios
ansible -i inventories/hosts.yml production -a "docker ps" --become

# Reiniciar servicios específicos
ansible -i inventories/hosts.yml production -a "docker compose -f /opt/apps/api/docker-compose.yml restart" --become

# Verificar logs
ansible -i inventories/hosts.yml production -a "docker logs traefik" --become

# Limpiar imágenes no utilizadas
ansible -i inventories/hosts.yml production -a "docker system prune -f" --become
```

## 🔍 Monitoreo y Troubleshooting

### Verificación de Estado

```bash
# Estado de contenedores
ansible -i inventories/hosts.yml production -m shell -a "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" --become

# Verificar red proxy
ansible -i inventories/hosts.yml production -m shell -a "docker network inspect proxy" --become

# Verificar servicios de sistema
ansible -i inventories/hosts.yml production -m service -a "name=docker state=started" --become
```

### Logs y Debugging

```bash
# Ver logs de Ansible en tiempo real
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit production -vvv

# Verificar configuración sin ejecutar
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --limit production --check --diff

# Ver variables de host específico
ansible-inventory -i inventories/hosts.yml --host prod-server --yaml
```

### Troubleshooting Común

```bash
# Problema: No se puede conectar al host
ansible -i inventories/hosts.yml production -m ping
# Solución: Verificar SSH keys y permisos

# Problema: Docker no está instalado
ansible -i inventories/hosts.yml production -m shell -a "docker --version" --become
# Solución: Ejecutar playbook setup.yml

# Problema: Servicios no inician
ansible -i inventories/hosts.yml production -a "docker logs traefik" --become
# Solución: Verificar configuración y variables
```

## 🔐 Seguridad

### Gestión de Secretos

```yaml
# Usar Ansible Vault para secretos
ansible-vault create inventories/group_vars/all_secrets.yml

# Editar secretos
ansible-vault edit inventories/group_vars/all_secrets.yml

# Despliegue con vault
ansible-playbook -i inventories/hosts.yml playbooks/deploy.yml --ask-vault-pass
```

### Configuración SSH

```bash
# Generar clave SSH para despliegue
ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_deploy

# Copiar clave al servidor
ssh-copy-id -i ~/.ssh/id_rsa_deploy.pub deploy@servidor.com

# Configurar SSH en ~/.ssh/config
Host prod-server
    HostName 192.168.1.100
    User deploy
    IdentityFile ~/.ssh/id_rsa_deploy
    StrictHostKeyChecking no
```

### Permisos y Usuarios

```yaml
# En group_vars/all.yml
deploy_user: deploy
deploy_group: deploy
app_permissions: "0755"
config_permissions: "0644"
secret_permissions: "0600"
```

## 📈 Optimización

### Paralelización

```yaml
# En ansible.cfg
[defaults]
forks = 10
host_key_checking = False
timeout = 30
gathering = smart
fact_caching = memory

[ssh_connection]
ssh_args = -o ControlMaster=auto -o ControlPersist=60s
pipelining = True
```

### Caché de Facts

```yaml
# Configuración de caché
fact_caching = jsonfile
fact_caching_connection = /tmp/facts_cache
fact_caching_timeout = 86400
```

### Estrategias de Despliegue

```yaml
# Rolling deployment strategy
strategy: rolling
serial: 1

# Parallel deployment
strategy: free
```

## 🤝 Contribución

1. Fork del repositorio
2. Crear rama de feature
3. Añadir playbooks en `playbooks/`
4. Documentar variables en `group_vars/`
5. Probar en entorno de desarrollo
6. Actualizar documentación
7. Enviar pull request

### Guías de Desarrollo

- Usar variables en lugar de valores hardcoded
- Implementar idempotencia en todas las tareas
- Añadir handlers para servicios que requieren restart
- Documentar todas las variables en `group_vars/`
- Usar tags para ejecución selectiva
- Implementar verificaciones de estado

## 📝 Variables de Configuración

### Variables Obligatorias

```yaml
# Dominio principal
domain: tudominio.com

# Ruta base de despliegue
deploy_path: /opt/apps

# Aplicaciones a desplegar
apps:
  - { name: "api", compose: "docker-compose.prod.yml" }
  - { name: "blog", compose: "docker-compose.prod.yml" }
  - { name: "web", compose: "docker-compose.prod.yml" }
```

### Variables Opcionales

```yaml
# Configuración de backup
backup_retention_days: 30
backup_dir: "{{ deploy_path }}/backups"

# Health checks
health_check_timeout: 30
health_check_urls:
  - "https://{{ domain }}/health"
  - "https://api.{{ domain }}/health"

# Docker configuration
docker_cleanup: true
docker_prune: false
pull_latest: true
```

## 🔗 Servicios Relacionados

- **Traefik**: `infra/traefik` - Proxy reverso y SSL
- **Nginx**: `infra/nginx` - Servidor web estático
- **Apps**: `apps/` - Aplicaciones desplegadas
- **Monitoreo**: `apps/monitoring` - Stack de observabilidad

## 📖 Recursos Adicionales

- [Documentación de Ansible](https://docs.ansible.com/)
- [Best Practices de Ansible](https://docs.ansible.com/ansible/latest/user_guide/playbooks_best_practices.html)
- [Ansible Vault](https://docs.ansible.com/ansible/latest/user_guide/vault.html)
- [Docker Compose con Ansible](https://docs.ansible.com/ansible/latest/collections/community/docker/docker_compose_module.html)