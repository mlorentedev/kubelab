---
title: Applications - mlorente.dev
description: Documentation for all applications in the mlorente.dev ecosystem
hide:
  - toc
---

# 1.0 Applications

**Complete documentation for all applications in the mlorente.dev ecosystem**

---

## Available Applications

<div class="section-cards">
  <div class="section-card">
    <h3><a href="api/"><span class="item-number">1.1</span> API</a></h3>
    <p>Main system API with REST endpoints and GraphQL support.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Backend</span>
        <span class="card-tag">REST</span>
        <span class="card-tag">Go</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="web/"><span class="item-number">1.2</span> Web</a></h3>
    <p>Main web application, frontend built with Astro framework.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Frontend</span>
        <span class="card-tag">Astro</span>
        <span class="card-tag">TypeScript</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="blog/"><span class="item-number">1.3</span> Blog</a></h3>
    <p>Personal and technical blog with content management system.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Blog</span>
        <span class="card-tag">Jekyll</span>
        <span class="card-tag">Markdown</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="wiki/"><span class="item-number">1.4</span> Wiki</a></h3>
    <p>Technical documentation system built with MkDocs Material.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Docs</span>
        <span class="card-tag">MkDocs</span>
        <span class="card-tag">Wiki</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="portainer/"><span class="item-number">1.5</span> Portainer</a></h3>
    <p>Visual Docker container management and orchestration interface.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Docker</span>
        <span class="card-tag">Containers</span>
        <span class="card-tag">Management</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="grafana/"><span class="item-number">1.6</span> Grafana</a></h3>
    <p>Monitoring and observability system for the entire ecosystem.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Monitoring</span>
        <span class="card-tag">Metrics</span>
        <span class="card-tag">Logs</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="n8n/"><span class="item-number">1.7</span> n8n</a></h3>
    <p>Workflow automation and business process integration platform.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Automation</span>
        <span class="card-tag">Workflows</span>
        <span class="card-tag">Integration</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="uptime/"><span class="item-number">1.8</span> Uptime Kuma</a></h3>
    <p>Service monitoring and uptime tracking for all applications.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Monitoring</span>
        <span class="card-tag">Uptime</span>
        <span class="card-tag">Alerts</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="loki/"><span class="item-number">1.9</span> Loki</a></h3>
    <p>Log aggregation system for centralized logging across services.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Logs</span>
        <span class="card-tag">Aggregation</span>
        <span class="card-tag">Search</span>
      </div>
    </div>
  </div>
  
  <div class="section-card">
    <h3><a href="minio/"><span class="item-number">1.10</span> MinIO</a></h3>
    <p>Object storage server for files, images, and static assets.</p>
    <div class="card-footer">
      <div class="card-tags">
        <span class="card-tag">Storage</span>
        <span class="card-tag">S3 Compatible</span>
        <span class="card-tag">Objects</span>
      </div>
    </div>
  </div>
</div>

## General Architecture

Applications are designed following clean architecture principles and microservices patterns:

- **Separation of concerns**: Each application has a specific purpose
- **API communication**: Well-defined interfaces between services
- **Horizontal scalability**: Design prepared for growth
- **Observability**: Centralized monitoring and logging

## Quick Links

| Application | Status | Port | Documentation |
|------------|--------|--------|---------------|
| API | 🟢 Active | 3000 | [View docs](api/) |
| Web | 🟢 Active | 3001 | [View docs](web/) |
| Blog | 🟢 Active | 4000 | [View docs](blog/) |
| Wiki | 🟢 Active | 8000 | [View docs](wiki/) |
| Portainer | 🟢 Active | 9000 | [View docs](portainer/) |
| Grafana | 🟢 Active | 3000 | [View docs](grafana/) |
| n8n | 🟢 Active | 5678 | [View docs](n8n/) |
| Uptime Kuma | 🟢 Active | 3001 | [View docs](uptime/) |
| Loki | 🟢 Active | 3100 | [View docs](loki/) |
| MinIO | 🟢 Active | 9000 | [View docs](minio/) |

---

💡 **Tip:** Use the sidebar navigation to quickly access specific application documentation.