# KdT AI Landing Page

A static landing page for KdT AI tools with Vercel-inspired theming, light/dark mode, and card-based navigation.

## Features

- Light/dark theme toggle with localStorage persistence
- System preference detection for initial theme
- Responsive design (mobile-first)
- Tailwind CSS via CDN
- No build step required

## AI Tools

| Tool | Description |
|------|-------------|
| Portfolio Timeline | Portfolio updates and competitive intelligence tracker |
| H-Index Tracker | Researcher database and h-index ranking |
| Talent Scout | AI talent scouting tool |
| Portfolio Relevance Tool | Portfolio relevance analysis |
| Conference Planner | AI conference planning assistant |

## Project Structure

```
KdT-ai-landing-page/
├── index.html          # Main landing page
├── static/
│   └── kdt-logo.png    # Logo
└── README.md           # This file
```

## Local Development

Simply open `index.html` in a browser:

```bash
open index.html
```

Or start a local server:

```bash
python -m http.server 8000
```

Then visit `http://localhost:8000`

## Adding New Tools

To add a new tool card, copy one of the existing card blocks in the grid and update:
1. The `href` attribute with the tool URL
2. The icon SVG and gradient colors
3. The title and description text
