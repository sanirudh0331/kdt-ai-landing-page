# KdT AI Landing Page

A static landing page for KdT AI tools with Vercel-inspired theming, light/dark mode, and card-based navigation.

## Data Limitations

| Aspect | Details |
|--------|---------|
| **FDA Calendar** | Manually curated JSON data enriched with Perplexity API - may have gaps or delays |
| **Clinical Trials** | Data freshness depends on external sources, not real-time |
| **News Ticker** | RSS feeds from FDA, Reuters, STAT, etc. - may have propagation delays |
| **Investor Sentiment** | Feature disabled - StockTwits data was too noisy/unreliable |
| **Tool Links** | Static links to Railway deployments - may break if URLs change |

### Key Caveats
- **FDA calendar is manual**: PDUFA dates and drug info require manual updates
- **No live FDA API**: Calendar data is not pulled from FDA directly
- **RSS limitations**: News ticker depends on third-party RSS feed availability
- **Warmup required**: Railway services have 5-15 second cold starts without warmup pings

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
