# den Website

A single-page showcase for den — Your Personal Cloud Lab.

## Brand Identity

**Concept**: "The Research Station" — a retro-scientific aesthetic inspired by 1970s space mission control and vintage laboratory equipment.

**Personality**: Precise but playful. Technical but accessible. Like a well-organized lab where serious science happens, but the scientists have personality.

**Visual Language**:
- Dark terminal aesthetic (#0D1117 background)
- Warning orange accent (#FF6B35) — like indicator lights on vintage equipment
- Grid background suggesting graph paper
- Scanline overlay evoking CRT displays
- Monospace for code, clean sans-serif for content

## Files

- `index.html` — Main site (single file, self-contained)
- `assets/og-card.svg` — Open Graph image source
- `README.md` — This file

## Open Graph

The site includes complete Open Graph meta tags for Twitter, Discord, and Facebook:

```html
<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="den — Your Personal Cloud Lab">
<meta name="twitter:description" content="...">
<meta name="twitter:image" content="https://den.dev/assets/og-card.png">

<!-- Facebook/Open Graph -->
<meta property="og:type" content="website">
<meta property="og:title" content="den — Your Personal Cloud Lab">
<meta property="og:description" content="...">
<meta property="og:image" content="https://den.dev/assets/og-card.png">
```

**Note**: The current site points metadata at `https://den.dio.computer`. If you want broad Open Graph compatibility, convert `assets/og-card.svg` to PNG and point the meta tags at the PNG asset:

```bash
# Using sharp
npx sharp -i assets/og-card.svg -o assets/og-card.png

# Using ImageMagick
convert assets/og-card.svg assets/og-card.png

# Using Inkscape
inkscape assets/og-card.svg --export-filename=assets/og-card.png
```

Then update the meta tags to point to the `.png` file.

## Deployment

This is a static site. Deploy anywhere:

- GitHub Pages
- Vercel
- Netlify
- Cloudflare Pages
- S3 + CloudFront

## Development

```bash
# Serve locally
python3 -m http.server 8000

# Or with Node
npx serve .

# Or with deno
deno run --allow-net --allow-read https://deno.land/std/http/file_server.ts
```

Then open http://localhost:8000

## Sections

1. **Hero** — Eye-catching terminal demo with animated grid
2. **Features** — 6 capability cards with tags
3. **Install** — Two-column: install command + prerequisites
4. **Use Cases** — 4 mission profiles (Nomad, Clean Slate, Parallel Dimension, Remote Beast)
5. **Source** — GitHub links and project stats

## Customization

Update these before deploying:

1. `og:image` paths — switch to a PNG if you need better social preview support
2. Version number in hero badge
3. Product copy that should track the canonical CLI surface

## Target User

The ideal den user:
- Values reproducibility and declarative configs
- Uses Nix or Guix (or wants to)
- Loves the terminal and modern CLI tools (fish, helix, zellij)
- Wants to work from anywhere on any machine
- Appreciates functional programming concepts
- Enjoys tools that "just work" after initial setup
- Likely uses a tiling window manager
- Probably has opinions about dotfiles
- Into sci-fi, space exploration, or vintage tech aesthetics
