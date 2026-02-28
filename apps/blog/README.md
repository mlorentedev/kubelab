# Blog - Technical Writing Platform

My personal technical blog where I write about DevOps, SRE, development, and everything I learn along the way. Built with Jekyll because I love writing in markdown and having everything generated as static files.

 What it is

This is my personal blog where I share technical articles, tutorials, and thoughts about DevOps, SRE, cloud technologies, and software development. I chose Jekyll because it lets me write in pure markdown without complications, generates lightning-fast static sites, and gives me full control over the content and presentation.

The blog focuses on practical content - tutorials that actually work, insights from real projects, and sharing what I learn from my homelab experiments and professional work.

 Tech stack

- Jekyll .. - Fast, stable, and lets me write in pure markdown
- Beautiful Jekyll - Customized theme that looks great and is fully responsive
- Bootstrap - For responsive design without reinventing the wheel
- Static generation - Super fast loading and easy deployment anywhere
- Markdown - Write content in markdown and forget about HTML

 Project structure

```
jekyll-site/
├── _config.yml               Main blog configuration
├── _data/
│   └── ui-text.yml           Interface text localization
├── _includes/                Reusable components
│   ├── footer.html           Site footer
│   ├── header.html           Site header
│   └── nav.html             Navigation menu
├── _layouts/                Page templates
│   ├── default.html         Main layout
│   ├── post.html            Blog post template
│   └── page.html            Static page template
├── _posts/                  Blog articles (markdown)
│   ├── ---the-harmony-of-devops-and-sre.md
│   ├── ---the-magic-of-the-cloud.md
│   └── ...
├── assets/                  Static assets
│   ├── css/                Custom styles
│   ├── img/                Images and media
│   └── js/                 JavaScript if needed
├── aboutme.html            About me page
└── tags.html               All tags listing
```

 Key features

 For writing
- Pure markdown - Write in markdown and it looks perfect
- Syntax highlighting - Code blocks look great with proper highlighting
- MathJax support - For when I need to write formulas or mathematical expressions
- Responsive images - Images adapt automatically to screen sizes
- Tag system - Organize posts by topics and themes
- Search functionality - Readers can search through content

 For readers
- Lightning fast loading - Static generation means maximum speed
- % responsive - Perfect display on mobile, tablet, and desktop
- Dark/light theme - Multiple theme options available
- Social sharing - Easy sharing buttons for social media
- Reading time - Estimated reading time for each post

 Configuration

 Main settings

```yaml
 _config.yml
title: Manu Lorente
author: Manuel Lorente
url: "https://kubelab.live"
description: "Personal blog about DevOps, SRE and development"

 Main navigation
navbar-links:
  Blog: "/"
  About: "aboutme"

 Social networks
social-network-links:
  github: mlorentedev
  linkedin: manuel-lorente-alman
  email: info@mlorente.dev

 RSS feed
rss-description: "Thoughts on DevOps and SRE"
excerpt_length: 
```

 Running the blog

 Development mode

```bash
 With hot reload
make up-blog

 Access at http://blog.mlorentedev.test
```

 Local development

```bash
 Navigate to Jekyll directory
cd apps/blog/jekyll-site

 Install Ruby gems
bundle install

 Start with live reload
bundle exec jekyll serve --livereload

 Access at http://localhost:
```

 Available commands

```bash
 Build the site
bundle exec jekyll build

 Serve with drafts
bundle exec jekyll serve --drafts

 Clean temporary files
bundle exec jekyll clean

 Check for issues
bundle exec jekyll doctor
```

 Writing a blog post

Create a file in `_posts/` with the format `YYYY-MM-DD-title.md`:

```yaml
---
layout: post
title: "Post Title"
subtitle: "Optional subtitle"
date: --
author: "Manuel Lorente"
tags: [devops, sre, tutorial]
cover-img: /assets/img/cover.jpg
thumbnail-img: /assets/img/thumb.jpg
share-img: /assets/img/share.jpg
readtime: true
comments: true
---

Write all the content here in markdown...
```

 Frontmatter options

```yaml
 Required
layout: post
title: "Post Title"
date: --

 SEO and social media
subtitle: "Optional subtitle"
meta-description: "Custom description for Google"
share-img: "/assets/img/share.jpg"

 Visual
cover-img: "/assets/img/cover.jpg"
thumbnail-img: "/assets/img/thumb.jpg"

 Organization
tags: [tag, tag, tag]
categories: [category]
author: "Author name"
readtime: true

 For open source projects
gh-repo: user/repo
gh-badge: [star, fork, follow]

 Comments
comments: true
```

 Writing features

 Code blocks

```bash
 Always specify the language
sudo systemctl start docker
```

 Mathematical expressions

For when I need to explain something with mathematics:

```latex
$$E = mc^$$
```

 Alert boxes

```markdown
{: .box-note}
Note: This is important to know.

{: .box-warning}  
Warning: This could break things.

{: .box-error}
Error: Something went wrong.

{: .box-success}
Success: Everything worked perfectly.
```

 Centered images

```markdown
![Description](/assets/img/image.jpg){: .mx-auto.d-block :}
```

 SEO and analytics

I like to know who reads the blog:

- Structured data - So Google better understands the articles
- Open Graph - So posts look good when shared on social media
- Twitter Cards - For nice Twitter sharing previews
- Automatic sitemap - Generated automatically
- RSS feed - For those who follow blogs the classic way

 Analytics I use

- Google Analytics  - To understand where traffic comes from
- Cloudflare Analytics - Performance metrics
- Reading time - To measure engagement
- Social sharing - To see what gets shared most

 Performance optimization

 Build optimization

- Image compression - Automatically converted to WebP format
- Minified CSS - Everything compressed for fast loading
- Smart caching - Static resources cache efficiently
- Lazy loading - Images load when you need them

 Hosting

- Static hosting - All HTML pre-generated
- CDN - Served from multiple locations
- Gzip compression - Everything compressed
- HTTP/ - Modern protocol support

 Theme customization

```scss
// Custom variables
$primary-color: a;
$navbar-border-col: eaeaea;
$footer-col: ;

// Custom components I added
.custom-box {
  border-left: px solid $primary-color;
  padding: rem;
  margin: rem ;
}
```

To customize further:

- Layouts in `_layouts/` - To change page structure
- Includes in `_includes/` - To add components
- Navigation in `_data/navigation.yml` - For the menu
- Styles in `assets/css/` - For colors and typography

 What I write about

 Topics I cover

- DevOps - CI/CD, automation, tools I use daily
- SRE - Monitoring, incident response, reliability engineering
- Cloud - AWS, containers, orchestration
- Linux - Administration, troubleshooting, scripting
- Development - Best practices, architecture, things I'm learning

 Post frequency

- Regular posts - I try to write - times per month
- Technical tutorials - Step-by-step guides when I learn something new
- Reflections - Analysis of trends or things that catch my attention
- Personal projects - My homelab and experiments

 Contributing

. Fork the repository
. Create a branch for your contribution
. Write following the blog's style
. Test locally with Jekyll
. Submit a pull request
. I'll review the content and publish it

 Writing guidelines

- Technical accuracy - All code and commands must work
- SEO friendly - Descriptive titles and meta descriptions
- Images - Always with alt text for accessibility
- Clean code - Proper syntax highlighting
- Accessible - Readable on any device

 Local development URLs

When running locally with `make up-blog`:
- Blog: http://blog.mlorentedev.test
- Development server: http://localhost:

Add `... blog.mlorentedev.test` to your `/etc/hosts` file.

---

This blog is my way of documenting what I learn and sharing it with the community. If you find something useful or have suggestions, feel free to reach out.
