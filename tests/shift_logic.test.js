// node tests/shift_logic.test.js — проверка расчёта смены (запускается и из pytest).
const assert = require('assert');
const S = require('../shift_timer/ui/shift.js');
const D = (h, m, s = 0, day = 17) => new Date(2026, 10, day, h, m, s);

// разбор времени
assert.strictEqual(S.parseHM('09:30'), 570);
assert.strictEqual(S.parseHM('9:05'), 545);
assert.strictEqual(S.parseHM('24:00'), null);
assert.strictEqual(S.parseHM('12:60'), null);
assert.strictEqual(S.parseHM(''), null);

// обычная смена 09:00–18:00
let r = S.report(D(15, 30, 0), '09:00', '18:00', true);
assert.strictEqual(r.phase, 'work');
assert.strictEqual(S.clock(r.remain, true), '02:30:00');
assert.strictEqual(S.clock(r.elapsed, true), '06:30:00');
assert.ok(Math.abs(r.progress - 6.5 / 9) < 1e-9);
assert.strictEqual(S.words(r.remain, false), '2 ч 30 мин');

// до начала и после конца
r = S.report(D(8, 0), '09:00', '18:00', true);
assert.strictEqual(r.phase, 'before'); assert.strictEqual(S.clock(r.untilStart, true), '01:00:00'); assert.strictEqual(r.progress, 0);
r = S.report(D(18, 45), '09:00', '18:00', true);
assert.strictEqual(r.phase, 'after'); assert.strictEqual(S.clock(r.over, true), '00:45:00'); assert.strictEqual(r.progress, 1);

// ровно на границах
assert.strictEqual(S.report(D(9, 0), '09:00', '18:00', true).phase, 'work');
assert.strictEqual(S.report(D(18, 0), '09:00', '18:00', true).phase, 'after');
assert.strictEqual(S.report(D(8, 59, 59), '09:00', '18:00', true).phase, 'before');

// без секунд — вверх: за 20 секунд до конца ещё «00:01», не «00:00»
r = S.report(D(17, 59, 40), '09:00', '18:00', false);
assert.strictEqual(S.clock(r.remain, false), '00:01');
r = S.report(D(15, 30, 1), '09:00', '18:00', false);
assert.strictEqual(S.clock(r.remain, false), '02:30');
r = S.report(D(15, 29, 59), '09:00', '18:00', false);
assert.strictEqual(S.clock(r.remain, false), '02:31');

// ночная смена 22:00–06:00: в 23:00 и в 02:00 (смена началась «вчера»), днём — до начала
r = S.report(D(23, 0), '22:00', '06:00', true);
assert.strictEqual(r.phase, 'work'); assert.strictEqual(S.clock(r.remain, true), '07:00:00');
r = S.report(D(2, 0), '22:00', '06:00', true);
assert.strictEqual(r.phase, 'work'); assert.strictEqual(S.clock(r.remain, true), '04:00:00'); assert.strictEqual(S.hm(r.start), '22:00');
assert.strictEqual(r.start.getDate(), 16);
r = S.report(D(12, 0), '22:00', '06:00', true);
assert.strictEqual(r.phase, 'before'); assert.strictEqual(S.clock(r.untilStart, true), '10:00:00');

// одинаковые время начала и конца — сутки
r = S.report(D(10, 0), '09:00', '09:00', true);
assert.strictEqual(r.phase, 'work'); assert.strictEqual(S.clock(r.remain, true), '23:00:00');

// неверное время
assert.strictEqual(S.report(D(10, 0), 'xx', '18:00', true), null);

// подписи
assert.strictEqual(S.words(45 * 60000, false), '45 мин');
assert.strictEqual(S.words(0, false), '0 мин');
assert.strictEqual(S.words(3600000 + 5000, true), '1 ч 5 с');
assert.strictEqual(S.clock(3 * 3600000 + 7 * 60000 + 9000, true), '03:07:09');
console.log('shift logic: OK');
