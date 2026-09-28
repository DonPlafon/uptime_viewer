import {duration, downtimeColor, summarize} from './metrics.mjs';

let currentPeriod = 24;
let requestId = 0;
let controller;
let charts = [];
const dateTime = timestamp => new Date(timestamp).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit'});

async function fetchJSON(url, signal) {
    const response = await fetch(url, {signal});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

function renderService(service, status, pings, period) {
    const card = document.getElementById('service-template').content.firstElementChild.cloneNode(true);
    card.id = `service-${service.id}`;
    const set = (selector, value) => { card.querySelector(selector).textContent = value; };
    set('.service-name', service.name || service.url);
    const link = card.querySelector('.service-link');
    link.textContent = service.url;
    if (/^https?:\/\//i.test(service.url)) link.href = service.url;
    const now = Date.parse(status.now);
    const cutoff = Date.parse(status.cutoff);
    const stats = summarize(status.logs, cutoff, now);
    const stateClass = stats.state.toLowerCase();
    card.querySelector('.status-indicator').classList.add(stateClass);
    const state = card.querySelector('.current-status');
    state.classList.add(stateClass);
    state.textContent = {UP: 'Operational', DOWN: 'Unavailable', UNKNOWN: 'No data'}[stats.state];
    set('.uptime-percentage', stats.uptime === null ? 'N/A' : `${stats.uptime.toFixed(2)}%`);
    card.querySelector('.uptime-percentage').style.color = stats.uptime === null ? 'var(--muted)' : downtimeColor(1 - stats.uptime / 100);
    set('.outage-count', stats.observed ? stats.outages.length : 'N/A');
    set('.downtime-total', stats.observed ? duration(stats.downtime) : 'N/A');
    set('.longest-outage', stats.observed ? duration(stats.longest) : 'N/A');
    const validPings = pings.filter(p => Number.isFinite(p.ping_ms));
    // API buckets carry sample counts so partial hours are weighted correctly.
    const count = validPings.reduce((sum, p) => sum + (p.samples ?? 1), 0);
    set('.average-ping', count ? `${Math.round(validPings.reduce((sum, p) => sum + p.ping_ms * (p.samples ?? 1), 0) / count)} ms` : 'N/A');
    set('.start-label', period === 24 ? '24 hours ago' : period === 168 ? '7 days ago' : '30 days ago');

    const detail = card.querySelector('.segment-detail');
    stats.buckets.forEach(bucket => {
        const segment = document.createElement('button');
        segment.type = 'button';
        segment.className = `segment${bucket.coverage > 0 && bucket.coverage < 0.999 ? ' partial' : ''}`;
        if (bucket.fraction !== null) segment.style.backgroundColor = downtimeColor(bucket.fraction);
        const text = `${dateTime(bucket.start)} - ${dateTime(bucket.end)} | ${bucket.fraction === null ? 'No data' : `${(bucket.fraction * 100).toFixed(2)}% downtime (${duration(bucket.down)})${bucket.coverage < 0.999 ? ' | Partial data' : ''}`}`;
        segment.title = text;
        segment.setAttribute('aria-label', text);
        for (const event of ['mouseenter', 'focus', 'click']) segment.addEventListener(event, () => { detail.textContent = text; });
        segment.addEventListener('mouseleave', () => { if (document.activeElement !== segment) detail.textContent = ''; });
        segment.addEventListener('blur', () => { detail.textContent = ''; });
        card.querySelector('.uptime-segments').appendChild(segment);
    });

    set('.history-count', String(stats.outages.length));
    const list = card.querySelector('.outage-list');
    if (!stats.outages.length) {
        const empty = document.createElement('p');
        empty.className = 'empty-history';
        empty.textContent = stats.observed ? 'No outages in this period.' : 'No history yet.';
        list.appendChild(empty);
    }
    [...stats.outages].reverse().slice(0, 10).forEach(log => {
        const row = document.createElement('div');
        row.className = 'outage-row';
        const date = document.createElement('span');
        date.textContent = dateTime(log.start_time);
        const elapsed = document.createElement('span');
        elapsed.className = 'outage-duration';
        elapsed.textContent = duration(log.end - log.start);
        elapsed.title = 'Downtime within the selected period';
        const state = document.createElement('span');
        state.className = log.end_time ? 'resolved' : 'ongoing';
        state.textContent = log.end_time ? 'Resolved' : 'Ongoing';
        row.append(date, elapsed, state);
        list.appendChild(row);
    });
    if (stats.outages.length > 10) {
        const more = document.createElement('p');
        more.className = 'empty-history';
        more.textContent = `Showing the latest 10 of ${stats.outages.length} outages.`;
        list.appendChild(more);
    }
    card.querySelector('details').open = stats.state === 'DOWN';
    return {card, stats, pings: validPings};
}

function renderChart(card, pings, period) {
    const canvas = card.querySelector('canvas');
    if (!pings.length || !window.Chart) {
        canvas.hidden = true;
        const empty = card.querySelector('.chart-empty');
        empty.hidden = false;
        empty.textContent = pings.length ? 'Chart unavailable.' : 'No response samples yet.';
        return;
    }
    charts.push(new window.Chart(canvas, {
        type: 'bar',
        data: {
            labels: pings.map(p => new Date(p.time).toLocaleString([], period === 24 ? {hour: '2-digit', minute: '2-digit'} : {month: 'short', day: 'numeric'})),
            datasets: [{label: 'Average response time (ms)', data: pings.map(p => p.ping_ms),
                backgroundColor: pings.map(p => p.ping_ms > 1000 ? '#f46370' : p.ping_ms > 500 ? '#efc050' : '#6299ca'),
                borderRadius: 2, barPercentage: 0.75, categoryPercentage: 0.9}],
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: {legend: {display: false}, tooltip: {displayColors: false, callbacks: {label: context => `${Math.round(context.raw)} ms`}}},
            scales: {
                x: {grid: {display: false}, border: {display: false}, ticks: {color: '#9a9da6', font: {size: 10}, maxTicksLimit: 8, maxRotation: 0}},
                y: {beginAtZero: true, border: {display: false}, grid: {color: '#25272b'}, ticks: {color: '#9a9da6', font: {size: 10}, maxTicksLimit: 3}},
            },
        },
    }));
}

async function loadServices() {
    const id = ++requestId;
    controller?.abort();
    controller = new AbortController();
    const {signal} = controller;
    const timeout = setTimeout(() => controller?.signal === signal && controller.abort(), 15000);
    const period = currentPeriod;
    const container = document.getElementById('services-container');
    const error = document.getElementById('refresh-error');
    try {
        const services = await fetchJSON('/api/services', signal);
        const data = await Promise.all(services.map(async service => {
            const [status, ping] = await Promise.all([
                fetchJSON(`/api/status/${service.id}?hours=${period}`, signal),
                fetchJSON(`/api/ping/${service.id}?hours=${period}`, signal),
            ]);
            return {service, status, ping};
        }));
        if (id !== requestId) return;
        const rendered = data.map(({service, status, ping}) => renderService(service, status, ping.pings, period));
        const openIds = new Set([...container.querySelectorAll('details[open]')].map(detail => detail.closest('section').id));
        const focused = document.activeElement;
        const focusCard = focused?.closest('.service-card')?.id;
        const focusIndex = focused?.classList.contains('segment') ? [...focused.parentElement.children].indexOf(focused) : -1;
        charts.forEach(chart => chart.destroy());
        charts = [];
        container.replaceChildren(...rendered.map(item => item.card));
        if (!services.length) {
            const empty = document.createElement('div');
            empty.className = 'loading-state';
            empty.textContent = 'No services configured.';
            container.appendChild(empty);
        }
        for (const {card, pings} of rendered) {
            if (openIds.has(card.id)) card.querySelector('details').open = true;
            renderChart(card, pings, period);
        }
        if (focusCard) {
            const card = document.getElementById(focusCard);
            if (focusIndex >= 0) card?.querySelectorAll('.segment')[focusIndex]?.focus({preventScroll: true});
            else if (focused.tagName === 'SUMMARY') card?.querySelector('summary').focus({preventScroll: true});
        }
        document.getElementById('updated').textContent = `Updated ${new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`;
        error.hidden = true;
        document.querySelectorAll('.period-selector button').forEach(button => {
            button.classList.toggle('active', Number(button.dataset.period) === period);
            button.setAttribute('aria-pressed', String(Number(button.dataset.period) === period));
        });
        if (!container.dataset.loaded && location.hash.startsWith('#service-')) document.getElementById(location.hash.slice(1))?.scrollIntoView();
        container.dataset.loaded = 'true';
    } catch (err) {
        if (id !== requestId) return;
        error.textContent = container.dataset.loaded ? 'Refresh failed. Showing the last successful update.' : 'Failed to load services. Retrying shortly.';
        error.hidden = false;
        if (!container.dataset.loaded) container.replaceChildren();
    } finally {
        clearTimeout(timeout);
    }
}

document.querySelectorAll('.period-selector button').forEach(button => button.addEventListener('click', () => {
    currentPeriod = Number(button.dataset.period);
    loadServices();
}));
loadServices();
setInterval(() => { if (!document.hidden) loadServices(); }, 20000);
