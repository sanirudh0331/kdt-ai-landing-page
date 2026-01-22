const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

// Cache for RSS feeds
let newsCache = {
    data: [],
    timestamp: 0
};
const NEWS_CACHE_DURATION = 15 * 60 * 1000; // 15 minutes

// FDA calendar paths
const FDA_CALENDAR_PATH = path.join(__dirname, 'static', 'fda-calendar.json');
const FDA_REFRESH_INTERVAL = 7 * 24 * 60 * 60 * 1000; // 7 days

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

        // Try to extract indication with expanded patterns
        const indicationPatterns = [
            /treatment\s+of\s+(?:adult\s+)?(?:patients\s+with\s+)?([^\.]{10,100})/i,
            /for\s+(?:the\s+)?treatment\s+of\s+([^\.]{10,100})/i,
            /indicated?\s+for\s+(?:the\s+)?(?:treatment\s+of\s+)?([^\.]{10,100})/i,
            /for\s+(?:use\s+in\s+)?(?:patients\s+with\s+)?([^\.]*?(?:cancer|carcinoma|lymphoma|leukemia|myeloma|disease|disorder|syndrome|deficiency|anemia|arthritis|diabetes|hypertension|infection)[^\.]{0,50})/i,
            /proposed\s+indication[^:]*:\s*([^\.]+)/i,
            /for\s+([^\.]*?(?:allergic|anaphylaxis|epilepsy|seizure|pain|inflammation|psoriasis|eczema|asthma|COPD|HIV|hepatitis|obesity)[^\.]{0,30})/i
        ];

        for (const pattern of indicationPatterns) {
            const match = description.match(pattern);
            if (match) {
                // Clean up the indication text
                indication = match[1]
                    .replace(/\s+/g, ' ')
                    .replace(/^(adult |pediatric )/i, '')
                    .trim();
                // Remove trailing incomplete phrases
                indication = indication.replace(/\s+(and|or|with|who|that|in|for)\s*$/i, '').trim();
                if (indication.length > 100) {
                    indication = indication.substring(0, 97) + '...';
                }
                break;
            }
        }

        // Skip generic fallback - leave empty if no real indication found
        // The frontend will hide empty indications

        events.push({
            type: eventType,
            ticker,
            company,
            drug: drug || '',
            indication: indication || '',
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
        const events = await fetchFDACalendars();

        if (events.length > 0) {
            const updatedData = {
                lastUpdated: new Date().toISOString().split('T')[0],
                source: 'Google Calendar ICS (FDA Tracker)',
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
