---
title: Infraestructura - mlorente.dev
description: Documentación de la infraestructura, configuraciones y sistemas de despliegue
hide:
  - toc
---

# 🔧 Infraestructura

**Configuraciones, proxies, DNS, despliegues y gestión de la infraestructura completa**

---

## Componentes de Infraestructura

<div class="section-cards">
  <div class="section-card">
    <h3><a href="#traefik"><span class="item-number">2.1</span> Traefik</a></h3>
    <p>Proxy reverso y load balancer con configuración automática.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Proxy</span>
        <span class="card-tag">Load Balancer</span>
        <span class="card-tag">SSL</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="#nginx"><span class="item-number">2.2</span> Nginx</a></h3>
    <p>Servidor web de alta performance para contenido estático.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Web Server</span>
        <span class="card-tag">Static Files</span>
        <span class="card-tag">Cache</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="#ansible"><span class="item-number">2.3</span> Ansible</a></h3>
    <p>Automatización de configuración y despliegue de infraestructura.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Automation</span>
        <span class="card-tag">IaC</span>
        <span class="card-tag">Deployment</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="#docker"><span class="item-number">2.4</span> Docker</a></h3>
    <p>Containerización y orquestación de aplicaciones y servicios.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Containers</span>
        <span class="card-tag">Docker Compose</span>
        <span class="card-tag">Orchestration</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="#dns"><span class="item-number">2.5</span> DNS & Domains</a></h3>
    <p>Configuración de DNS, dominios y subdominios del ecosistema.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">DNS</span>
        <span class="card-tag">Domains</span>
        <span class="card-tag">Routing</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="#ssl"><span class="item-number">2.6</span> SSL/TLS</a></h3>
    <p>Certificados SSL automáticos y configuración de seguridad.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">SSL</span>
        <span class="card-tag">Let's Encrypt</span>
        <span class="card-tag">Security</span>
      </div>
    </div>
  </div>
</div>

## Arquitectura de Red

La infraestructura está diseñada con los siguientes principios:

- **Proxy Reverso Centralizado**: Traefik como punto de entrada único
- **Seguridad por Defecto**: SSL/TLS automático y headers de seguridad
- **Alta Disponibilidad**: Configuración redundante y health checks
- **Monitorización Integrada**: Métricas y logs centralizados

## Diagrama de Red

```mermaid
graph TB
    Internet[Internet] --> Traefik[Traefik Proxy]
    Traefik --> Web[Web App]
    Traefik --> API[API Server]
    Traefik --> Blog[Blog]
    Traefik --> Wiki[Wiki]
    Traefik --> Monitor[Monitoring]
    Traefik --> N8N[N8N Workflows]
    Traefik --> Portainer[Portainer]
    
    Nginx[Nginx] --> StaticFiles[Static Files]
    Traefik --> Nginx
```

## Configuraciones Clave

| Componente | Configuración | Ubicación | Estado |
|------------|---------------|-----------|--------|
| Traefik | docker-compose.yml | `/infra/traefik/` | 🟢 Activo |
| Nginx | nginx.conf | `/infra/nginx/` | 🟢 Activo |
| Ansible | playbooks/ | `/infra/ansible/` | 🟢 Configurado |
| Docker | Dockerfiles | `/apps/*/` | 🟢 Multi-container |
| DNS | mlorente.dev | Cloudflare | 🟢 Activo |
| SSL | Let's Encrypt | Automático | 🟢 Auto-renovación |

## Servicios de Red

### Puertos y Exposición

- **80/443**: Entrada HTTP/HTTPS (Traefik)
- **8080**: Dashboard Traefik (interno)
- **9443**: Portainer HTTPS
- **5678**: N8N workflows
- **3000-3004**: Aplicaciones (proxificadas)

### Dominios Configurados

- `mlorente.dev` - Sitio principal
- `api.mlorente.dev` - API REST/GraphQL
- `blog.mlorente.dev` - Blog personal
- `wiki.mlorente.dev` - Documentación técnica
- `monitoring.mlorente.dev` - Dashboards
- `n8n.mlorente.dev` - Automatización
- `portainer.mlorente.dev` - Gestión containers

---

💡 **Tip:** La infraestructura se gestiona principalmente mediante Docker Compose y scripts de automatización.