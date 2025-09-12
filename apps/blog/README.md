# Mi Blog Técnico con Jekyll

<div align="center">

![Jekyll](https://img.shields.io/badge/Jekyll-4.3.4-CC0000?style=flat&logo=jekyll&logoColor=white)
![Ruby](https://img.shields.io/badge/Ruby-CC342D?style=flat&logo=ruby&logoColor=white)
![Bootstrap](https://img.shields.io/badge/Bootstrap-7952B3?style=flat&logo=bootstrap&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

</div>

Este es mi blog personal donde escribo sobre DevOps, SRE, desarrollo y todas esas cosas que me van gustando por el camino. Lo hago con Jekyll porque me gusta escribir en markdown y que se genere todo estático.

## 🤔 Por qué elegí Jekyll

- **Jekyll 4.3.4** - Es rápido, estable y me deja escribir en markdown puro sin complicaciones
- **Beautiful Jekyll** - Tema que personalicé porque me gusta cómo se ve y es muy responsive
- **Bootstrap** - Para no reinventar la rueda con los estilos y que se adapte bien a móviles
- **Generación estática** - Súper rápido de cargar y fácil de desplegar donde sea
- **Markdown** - Escribo en markdown y me olvido del HTML

## 📁 Cómo está organizado

```
jekyll-site/
├── _config.yml              # Configuración principal del blog
├── _data/
│   └── ui-text.yml          # Textos de la interfaz en español
├── _includes/               # Componentes reutilizables
│   ├── footer.html          # El pie de página
│   ├── header.html          # La cabecera
│   └── nav.html            # La navegación
├── _layouts/               # Plantillas de página
│   ├── default.html        # Layout principal
│   ├── post.html           # Para las entradas del blog
│   └── page.html           # Para páginas estáticas
├── _posts/                 # Mis artículos (markdown)
│   ├── 2024-02-18-the-harmony-of-devops-and-sre.md
│   ├── 2024-03-10-the-magic-of-the-cloud.md
│   └── ...
├── assets/                 # Archivos estáticos
│   ├── css/               # Mis estilos personalizados
│   ├── img/               # Imágenes y media
│   └── js/                # JavaScript si hace falta
├── aboutme.html           # Página sobre mí
└── tags.html              # Lista de todas las etiquetas
```

## 🚀 Lo que más me gusta del blog

### Para escribir

- **Markdown puro** - Escribo en markdown y se ve perfecto
- **Sintaxis highlighting** - Los bloques de código se ven geniales
- **MathJax** - Para cuando necesito escribir fórmulas o cosas matemáticas
- **Imágenes responsive** - Las imágenes se adaptan automáticamente
- **Sistema de etiquetas** - Para organizar los posts por temas
- **Búsqueda** - Los lectores pueden buscar contenido

### Para los lectores

- **Carga súper rápida** - Es estático, no puede ir más rápido
- **Responsive al 100%** - Se ve perfecto en móvil, tablet y desktop
- **Tema oscuro/claro** - Porque no todos aguantamos lo mismo
- **Compartir en redes** - Botones para compartir en redes sociales
- **Tiempo de lectura** - Para saber cuánto van a tardar en leer

## 🔧 Configuración principal

```yaml
# _config.yml
title: Manu Lorente
author: Manuel Lorente
url: "https://mlorente.dev"
description: "Mi blog personal sobre DevOps, SRE y desarrollo"

# Navegación principal
navbar-links:
  Blog: "/"
  Sobre mí: "aboutme"

# Mis redes sociales
social-network-links:
  github: mlorentedev
  linkedin: manuel-lorente-alman
  email: info@mlorente.dev

# Para el feed RSS
rss-description: "Mis reflexiones sobre DevOps y SRE"
excerpt_length: 50
```

## 🐳 Cómo lo ejecuto

### En desarrollo

```bash
# Con hot reload que me encanta
docker-compose -f docker-compose.dev.yml up --build

# Y lo veo en http://localhost:4000
```

### En producción

```bash
# Despliegue completo
docker-compose -f docker-compose.prod.yml up -d

# Ver qué tal va
docker-compose logs -f blog
```

## 🛠️ Desarrollo local

```bash
# Me voy al directorio de Jekyll
cd apps/blog/jekyll-site

# Instalo las gemas de Ruby
bundle install

# Y lo arranco con live reload
bundle exec jekyll serve --livereload

# Se abre en http://localhost:4000
```

### Comandos que uso

```bash
# Build del sitio
bundle exec jekyll build

# Servir con borradores
bundle exec jekyll serve --drafts

# Limpiar archivos temporales
bundle exec jekyll clean

# Verificar si hay problemas
bundle exec jekyll doctor
```

## ✍️ Cómo escribo un post

Creo un archivo en `_posts/` con el formato `YYYY-MM-DD-titulo.md`:

```yaml
---
layout: post
title: "Título del Post"
subtitle: "Un subtítulo si me apetece"
date: 2024-01-15
author: "Manuel Lorente"
tags: [devops, sre, tutorial]
cover-img: /assets/img/cover.jpg
thumbnail-img: /assets/img/thumb.jpg
share-img: /assets/img/share.jpg
readtime: true
comments: true
---

Y aquí escribo todo el contenido en markdown...
```

### Opciones que uso en el frontmatter

```yaml
# Obligatorio
layout: post
title: "Título del Post"
date: 2024-01-15

# SEO y redes sociales
subtitle: "Subtítulo opcional"
meta-description: "Descripción custom para Google"
share-img: "/assets/img/share.jpg"

# Visual
cover-img: "/assets/img/cover.jpg"
thumbnail-img: "/assets/img/thumb.jpg"

# Organización
tags: [tag1, tag2, tag3]
categories: [categoria]
author: "Mi nombre"
readtime: true

# Si es código open source
gh-repo: usuario/repo
gh-badge: [star, fork, follow]

# Comentarios
comments: true
```

## 📝 Lo que más uso cuando escribo

### Bloques de código

```bash
# Siempre especifico el lenguaje
sudo systemctl start docker
```

### Expresiones matemáticas

Para cuando necesito explicar algo con matemáticas:

```latex
$$E = mc^2$$
```

### Cajas de aviso

```markdown
{: .box-note}
**Nota:** Esto es importante que lo sepas.

{: .box-warning}  
**Cuidado:** Esto puede romper cosas.

{: .box-error}
**Error:** Algo ha ido mal.

{: .box-success}
**Genial:** Todo ha funcionado.
```

### Imágenes centradas

```markdown
![Descripción](/assets/img/image.jpg){: .mx-auto.d-block :}
```

## 🔍 SEO y analytics

Me gusta saber quién lee el blog:

- **Datos estructurados** - Para que Google entienda mejor los artículos
- **Open Graph** - Para que se vean bien cuando se comparten en redes
- **Twitter Cards** - Para que quede chulo en Twitter
- **Sitemap automático** - Se genera solo
- **Feed RSS** - Para los que siguen blogs clásicamente

### Analytics que uso

- **Google Analytics 4** - Para saber de dónde viene la gente
- **Cloudflare Analytics** - Métricas de rendimiento
- **Tiempo de lectura** - Para ver el engagement
- **Compartir en redes** - Para ver qué se comparte más

## 🚀 Optimización que implementé

### Build optimizado

- **Compresión de imágenes** - Se convierten automáticamente a WebP
- **CSS minificado** - Todo comprimido para que cargue rápido
- **Caché inteligente** - Los recursos estáticos se cachean bien
- **Lazy loading** - Las imágenes cargan cuando las necesitas

### Hosting

- **Hosting estático** - Todo HTML pre-generado
- **CDN** - Se sirve desde múltiples ubicaciones
- **Compresión Gzip** - Todo comprimido
- **HTTP/2** - Protocolo moderno

## 🎨 Personalización del tema

```scss
// Variables personalizadas
$primary-color: #0085a1;
$navbar-border-col: #eaeaea;
$footer-col: #404040;

// Componentes custom que añadí
.custom-box {
  border-left: 4px solid $primary-color;
  padding: 1rem;
  margin: 1rem 0;
}
```

Para personalizar más:

- **Layouts** en `_layouts/` - Para cambiar la estructura
- **Includes** en `_includes/` - Para añadir componentes
- **Navegación** en `_data/navigation.yml` - Para el menú
- **Estilos** en `assets/css/` - Para los colores y tipografías

## 📈 De qué escribo

### Temas que me van

- **DevOps** - CI/CD, automatización, herramientas que uso
- **SRE** - Monitoreo, respuesta a incidentes, reliability
- **Cloud** - AWS, containers, orquestación  
- **Linux** - Administración, troubleshooting, scripts
- **Desarrollo** - Mejores prácticas, arquitectura, lo que voy aprendiendo

### Frecuencia de posts

- **Posts regulares** - Intento escribir 2-3 veces al mes
- **Tutoriales técnicos** - Guías paso a paso cuando aprendo algo nuevo
- **Reflexiones** - Análisis de tendencias o cosas que me llaman la atención
- **Proyectos personales** - Mi homelab y experimentos

## 🤝 Si quieres contribuir

1. Fork del repositorio
2. Crea una rama para tu contribución
3. Escribe siguiendo el estilo del blog
4. Pruébalo localmente con Jekyll
5. Envía un pull request
6. Te reviso el contenido y lo publicamos

### Directrices de escritura

- **Precisión técnica** - Todo el código y comandos tienen que funcionar
- **SEO friendly** - Títulos descriptivos y meta descripciones que tengan sentido
- **Imágenes** - Siempre con texto alternativo para accesibilidad
- **Código limpio** - Syntax highlighting apropiado
- **Accesible** - Que se pueda leer bien en cualquier dispositivo

---

Este blog es mi forma de documentar lo que voy aprendiendo y compartirlo con la comunidad. Si algo te resulta útil o tienes alguna sugerencia, siempre puedes escribirme.