import assert from 'node:assert/strict';
import {test} from 'node:test';
import {duration, downtimeColor, summarize} from '../frontend/js/metrics.mjs';

const now = Date.parse('2026-09-27T12:00:00Z');
const cutoff = now - 86400000;
const log = (state, start, end = null) => ({state, start_time: new Date(start).toISOString(), end_time: end === null ? null : new Date(end).toISOString()});

test('short outages retain seconds, including subsecond values', () => {
    assert.equal(duration(2000), '2s');
    assert.equal(duration(59000), '59s');
    assert.equal(duration(61000), '1m 1s');
    assert.equal(duration(500), '<1s');
});
test('no observations are unknown, not 100% up', () => {
    const result = summarize([], cutoff, now);
    assert.equal(result.uptime, null);
    assert.equal(result.state, 'UNKNOWN');
    assert(result.buckets.every(bucket => bucket.fraction === null));
});
test('new services do not assume uptime before first observation', () => {
    const result = summarize([log('DOWN', now - 10000)], cutoff, now);
    assert.equal(result.uptime, 0);
    assert.equal(result.observed, 10000);
    assert.equal(result.outages.length, 1);
    assert.equal(result.buckets[0].fraction, null);
    assert(result.buckets.at(-1).coverage < 1);
});
test('outages crossing the period are clipped and counted once', () => {
    const result = summarize([log('DOWN', cutoff - 5000, cutoff + 2000), log('UP', cutoff + 2000)], cutoff, now);
    assert.equal(result.downtime, 2000);
    assert.equal(result.outages.length, 1);
    assert.equal(result.longest, 2000);
    assert.equal(result.state, 'UP');
    assert(result.buckets[0].fraction > 0 && result.buckets[0].fraction < 0.01);
});
test('bucket colors use accumulated duration, not mere outage presence', () => {
    const result = summarize([log('UP', cutoff, cutoff + 1000), log('DOWN', cutoff + 1000, cutoff + 3000), log('UP', cutoff + 3000)], cutoff, now, 1);
    assert.equal(result.buckets[0].down, 2000);
    assert.equal(result.buckets[0].fraction, 2000 / 86400000);
    assert.equal(downtimeColor(0), 'rgb(24, 212, 59)');
    assert.equal(downtimeColor(0.05), 'rgb(239, 192, 80)');
    assert.equal(downtimeColor(1), 'rgb(244, 99, 112)');
});
test('closed history does not claim a current state', () => {
    const result = summarize([log('UP', cutoff, now - 1000)], cutoff, now);
    assert.equal(result.state, 'UNKNOWN');
});

test('large outage histories do not exceed the function argument limit', () => {
    const end = 130000 * 19000;
    const logs = Array.from({length: 130000}, (_, i) => log('DOWN', i * 19000, i * 19000 + 5000));
    const result = summarize(logs, 0, end);
    assert.equal(result.longest, 5000);
    assert.equal(result.outages.length, 130000);
    assert.equal(result.downtime, 650000000);
});
