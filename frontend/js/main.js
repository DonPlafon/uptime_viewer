let currentPeriod = 24;
const charts = {};

async function init() {
    setupPeriodSelectors();
    await loadServices();
}

function setupPeriodSelectors() {
    document.querySelectorAll('.period-selector button').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            document.querySelectorAll('.period-selector button').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');
            currentPeriod = parseInt(e.target.dataset.period);
            await loadServices();
        });
    });
}

async function loadServices() {
    const container = document.getElementById('services-container');
    container.innerHTML = '<div class="loading-state">Loading data...</div>';

    try {
        const res = await fetch('/api/services');
        const services = await res.json();

        container.innerHTML = '';

        for (const service of services) {
            await renderService(service, container);
        }
    } catch (e) {
        container.innerHTML = '<div class="loading-state" style="color: var(--color-down)">Failed to load services.</div>';
    }
}

async function renderService(service, container) {
    const template = document.getElementById('service-template').content.cloneNode(true);
    const card = template.querySelector('.service-card');

    card.querySelector('.service-name').textContent = service.name;
    const link = card.querySelector('.service-link');
    link.href = service.url;
    link.title = service.url;

    const startLabel = card.querySelector('.start-label');
    if (currentPeriod === 24) startLabel.textContent = '24 hours ago';
    else if (currentPeriod === 168) startLabel.textContent = '7 days ago';
    else startLabel.textContent = '30 days ago';

    container.appendChild(card);

    const [statusRes, pingRes] = await Promise.all([
        fetch(`/api/status/${service.id}?hours=${currentPeriod}`),
        fetch(`/api/ping/${service.id}?hours=${currentPeriod}`)
    ]);

    const statusData = await statusRes.json();
    const pingData = await pingRes.json();

    processStatusData(card, statusData.logs);
    renderPingChart(card, service, pingData.pings);
}

function processStatusData(card, logs) {
    const now = new Date();
    const cutoff = new Date(now.getTime() - (currentPeriod * 60 * 60 * 1000));

    let totalDowntimeMs = 0;
    const activeIntervals = [];
    let lastState = 'UP';
    let isCurrentlyUp = true;

    if (logs.length > 0) {
        lastState = logs[logs.length - 1].state;
        isCurrentlyUp = (lastState === 'UP');
    }

    const indicator = card.querySelector('.status-indicator');
    if (logs.length === 0) {
        indicator.className = 'status-indicator';
    } else if (isCurrentlyUp) {
        indicator.className = 'status-indicator up';
    } else {
        indicator.className = 'status-indicator down';
    }

    logs.forEach(log => {
        if (log.state === 'DOWN') {
            const startStr = log.start_time;
            const start = new Date(startStr);
            const end = log.end_time ? new Date(log.end_time) : now;

            const effStart = start < cutoff ? cutoff : start;
            if (end > cutoff) {
                totalDowntimeMs += (end - effStart);
                activeIntervals.push({ start: effStart, end: end });
            }
        }
    });

    const totalMs = now - cutoff;
    const uptimePct = ((totalMs - totalDowntimeMs) / totalMs) * 100;

    const pctEl = card.querySelector('.uptime-percentage');
    pctEl.textContent = `${uptimePct.toFixed(2)}% Uptime`;
    if (uptimePct >= 99) {
        pctEl.className = 'uptime-percentage';
    } else if (uptimePct >= 95) {
        pctEl.className = 'uptime-percentage warning';
    } else {
        pctEl.className = 'uptime-percentage danger';
    }

    const dtEl = card.querySelector('.downtime-total');
    let dtMins = Math.round(totalDowntimeMs / 60000);
    if (dtMins < 60) dtEl.textContent = `${dtMins}m Downtime`;
    else if (dtMins < 1440) dtEl.textContent = `${(dtMins / 60).toFixed(1)}h Downtime`;
    else dtEl.textContent = `${(dtMins / 1440).toFixed(1)}d Downtime`;

    const NUM_SEGMENTS = 60;
    const segmentsContainer = card.querySelector('.uptime-segments');
    const segmentDuration = totalMs / NUM_SEGMENTS;

    for (let i = 0; i < NUM_SEGMENTS; i++) {
        const segStart = new Date(cutoff.getTime() + (i * segmentDuration));
        const segEnd = new Date(segStart.getTime() + segmentDuration);

        let isDown = false;
        let isUnknown = logs.length === 0;

        for (const intv of activeIntervals) {
            if (intv.start < segEnd && intv.end > segStart) {
                isDown = true;
                break;
            }
        }

        const segEl = document.createElement('div');
        segEl.className = 'segment ' + (isUnknown ? '' : (isDown ? 'down' : 'up'));

        segEl.title = `${segStart.toLocaleString()} - ${isDown ? 'DOWN' : 'UP'}`;
        segmentsContainer.appendChild(segEl);
    }
}

function renderPingChart(card, service, pings) {
    const canvas = card.querySelector('.ping-chart');
    const ctx = canvas.getContext('2d');

    if (charts[service.id]) {
        charts[service.id].destroy();
    }

    Chart.defaults.color = '#8b949e';
    Chart.defaults.font.family = "'Inter', sans-serif";

    const labels = pings.map(p => {
        const d = new Date(p.time);
        return currentPeriod <= 24 ?
            d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) :
            d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    });

    const data = pings.map(p => p.ping_ms);
    const bgColors = data.map(ping =>
        ping > 1000 ? '#da3633' :
            ping > 500 ? '#d29922' : '#238636'
    );

    charts[service.id] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Avg Ping (ms)',
                data: data,
                backgroundColor: bgColors,
                borderRadius: 2,
                barPercentage: 0.8,
                categoryPercentage: 0.9
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#161b22',
                    titleColor: '#c9d1d9',
                    bodyColor: '#c9d1d9',
                    borderColor: '#30363d',
                    borderWidth: 1,
                    displayColors: false,
                    callbacks: {
                        label: function (context) {
                            return Math.round(context.raw) + ' ms';
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false, drawBorder: false },
                    ticks: { maxTicksLimit: 8, autoSkip: true }
                },
                y: {
                    grid: { color: '#30363d', drawBorder: false },
                    beginAtZero: true
                }
            }
        }
    });
}

document.addEventListener('DOMContentLoaded', init);
