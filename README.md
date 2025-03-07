# mlorente.dev

This is my minimal website [mlorente.dev](https://mlorente.dev).

## Project Structure

Inside of this project, you'll see the following folders and files:

```text
|── .github/
|   |── workflows/
|── .vscode/
├── public/
├── src/
│   ├── components/
│   ├── content/
│   ├── layouts/
│   └── pages/
│       ├── projects/
│           ├── [slug]/
├── utils/
|── .gitignore
|── .pretierignore
|── .prettierrc
├── astro.config.mjs
|── eslint.config.cjs
├── package.json
|── README.md
|── tailwind.config.cjs
└── tsconfig.json
```

Astro looks for `.astro` or `.md` files in the `src/pages/` directory. Each page is exposed as a route based on its file name and its language parameter.

There's nothing special about `src/components/`, but that's where we like to put any Astro/React/Vue/Svelte/Preact components.

The `src/content/` directory contains "collections" of related Markdown and MDX documents.
The `src/content/config.ts` file adds the `slug` key as a property to the collections. This is the slug that will be used in the header, blogs list page and as canonical and alternate URLs.

Any static assets, like images, can be placed in the `public/` directory.

## Commands

All commands are run from the root of the project, from a terminal:

| Command                   | Action                                           |
| :------------------------ | :----------------------------------------------- |
| `npm install`             | Installs dependencies                            |
| `npm run dev`             | Starts local dev server at `localhost:4321`      |
| `npm run build`           | Build your production site to `./dist/`          |
| `npm run preview`         | Preview your build locally, before deploying     |
| `npm run lint`            | Lint your code for formatting and errors         |
| `npm run format`          | Format your code for consistency                 |
| `npm run astro ...`       | Run CLI commands like `astro add`, `astro check` |
| `npm run astro -- --help` | Get help using the Astro CLI                     |

## Tips

To disable the devToolbar, run this command:

```shell
    astro preferences disable devToolbar
```

## TODO

- [ ] Script to populate secrets in GitHub Actions
- [ ] Add homelab section: learning-path, homelabs, etc. similar to Collabnix
- [ ] CI/CD with GitHub Actions
- [ ] Most recent RRSS in some section - dynamic with CI/CD
- [ ] Testing
- [ ] Slack community integration with the API
- [ ] Dynamic quotes at the end of the page
- [ ] Copy in all pages
- [ ] Simple and minimalistic design
- [ ] Indexed search by tags

## CONTRIBUTING

If you want to contribute to this project, please read the [CONTRIBUTING.md](CONTRIBUTING.md) file.
