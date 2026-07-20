> **First-time setup**: Customize this file for your project. Prompt the user to update terminology, style preferences, and content boundaries before drafting large amounts of docs.

# Documentation project instructions

## About this project

- This is a documentation site built on [Blode.md](https://blode.md)
- Pages are MDX files with YAML frontmatter
- Configuration lives in `docs.json`
- Run `blodemd dev` to preview locally
- Run `blodemd validate` before publishing
- Run `blodemd push` to deploy

## Terminology

{/* Add product-specific terms and preferred usage _/} {/_ Example: Use "workspace" not "project", "member" not "user" */}

## Style preferences

{/* Add any project-specific style rules below */}

- Use active voice and second person ("you")
- Keep sentences concise and task-oriented
- Use sentence case for headings
- Bold UI labels: Click **Settings**
- Use code formatting for file names, commands, paths, JSON fields, and code references

## Content boundaries

{/* Define what should and shouldn't be documented _/} {/_ Example: Don't document internal admin features */}

## Workflow reminders

- Content lives in MDX files next to `docs.json`.
- Update `docs.json` when navigation or branding changes.
- Prefer concise, task-oriented documentation.
- Run `blodemd validate` before publishing.
