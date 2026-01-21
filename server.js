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

// ============ FDA Calendar with Auto-Refresh ============

// Fetch and parse FDA calendar from BioPharmCatalyst
async function fetchFDAFromSource() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 20000);

    try {
        console.log('Fetching FDA calendar from BioPharmCatalyst...');
        const response = await fetch('https://www.biopharmcatalyst.com/calendars/fda-calendar', {
            signal: controller.signal,
            headers: {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
            }
        });
        clearTimeout(timeout);

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }

        const html = await response.text();
        return parseFDACalendarHTML(html);
    } catch (error) {
        clearTimeout(timeout);
        console.warn('Failed to fetch FDA calendar:', error.message);
        return null;
    }
}

// Parse FDA calendar HTML - multiple parsing strategies
function parseFDACalendarHTML(html) {
    const events = [];

    // Strategy 1: Look for JSON data embedded in page
    const jsonMatch = html.match(/window\.__NUXT__\s*=\s*(\{[\s\S]*?\});?\s*<\/script>/);
    if (jsonMatch) {
        try {
            // This is complex nested data, try to extract
            const nuxtData = jsonMatch[1];
            // Look for PDUFA patterns in the data
            const pdufaMatches = nuxtData.matchAll(/"date":"(\d{4}-\d{2}-\d{2})"[^}]*"company":"([^"]+)"[^}]*"drug":"([^"]+)"[^}]*"indication":"([^"]+)"/g);
            for (const match of pdufaMatches) {
                events.push({
                    type: 'PDUFA',
                    date: match[1],
                    company: match[2],
                    drug: match[3],
                    indication: match[4]
                });
            }
        } catch (e) {
            console.warn('Failed to parse embedded JSON');
        }
    }

    // Strategy 2: Parse HTML table rows
    if (events.length === 0) {
        // Look for rows with date patterns
        const rowRegex = /<tr[^>]*>([\s\S]*?)<\/tr>/gi;
        let rowMatch;

        while ((rowMatch = rowRegex.exec(html)) !== null && events.length < 30) {
            const rowContent = rowMatch[1];

            // Extract cells
            const cells = [];
            const cellRegex = /<td[^>]*>([\s\S]*?)<\/td>/gi;
            let cellMatch;
            while ((cellMatch = cellRegex.exec(rowContent)) !== null) {
                cells.push(stripHtml(cellMatch[1]));
            }

            if (cells.length >= 4) {
                // Try to find a date in the first cell
                const dateMatch = cells[0].match(/(\w{3,9})\s+(\d{1,2}),?\s*(\d{4})?/i);
                if (dateMatch) {
                    const months = {
                        'january': '01', 'february': '02', 'march': '03', 'april': '04',
                        'may': '05', 'june': '06', 'july': '07', 'august': '08',
                        'september': '09', 'october': '10', 'november': '11', 'december': '12',
                        'jan': '01', 'feb': '02', 'mar': '03', 'apr': '04',
                        'jun': '06', 'jul': '07', 'aug': '08', 'sep': '09',
                        'oct': '10', 'nov': '11', 'dec': '12'
                    };

                    const monthKey = dateMatch[1].toLowerCase();
                    const month = months[monthKey];
                    const day = dateMatch[2].padStart(2, '0');
                    const year = dateMatch[3] || new Date().getFullYear().toString();

                    if (month && cells[1] && cells[2]) {
                        const type = rowContent.toLowerCase().includes('adcom') ? 'AdCom' : 'PDUFA';
                        events.push({
                            type,
                            company: cells[1].split(/[(\[]/)[0].trim(),
                            drug: cells[2].trim(),
                            indication: cells[3] ? cells[3].trim() : '',
                            date: `${year}-${month}-${day}`
                        });
                    }
                }
            }
        }
    }

    console.log(`Parsed ${events.length} FDA events`);
    return events.length > 0 ? events : null;
}

// Check and refresh FDA calendar if needed
async function checkAndRefreshFDA() {
    try {
        const currentData = JSON.parse(fs.readFileSync(FDA_CALENDAR_PATH, 'utf8'));
        const lastUpdated = new Date(currentData.lastUpdated).getTime();
        const now = Date.now();

        // Check if 7 days have passed
        if (now - lastUpdated < FDA_REFRESH_INTERVAL) {
            const daysUntilRefresh = Math.ceil((FDA_REFRESH_INTERVAL - (now - lastUpdated)) / (24 * 60 * 60 * 1000));
            console.log(`FDA calendar is fresh. Next refresh in ${daysUntilRefresh} days.`);
            return;
        }

        console.log('FDA calendar is stale. Attempting refresh...');
        const newEvents = await fetchFDAFromSource();

        if (newEvents && newEvents.length > 0) {
            // Filter to only future events
            const today = new Date().toISOString().split('T')[0];
            const futureEvents = newEvents.filter(e => e.date >= today);

            if (futureEvents.length > 0) {
                const updatedData = {
                    lastUpdated: new Date().toISOString().split('T')[0],
                    events: futureEvents.sort((a, b) => a.date.localeCompare(b.date))
                };

                fs.writeFileSync(FDA_CALENDAR_PATH, JSON.stringify(updatedData, null, 2));
                console.log(`FDA calendar updated with ${futureEvents.length} events.`);
            } else {
                console.log('No future events found, keeping existing data.');
            }
        } else {
            console.log('Could not fetch new FDA data, keeping existing data.');
        }
    } catch (error) {
        console.error('Error checking FDA calendar:', error.message);
    }
}

// API endpoint for FDA calendar
app.get('/api/fda-calendar', (req, res) => {
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
