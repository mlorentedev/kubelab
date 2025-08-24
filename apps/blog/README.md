# Blog Personal

<div align="center">

![Jekyll](https://img.shields.io/badge/Jekyll-4.3.4-CC0000?style=flat&logo=jekyll&logoColor=white)
![Ruby](https://img.shields.io/badge/Ruby-CC342D?style=flat&logo=ruby&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-7952B3?style=flat&logo=bootstrap&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

</div>

Blog personal basado en Jekyll para mlorente.dev, presentando contenido sobre DevOps, SRE e ingeniería de software.

## 🏗️ Arquitectura

- **Generador de Sitio Estático**: Jekyll 4.3.4
- **Tema**: Beautiful Jekyll (personalizado)
- **Estilos**: Bootstrap + CSS personalizado
- **Despliegue**: Docker + Nginx
- **Contenido**: Markdown con frontmatter YAML

## 📁 Estructura del Proyecto

```
jekyll-site/
├── _config.yml              # Configuración de Jekyll
├── _data/
│   └── ui-text.yml          # Texto de interfaz y traducciones
├── _includes/               # Componentes de plantilla reutilizables
│   ├── analytics/           # Seguimiento de analíticas
│   ├── comments/            # Sistemas de comentarios
│   ├── footer.html          # Pie de página del sitio
│   ├── header.html          # Cabecera del sitio
│   ├── nav.html            # Navegación
│   └── ...
├── _layouts/               # Plantillas de página
│   ├── base.html           # Plantilla base
│   ├── default.html        # Diseño por defecto
│   ├── home.html           # Diseño de página de inicio
│   ├── page.html           # Páginas estáticas
│   └── post.html           # Diseño de entrada de blog
├── _posts/                 # Entradas del blog (markdown)
│   ├── 2024-02-18-the-harmony-of-devops-and-sre.md
│   ├── 2024-03-10-the-magic-of-the-cloud.md
│   └── ...
├── _site/                  # Sitio estático generado (ignorado)
├── assets/                 # Recursos estáticos
│   ├── css/               # Hojas de estilo
│   ├── img/               # Imágenes y medios
│   └── js/                # Archivos JavaScript
├── aboutme.html           # Página sobre mí
├── tags.html              # Lista de etiquetas
├── Gemfile                # Dependencias de Ruby
└── Gemfile.lock          # Dependencias bloqueadas
```

## 🚀 Características

### Características de Contenido
- **Entradas Técnicas del Blog**: Temas sobre DevOps, SRE, Linux, Cloud
- **Resaltado de Sintaxis**: Bloques de código con soporte de idiomas
- **Soporte Matemático**: Renderizado LaTeX para contenido técnico
- **Galería de Imágenes**: Imágenes responsivas con carga diferida
- **Sistema de Etiquetas**: Categorización y filtrado de contenido
- **Búsqueda**: Funcionalidad de búsqueda del lado del cliente

### Características de Diseño
- **Diseño Responsivo**: Diseño Bootstrap mobile-first
- **Tema Oscuro/Claro**: Soporte de preferencias del usuario
- **Carga Rápida**: Recursos optimizados y carga diferida
- **Optimizado para SEO**: Meta tags, datos estructurados, sitemap
- **Compartir en Redes**: Botones de compartir integrados

### Analíticas y Compromiso
- **Google Analytics**: Seguimiento de tráfico y comportamiento del usuario
- **Cloudflare Analytics**: Monitoreo de rendimiento
- **Sistema de Comentarios**: Múltiples proveedores (Disqus, Giscus)
- **Integración de Newsletter**: Formularios de suscripción vía API
- **Tiempo de Lectura**: Tiempo estimado de lectura para las entradas

## 🔧 Configuración

### Configuración del Sitio (`_config.yml`)

```yaml
# Información Básica
title: Manu Lorente
author: Manuel Lorente
url: "https://mlorente.dev"
description: "Blog personal sobre DevOps, SRE e ingeniería de software"

# Navegación
navbar-links:
  Blog: "/"
  Sobre mí: "aboutme"

# Enlaces Sociales
social-network-links:
  github: mlorentedev
  linkedin: manuel-lorente-alman
  email: info@mlorente.dev

# Características
rss-description: "Perspectivas sobre DevOps y SRE"
excerpt_length: 50
```

### Variables de Entorno

```bash
# Configuración de Build
JEKYLL_ENV=production
PAGES_REPO_NWO=username/repository
```

## 🐳 Despliegue con Docker

### Desarrollo
```bash
# Construir y servir con recarga en vivo
docker-compose -f docker-compose.dev.yml up --build

# Acceder en http://localhost:4000
```

### Producción
```bash
# Construir y desplegar
docker-compose -f docker-compose.prod.yml up -d

# Ver logs
docker-compose logs -f blog
```

## 🛠️ Desarrollo Local

### Prerrequisitos
- Ruby 3.0+ y Bundler
- Node.js (para procesamiento de recursos)
- Docker (opcional)

### Configuración
```bash
# Navegar al directorio de Jekyll
cd apps/blog/jekyll-site

# Instalar dependencias de Ruby
bundle install

# Servir localmente con recarga en vivo
bundle exec jekyll serve --livereload

# Acceder en http://localhost:4000
```

### Comandos de Desarrollo
```bash
# Construir el sitio
bundle exec jekyll build

# Servir con borradores
bundle exec jekyll serve --drafts

# Limpiar archivos de build
bundle exec jekyll clean

# Verificar problemas
bundle exec jekyll doctor
```

## ✍️ Creación de Contenido

### Escribir Entradas del Blog

Crear nuevas entradas en `_posts/` con la convención de nombres: `YYYY-MM-DD-titulo.md`

```yaml
---
layout: post
title: "Título de tu Entrada"
subtitle: "Subtítulo opcional"
date: 2024-01-15
author: "Manuel Lorente"
tags: [devops, sre, tutorial]
cover-img: /assets/img/cover.jpg
thumbnail-img: /assets/img/thumb.jpg
share-img: /assets/img/share.jpg
readtime: true
---

Tu contenido markdown aquí...
```

### Opciones de Frontmatter

```yaml
# Requerido
layout: post
title: "Título de la Entrada"
date: 2024-01-15

# SEO y Social
subtitle: "Subtítulo de la entrada"
meta-description: "Descripción personalizada para SEO"
share-img: "/assets/img/share.jpg"

# Visual
cover-img: "/assets/img/cover.jpg"
thumbnail-img: "/assets/img/thumb.jpg"

# Contenido
tags: [etiqueta1, etiqueta2, etiqueta3]
categories: [categoria]
author: "Nombre del Autor"
readtime: true
gh-repo: usuario/repo
gh-badge: [star, fork, follow]

# Comentarios
comments: true
```

### Directrices de Contenido

1. **Precisión Técnica**: Verificar todos los ejemplos de código y comandos
2. **Optimización SEO**: Usar títulos descriptivos y meta descripciones
3. **Atractivo Visual**: Incluir imágenes y diagramas relevantes
4. **Calidad del Código**: Usar resaltado de sintaxis apropiado
5. **Accesibilidad**: Incluir texto alt para imágenes

## 📝 Características de Escritura

### Bloques de Código
```bash
# Usar bloques de código delimitados con idioma
sudo systemctl start docker
```

### Expresiones Matemáticas
Usar sintaxis LaTeX para expresiones matemáticas:
```latex
$$E = mc^2$$
```

### Cajas de Notificación
```markdown
{: .box-note}
**Nota:** Esta es una caja de notificación.

{: .box-warning}
**Advertencia:** Esta es una caja de advertencia.

{: .box-error}
**Error:** Esta es una caja de error.

{: .box-success}
**Éxito:** Esta es una caja de éxito.
```

### Galerías de Imágenes
```markdown
![Descripción](/assets/img/image.jpg){: .mx-auto.d-block :}
```

## 🔍 SEO y Analíticas

### Características SEO
- **Datos Estructurados**: JSON-LD para artículos
- **Open Graph**: Vistas previas en redes sociales
- **Twitter Cards**: Metadatos específicos de Twitter
- **Sitemap**: Generación automática de sitemap XML
- **Feed RSS**: Generación automática de feed

### Integración de Analíticas
- **Google Analytics 4**: Seguimiento de comportamiento del usuario
- **Cloudflare Analytics**: Métricas de rendimiento
- **Tiempo de Lectura**: Métricas de compromiso
- **Compartir Social**: Seguimiento del alcance del contenido

## 🚀 Optimización de Rendimiento

### Optimizaciones de Build
- **Compresión de Imágenes**: Conversión automática a WebP
- **Minificación CSS**: Hojas de estilo comprimidas
- **Caché de Recursos**: Caché del navegador a largo plazo
- **Carga Diferida**: Carga diferida de imágenes

### Optimizaciones de Despliegue
- **Hosting Estático**: HTML pre-generado
- **Integración CDN**: Entrega global de contenido
- **Compresión Gzip**: Tamaños de transferencia reducidos
- **HTTP/2**: Conexiones multiplexadas

## 🎨 Personalización

### Personalización del Tema
```scss
// Variables personalizadas en _sass/main.scss
$primary-color: #0085a1;
$navbar-border-col: #eaeaea;
$footer-col: #404040;

// Componentes personalizados
.custom-box {
  border-left: 4px solid $primary-color;
  padding: 1rem;
  margin: 1rem 0;
}
```

### Modificaciones de Diseño
- Editar plantillas en `_layouts/`
- Añadir includes en `_includes/`
- Modificar navegación en `_data/navigation.yml`
- Actualizar estilos en `assets/css/`

## 🔗 Servicios Relacionados

- **Frontend Web**: `apps/web` - Sitio web principal
- **Backend API**: `apps/api` - Suscripciones al newsletter
- **Infraestructura**: `infra/` - Hosting y despliegue

## 📈 Estrategia de Contenido

### Temas Cubiertos
- **Ingeniería DevOps**: CI/CD, automatización, herramientas
- **Ingeniería de Confiabilidad de Sitio**: Monitoreo, respuesta a incidentes
- **Computación en la Nube**: AWS, contenedorización, orquestación
- **Sistemas Linux**: Administración, resolución de problemas
- **Ingeniería de Software**: Mejores prácticas, arquitectura

### Horario de Publicación
- **Entradas Regulares**: 2-3 veces por mes
- **Tutoriales Técnicos**: Guías en profundidad
- **Comentarios de la Industria**: Análisis de tendencias
- **Proyectos Personales**: Homelab y experimentos

## 🤝 Contribuir

1. Hacer fork del repositorio
2. Crear una rama de característica
3. Escribir tu contenido siguiendo las directrices
4. Probar localmente con Jekyll
5. Enviar una pull request
6. Seguir el proceso de revisión