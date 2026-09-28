export function duration(ms) {
    if (ms > 0 && ms < 1000) return '<1s';
    const seconds = Math.max(0, Math.floor(ms / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ${minutes % 60}m`;
    return `${Math.floor(hours / 24)}d ${hours % 24}h`;
}

// Piecewise RGB interpolation: 0% down is green, 5% amber, 25%+ red.
export function downtimeColor(fraction) {
    const stops = [[0, [24, 212, 59]], [0.05, [239, 192, 80]], [0.25, [244, 99, 112]]];
    const value = Math.max(0, Math.min(0.25, fraction));
    const [a, b] = value <= 0.05 ? stops.slice(0, 2) : stops.slice(1);
    const ratio = (value - a[0]) / (b[0] - a[0]);
    return `rgb(${a[1].map((channel, i) => Math.round(channel + (b[1][i] - channel) * ratio)).join(', ')})`;
}

export function summarize(logs, cutoff, now, segments = 60) {
    const intervals = logs.map(log => ({
        ...log, start: Math.max(cutoff, Date.parse(log.start_time)),
        end: Math.min(now, log.end_time ? Date.parse(log.end_time) : now),
    })).filter(log => Number.isFinite(log.start) && Number.isFinite(log.end) && log.end > log.start);
    const outages = intervals.filter(log => log.state === 'DOWN');
    const observed = intervals.reduce((sum, log) => sum + log.end - log.start, 0);
    const downtime = outages.reduce((sum, log) => sum + log.end - log.start, 0);
    const current = [...logs].reverse().find(log => !log.end_time && Date.parse(log.start_time) <= now);
    const width = (now - cutoff) / segments;
    const buckets = Array.from({length: segments}, (_, i) => {
        const start = cutoff + i * width;
        const end = start + width;
        let known = 0, down = 0;
        for (const log of intervals) {
            const overlap = Math.max(0, Math.min(end, log.end) - Math.max(start, log.start));
            known += overlap;
            if (log.state === 'DOWN') down += overlap;
        }
        return {start, end, known, down, fraction: known ? down / known : null, coverage: Math.min(1, known / width)};
    });
    return {outages, observed, downtime, longest: outages.reduce((longest, log) => Math.max(longest, log.end - log.start), 0),
        uptime: observed ? 100 * (1 - downtime / observed) : null, state: current?.state ?? 'UNKNOWN', buckets};
}
