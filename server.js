const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// CORS middleware for API routes (allow tool pages to call Neo API)
app.use('/api', (req, res, next) => {
    const allowedOrigins = [
        'https://kdt-ai-landing.up.railway.app',
        'https://kdttalentscout.up.railway.app',
        'https://kdtportfoliobeacon.up.railway.app',
        'https://kdtgrantstracker.up.railway.app',
        'https://kdtpatentwarrior.up.railway.app',
        'http://localhost:3000',
        'http://localhost:5000'
    ];
    const origin = req.headers.origin;
    if (allowedOrigins.includes(origin)) {
        res.setHeader('Access-Control-Allow-Origin', origin);
    }
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
    if (req.method === 'OPTIONS') {
        return res.sendStatus(200);
    }
    next();
});

// Parse JSON bodies for login endpoint
app.use(express.json());

// Auth credentials from environment variables (with fallback for development)
const AUTH_USERNAME = process.env.KDT_AUTH_USERNAME || 'kdtai';
const AUTH_PASSWORD = process.env.KDT_AUTH_PASSWORD || 'kdtftw';

// Login endpoint - validates credentials server-side
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;

    if (username === AUTH_USERNAME && password === AUTH_PASSWORD) {
        res.json({ success: true });
    } else {
        res.status(401).json({ success: false, error: 'Invalid credentials' });
    }
});

// Cache for RSS feeds
let newsCache = {
    data: [],
    timestamp: 0
};
const NEWS_CACHE_DURATION = 15 * 60 * 1000; // 15 minutes

// FDA calendar paths
const FDA_CALENDAR_PATH = path.join(__dirname, 'static', 'fda-calendar.json');
const FDA_REFRESH_INTERVAL = 7 * 24 * 60 * 60 * 1000; // 7 days

// Perplexity API for enriching FDA data
const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;

// Query Perplexity for drug/indication info
async function enrichWithPerplexity(company, ticker, date) {
    if (!PERPLEXITY_API_KEY) {
        console.warn('No Perplexity API key configured');
        return null;
    }

    const query = `What drug is ${company} (${ticker}) seeking FDA approval for with PDUFA date ${date}? Give me just the drug name and the medical indication/condition it treats. Be concise - just the drug name and indication, nothing else.`;

    try {
        const response = await fetch('https://api.perplexity.ai/chat/completions', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${PERPLEXITY_API_KEY}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                model: 'sonar',
                messages: [
                    {
                        role: 'system',
                        content: 'You are a helpful assistant that provides concise information about FDA drug approvals. Respond with just the drug name and indication in this format: "Drug: [name], Indication: [condition]". If you cannot find the information, respond with "Unknown".'
                    },
                    {
                        role: 'user',
                        content: query
                    }
                ],
                max_tokens: 150
            })
        });

        if (!response.ok) {
            console.warn(`Perplexity API error: ${response.status}`);
            return null;
        }

        const data = await response.json();
        const content = data.choices?.[0]?.message?.content || '';

        // Parse the response and clean up citation markers
        const cleanText = (text) => text
            .replace(/\*\*/g, '')           // Remove bold markers
            .replace(/\[\d+\]/g, '')        // Remove citation numbers [1], [2], etc.
            .replace(/\s+/g, ' ')           // Normalize whitespace
            .trim();

        const drugMatch = content.match(/Drug:\s*([^,\n]+)/i);
        const indicationMatch = content.match(/Indication:\s*([^\n]+)/i);

        if (drugMatch || indicationMatch) {
            return {
                drug: drugMatch ? cleanText(drugMatch[1]) : '',
                indication: indicationMatch ? cleanText(indicationMatch[1]) : ''
            };
        }

        // Try to extract from less structured response
        if (content && content.toLowerCase() !== 'unknown') {
            // First sentence often has the drug name
            const firstSentence = content.split('.')[0];
            return {
                drug: '',
                indication: firstSentence.substring(0, 80).trim()
            };
        }

        return null;
    } catch (error) {
        console.warn('Perplexity API error:', error.message);
        return null;
    }
}

// Enrich multiple events with Perplexity (with rate limiting)
async function enrichFDAEvents(events, limit = 12) {
    const eventsToEnrich = events.slice(0, limit);
    const enrichedEvents = [];

    console.log(`Enriching ${eventsToEnrich.length} FDA events with Perplexity...`);

    for (const event of eventsToEnrich) {
        // Add small delay to avoid rate limiting
        await new Promise(resolve => setTimeout(resolve, 500));

        const enrichment = await enrichWithPerplexity(event.company, event.ticker, event.date);

        if (enrichment) {
            enrichedEvents.push({
                ...event,
                drug: enrichment.drug || event.drug,
                indication: enrichment.indication || event.indication
            });
            console.log(`  ✓ ${event.company}: ${enrichment.drug || 'no drug'} - ${enrichment.indication || 'no indication'}`);
        } else {
            enrichedEvents.push(event);
            console.log(`  ✗ ${event.company}: using fallback data`);
        }
    }

    // Add remaining events without enrichment
    const remaining = events.slice(limit);
    return [...enrichedEvents, ...remaining];
}

// RSS feed URLs
const RSS_FEEDS = [
    'https://www.fiercebiotech.com/rss/xml',
    'https://www.biopharmadive.com/feeds/news/',
    'https://endpts.com/feed/'
];

// Strip HTML tags and decode entities
function stripHtml(str) {
    return str
        .replace(/<!\[CDATA\[(.*?)\]\]>/gs, '$1')
        .replace(/<[^>]*>/g, '')
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&nbsp;/g, ' ')
        .trim();
}

// Simple XML parser for RSS items
function parseRSSItems(xml) {
    const items = [];
    const itemRegex = /<item>([\s\S]*?)<\/item>/g;
    const titleRegex = /<title>([\s\S]*?)<\/title>/;
    const linkRegex = /<link>([\s\S]*?)<\/link>|<link[^>]*href=["']([^"']+)["']/;

    let match;
    while ((match = itemRegex.exec(xml)) !== null && items.length < 5) {
        const itemContent = match[1];
        const titleMatch = itemContent.match(titleRegex);
        const linkMatch = itemContent.match(linkRegex);

        let title = titleMatch ? stripHtml(titleMatch[1]) : '';
        let link = linkMatch ? stripHtml(linkMatch[1] || linkMatch[2] || '') : '';

        if (title && title.length > 0) {
            items.push({ title, link });
        }
    }
    return items;
}

// Fetch RSS feed with timeout
async function fetchFeed(url) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);

    try {
        const response = await fetch(url, {
            signal: controller.signal,
            headers: {
                'User-Agent': 'Mozilla/5.0 (compatible; KdT-AI-NewsReader/1.0)'
            }
        });
        clearTimeout(timeout);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const text = await response.text();
        return parseRSSItems(text);
    } catch (error) {
        clearTimeout(timeout);
        console.warn(`Failed to fetch ${url}:`, error.message);
        return [];
    }
}

// API endpoint for biotech news
app.get('/api/news', async (req, res) => {
    const now = Date.now();

    // Return cached data if still fresh
    if (newsCache.data.length > 0 && (now - newsCache.timestamp) < NEWS_CACHE_DURATION) {
        return res.json({ news: newsCache.data, cached: true });
    }

    // Fetch all feeds in parallel
    const results = await Promise.all(RSS_FEEDS.map(fetchFeed));
    const allNews = results.flat();

    // Update cache if we got any news
    if (allNews.length > 0) {
        newsCache = {
            data: allNews,
            timestamp: now
        };
    }

    // Return fresh data or stale cache if fetch failed
    const newsToReturn = allNews.length > 0 ? allNews : newsCache.data;

    res.json({
        news: newsToReturn,
        cached: allNews.length === 0 && newsCache.data.length > 0
    });
});

// ============ FDA Calendar from Google Calendar ICS Feeds ============

// Google Calendar ICS feed URLs (from FDA Tracker's public calendars)
const FDA_CALENDAR_FEEDS = {
    pdufa: 'https://calendar.google.com/calendar/ical/5dso8589486irtj53sdkr4h6ek%40group.calendar.google.com/public/basic.ics',
    adcom: 'https://calendar.google.com/calendar/ical/evgohovm2m3tuvqakdf4hfeq84%40group.calendar.google.com/public/basic.ics'
};

// Cache for FDA calendar data
let fdaCache = {
    data: null,
    timestamp: 0
};

// Parse ICS format to extract events
function parseICSEvents(icsText, eventType) {
    const events = [];
    const eventBlocks = icsText.split('BEGIN:VEVENT');

    for (let i = 1; i < eventBlocks.length; i++) {
        const block = eventBlocks[i];
        const endIndex = block.indexOf('END:VEVENT');
        if (endIndex === -1) continue;

        const eventContent = block.substring(0, endIndex);

        // Extract date
        const dateMatch = eventContent.match(/DTSTART;VALUE=DATE:(\d{4})(\d{2})(\d{2})/);
        if (!dateMatch) continue;

        const date = `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}`;

        // Only include future events (within next 365 days)
        const eventDate = new Date(date);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        const oneYearOut = new Date(today);
        oneYearOut.setFullYear(oneYearOut.getFullYear() + 1);

        if (eventDate < today || eventDate > oneYearOut) continue;

        // Extract summary (contains ticker and company name)
        const summaryMatch = eventContent.match(/SUMMARY:(.+?)(?:\r?\n[A-Z]|$)/s);
        if (!summaryMatch) continue;

        const summary = summaryMatch[1].replace(/\r?\n\s*/g, '').trim();

        // Parse ticker and company from summary
        // Format is usually: "TICKER Company Name PDUFA" or "TICKER Company Name FDA AdCom"
        const summaryParts = summary.replace(/ PDUFA$| FDA AdCom$/i, '').trim();
        const tickerMatch = summaryParts.match(/^([A-Z0-9]{2,5})\s+(.+)$/);

        let ticker = '';
        let company = summaryParts;
        if (tickerMatch) {
            ticker = tickerMatch[1];
            company = tickerMatch[2].replace(/,?\s*(Inc\.?|Corp\.?|Ltd\.?|plc|AG|SA|N\.V\.?)?\s*$/i, '').trim();
        }

        // Extract description (contains drug and indication details)
        const descMatch = eventContent.match(/DESCRIPTION:(.+?)(?:\r?\n[A-Z]|$)/s);
        let description = '';
        if (descMatch) {
            description = descMatch[1]
                .replace(/\\n/g, ' ')
                .replace(/\\,/g, ',')
                .replace(/\r?\n\s*/g, '')
                .trim();
        }

        // Try to extract drug name and indication from description
        let drug = '';
        let indication = '';

        // Common patterns in descriptions
        const drugPatterns = [
            /for\s+([A-Za-z0-9-]+(?:\s+[A-Za-z0-9-]+)?)\s*[\(,]/i,
            /NDA.*?for\s+([A-Za-z0-9-]+)/i,
            /BLA.*?for\s+([A-Za-z0-9-]+)/i,
            /application.*?for\s+([A-Za-z0-9-]+)/i
        ];

        for (const pattern of drugPatterns) {
            const match = description.match(pattern);
            if (match) {
                drug = match[1].trim();
                break;
            }
        }

        // Extract URL from description (press release link)
        let url = '';
        const urlMatch = description.match(/https?:\/\/[^\s\)]+/);
        if (urlMatch) {
            url = urlMatch[0].replace(/\\,/g, ',').replace(/\s/g, '');
        }

        // Try to extract indication - focus on disease/condition names only
        const indicationPatterns = [
            /treatment\s+of\s+(?:adult\s+)?(?:patients\s+with\s+)?([^,\.]{8,60})/i,
            /for\s+(?:the\s+)?treatment\s+of\s+([^,\.]{8,60})/i,
            /indication[^:]*(?:is|for|:)\s*([^,\.]{8,60})/i,
            /for\s+([^,\.]*?(?:allergic|anaphylaxis|cancer|disease|syndrome|disorder)[^,\.]{0,30})/i
        ];

        for (const pattern of indicationPatterns) {
            const match = description.match(pattern);
            if (match) {
                // Clean up the indication - just the condition
                indication = match[1]
                    .replace(/\s+/g, ' ')
                    .replace(/^(adult |pediatric |patients with |the )/gi, '')
                    // Remove trailing junk
                    .replace(/\s+(FDA|PDUFA|Phase|trial|study|data|review|•|http).*$/i, '')
                    .replace(/\s+(and|or|with|who|that)\s*$/i, '')
                    .trim();

                // Skip if too short or just noise
                if (indication.length < 8 || /^(the|a|an|for|in)\s/i.test(indication)) {
                    indication = '';
                    continue;
                }

                // Capitalize first letter
                indication = indication.charAt(0).toUpperCase() + indication.slice(1);

                // Limit length
                if (indication.length > 55) {
                    indication = indication.substring(0, 52) + '...';
                }
                break;
            }
        }

        events.push({
            type: eventType,
            ticker,
            company,
            drug: drug || '',
            indication: indication || '',
            url,
            date
        });
    }

    return events;
}

// Fetch ICS feed
async function fetchICSFeed(url, type) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    try {
        const response = await fetch(url, {
            signal: controller.signal,
            headers: {
                'User-Agent': 'Mozilla/5.0 (compatible; KdT-AI/1.0)'
            }
        });
        clearTimeout(timeout);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const text = await response.text();
        return parseICSEvents(text, type);
    } catch (error) {
        clearTimeout(timeout);
        console.warn(`Failed to fetch ${type} calendar:`, error.message);
        return [];
    }
}

// Fetch all FDA calendar data
async function fetchFDACalendars() {
    console.log('Fetching FDA calendars from Google Calendar ICS feeds...');

    const [pdufaEvents, adcomEvents] = await Promise.all([
        fetchICSFeed(FDA_CALENDAR_FEEDS.pdufa, 'PDUFA'),
        fetchICSFeed(FDA_CALENDAR_FEEDS.adcom, 'AdCom')
    ]);

    const allEvents = [...pdufaEvents, ...adcomEvents];

    // Sort by date
    allEvents.sort((a, b) => a.date.localeCompare(b.date));

    console.log(`Fetched ${pdufaEvents.length} PDUFA and ${adcomEvents.length} AdCom events`);

    return allEvents;
}

// Check and refresh FDA calendar
async function checkAndRefreshFDA() {
    try {
        let needsRefresh = true;

        // Check if we have cached data
        try {
            const currentData = JSON.parse(fs.readFileSync(FDA_CALENDAR_PATH, 'utf8'));
            const lastUpdated = new Date(currentData.lastUpdated).getTime();
            const now = Date.now();

            if (now - lastUpdated < FDA_REFRESH_INTERVAL) {
                const daysUntilRefresh = Math.ceil((FDA_REFRESH_INTERVAL - (now - lastUpdated)) / (24 * 60 * 60 * 1000));
                console.log(`FDA calendar is fresh. Next refresh in ${daysUntilRefresh} days.`);
                needsRefresh = false;
            }
        } catch (e) {
            // No existing data, need to fetch
            needsRefresh = true;
        }

        if (!needsRefresh) return;

        console.log('Refreshing FDA calendar from Google Calendar...');
        let events = await fetchFDACalendars();

        if (events.length > 0) {
            // Enrich top 12 events with Perplexity for drug/indication details
            if (PERPLEXITY_API_KEY) {
                events = await enrichFDAEvents(events, 12);
            } else {
                console.log('Skipping Perplexity enrichment (no API key)');
            }

            const updatedData = {
                lastUpdated: new Date().toISOString().split('T')[0],
                source: 'Google Calendar ICS (FDA Tracker) + Perplexity AI',
                events
            };

            fs.writeFileSync(FDA_CALENDAR_PATH, JSON.stringify(updatedData, null, 2));
            console.log(`FDA calendar updated with ${events.length} events.`);

            // Update memory cache
            fdaCache = {
                data: updatedData,
                timestamp: Date.now()
            };
        } else {
            console.log('No events fetched, keeping existing data.');
        }
    } catch (error) {
        console.error('Error refreshing FDA calendar:', error.message);
    }
}

// API endpoint for FDA calendar
app.get('/api/fda-calendar', async (req, res) => {
    // Check for force refresh parameter
    if (req.query.refresh === 'true') {
        console.log('Force refresh requested for FDA calendar');
        // Reset the lastUpdated to force a refresh
        try {
            const currentData = JSON.parse(fs.readFileSync(FDA_CALENDAR_PATH, 'utf8'));
            currentData.lastUpdated = '2000-01-01'; // Force stale
            fs.writeFileSync(FDA_CALENDAR_PATH, JSON.stringify(currentData, null, 2));
        } catch (e) {}
        await checkAndRefreshFDA();
    }

    try {
        const data = JSON.parse(fs.readFileSync(FDA_CALENDAR_PATH, 'utf8'));
        return res.json(data);
    } catch (error) {
        return res.json({ events: [], lastUpdated: null, error: 'No data available' });
    }
});

// Neo MCP proxy - forwards to Python FastAPI service
// Hardcoded to Neo v1 until Leo v2 is fully tested
const NEO_SERVICE_URL = 'https://kdtneo.up.railway.app';

app.get('/api/neo-search', async (req, res) => {
    try {
        const queryParams = new URLSearchParams(req.query).toString();
        const response = await fetch(`${NEO_SERVICE_URL}/api/neo-search?${queryParams}`, {
            headers: { 'Accept': 'application/json' },
            timeout: 30000
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Neo service error' }));
            return res.status(response.status).json(error);
        }

        const data = await response.json();
        res.json(data);
    } catch (error) {
        console.error('Neo search proxy error:', error.message);
        res.status(503).json({
            error: 'Neo search unavailable',
            detail: 'The search service is not running. Start it with: python neo_mcp/server.py'
        });
    }
});

// Neo Ask proxy - AI-powered Q&A (POST with longer timeout for LLM)
app.post('/api/neo-ask', async (req, res) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 60000); // 60 second timeout for LLM

    try {
        const response = await fetch(`${NEO_SERVICE_URL}/api/neo-ask`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(req.body),
            signal: controller.signal
        });
        clearTimeout(timeout);

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Neo service error' }));
            return res.status(response.status).json(error);
        }

        const data = await response.json();
        res.json(data);
    } catch (error) {
        clearTimeout(timeout);
        console.error('Neo ask proxy error:', error.message);

        if (error.name === 'AbortError') {
            res.status(504).json({
                error: 'Request timeout',
                detail: 'The AI took too long to respond. Please try again.'
            });
        } else {
            res.status(503).json({
                error: 'AI Q&A unavailable',
                detail: 'The Neo service is not running. Start it with: python neo_mcp/server.py'
            });
        }
    }
});

// Neo SQL Agent proxy - Direct database access with agentic reasoning
app.post('/api/neo-analyze', async (req, res) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 120000); // 2 minute timeout for multi-step analysis

    try {
        const response = await fetch(`${NEO_SERVICE_URL}/api/neo-analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            body: JSON.stringify(req.body),
            signal: controller.signal
        });
        clearTimeout(timeout);

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Neo agent error' }));
            return res.status(response.status).json(error);
        }

        const data = await response.json();
        res.json(data);
    } catch (error) {
        clearTimeout(timeout);
        console.error('Neo analyze proxy error:', error.message);

        if (error.name === 'AbortError') {
            res.status(504).json({
                error: 'Request timeout',
                detail: 'The analysis took too long. Try a simpler question.'
            });
        } else {
            res.status(503).json({
                error: 'Neo SQL agent unavailable',
                detail: 'The database service is not running.'
            });
        }
    }
});

// Neo SQL Agent streaming proxy - Server-Sent Events for real-time status
app.post('/api/neo-analyze-stream', async (req, res) => {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 180000); // 3 minute timeout for streaming

    try {
        const response = await fetch(`${NEO_SERVICE_URL}/api/neo-analyze-stream`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream'
            },
            body: JSON.stringify(req.body),
            signal: controller.signal
        });
        clearTimeout(timeout);

        if (!response.ok) {
            const error = await response.json().catch(() => ({ error: 'Neo agent error' }));
            return res.status(response.status).json(error);
        }

        // Set SSE headers
        res.setHeader('Content-Type', 'text/event-stream');
        res.setHeader('Cache-Control', 'no-cache');
        res.setHeader('Connection', 'keep-alive');
        res.setHeader('X-Accel-Buffering', 'no'); // Disable nginx buffering

        // Pipe the stream through
        const reader = response.body.getReader();

        const pump = async () => {
            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) {
                        res.end();
                        break;
                    }
                    res.write(value);
                }
            } catch (error) {
                console.error('Stream pump error:', error.message);
                res.end();
            }
        };

        pump();

        // Handle client disconnect
        req.on('close', () => {
            reader.cancel();
        });

    } catch (error) {
        clearTimeout(timeout);
        console.error('Neo streaming proxy error:', error.message);

        if (error.name === 'AbortError') {
            res.status(504).json({
                error: 'Request timeout',
                detail: 'The analysis took too long. Try a simpler question.'
            });
        } else {
            res.status(503).json({
                error: 'Neo SQL agent unavailable',
                detail: 'The database service is not running.'
            });
        }
    }
});

app.get('/api/neo-stats', async (req, res) => {
    try {
        const response = await fetch(`${NEO_SERVICE_URL}/api/neo-stats`, {
            headers: { 'Accept': 'application/json' }
        });

        if (!response.ok) {
            return res.status(response.status).json({ error: 'Neo service error' });
        }

        const data = await response.json();
        res.json(data);
    } catch (error) {
        res.status(503).json({ error: 'Neo stats unavailable' });
    }
});

// Serve static files
app.use(express.static(path.join(__dirname)));

// Fallback to index.html for SPA routing
app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
    console.log(`KdT AI server running on port ${PORT}`);

    // Check FDA calendar on startup
    checkAndRefreshFDA();

    // Check daily for FDA refresh
    setInterval(checkAndRefreshFDA, 24 * 60 * 60 * 1000);
});
