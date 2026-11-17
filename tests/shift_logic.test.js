// node tests/shift_logic.test.js — проверка расчёта по отработанному времени (запускается и из pytest).
const assert = require('assert');
const S = require('../shift_timer/ui/shift.js');
const NOW = new Date(2026, 10, 17, 14, 0, 0).getTime();
const H = 3600;

assert.strictEqual(S.parseHM('08:30'), 510);
assert.strictEqual(S.parseHM('24:00'), null);
assert.strictEqual(S.parseHM('12:60'), null);
assert.strictEqual(S.parseHM(''), null);

// идёт работа: отработано 5:10:30 из 8 ч
let c = S.calc(5 * H + 10 * 60 + 30, 8 * H, NOW, false, true);
assert.strictEqual(c.phase, 'work');
assert.strictEqual(S.clock(c.remain, true), '02:49:30');
assert.strictEqual(S.clock(c.worked, true), '05:10:30');
assert.ok(Math.abs(c.progress - (5 * H + 630) / (8 * H)) < 1e-9);
assert.strictEqual(S.hm(c.finish), '16:50');                 // 14:00 + 2:49:30 = 16:49:30 → вверх до минуты
assert.strictEqual(c.soon, false);
assert.strictEqual(S.words(S.calc(5 * H + 630, 8 * H, NOW, false, false).remain, false), '2 ч 50 мин');   // без секунд — вверх

// экран заблокирован: пауза, прогноза ухода нет
c = S.calc(3 * H, 8 * H, NOW, true, true);
assert.strictEqual(c.phase, 'paused'); assert.strictEqual(c.finish, null);

// норма выполнена и переработка
c = S.calc(8 * H, 8 * H, NOW, false, true);
assert.strictEqual(c.phase, 'done'); assert.strictEqual(c.remain, 0); assert.strictEqual(c.over, 0); assert.strictEqual(c.progress, 1);
c = S.calc(8 * H + 25 * 60 + 40, 8 * H, NOW, false, true);
assert.strictEqual(c.phase, 'done'); assert.strictEqual(c.over, 25 * 60 + 40); assert.strictEqual(c.finish, null);
assert.strictEqual(c.progress, 1);
c = S.calc(8 * H + 100, 8 * H, NOW, true, true);             // пауза после выполненной нормы — всё равно «выполнена»
assert.strictEqual(c.phase, 'done');

// без секунд: оставшееся — вверх, отработанное — вниз
c = S.calc(8 * H - 20, 8 * H, NOW, false, false);
assert.strictEqual(S.clock(c.remain, false), '00:01'); assert.strictEqual(c.soon, true);
c = S.calc(8 * H - 3 * H - 59, 8 * H, NOW, false, false);
assert.strictEqual(S.clock(c.remain, false), '03:01'); assert.strictEqual(S.clock(c.worked, false), '04:59');   // осталось 3:00:59 → 03:01
assert.strictEqual(S.clock(S.calc(5 * H + 59, 8 * H, NOW, false, false).worked, false), '05:00');   // 5:00:59 → 05:00
assert.strictEqual(S.clock(S.calc(5 * H - 1, 8 * H, NOW, false, false).worked, false), '04:59');

// в начале дня
c = S.calc(0, 8 * H, NOW, false, true);
assert.strictEqual(S.clock(c.remain, true), '08:00:00'); assert.strictEqual(c.progress, 0);

// подписи
assert.strictEqual(S.words(45 * 60, false), '45 мин');
assert.strictEqual(S.words(0, false), '0 мин');
assert.strictEqual(S.words(H + 5, true), '1 ч 5 с');
assert.strictEqual(S.clock(3 * H + 7 * 60 + 9, true), '03:07:09');
assert.strictEqual(S.hmStr('09:02:11'), '09:02'); assert.strictEqual(S.hmStr(null), '—');
assert.strictEqual(S.signed(720), '+0:12'); assert.strictEqual(S.signed(-3900), '−1:05'); assert.strictEqual(S.signed(0), '+0:00');
assert.strictEqual(S.hmSec(8 * H), '8:00'); assert.strictEqual(S.hmSec(8 * H + 30 * 60), '8:30');
// прогноз ухода учитывает обед, который ещё впереди (день = норма + обед)
c = S.calc(5 * H + 630, 8 * H, NOW, false, true, 3600);
assert.strictEqual(S.hm(c.finish), '17:50');                 // 14:00 + 2:49:30 + 1:00 = 17:49:30 → 17:50
assert.strictEqual(S.hm(S.calc(5 * H + 630, 8 * H, NOW, false, true, 0).finish), '16:50');
assert.strictEqual(S.calc(5 * H, 8 * H, NOW, true, true, 3600).finish, null);   // экран заблокирован (без обеда) — прогноза нет

// таймер обеда
let l = S.lunch(1500, 3600, true);
assert.strictEqual(S.clock(l.remain, true), '00:35:00'); assert.ok(Math.abs(l.progress - 1500 / 3600) < 1e-9); assert.strictEqual(l.over, false);
l = S.lunch(3600, 3600, true); assert.strictEqual(l.remain, 0); assert.strictEqual(l.progress, 1); assert.strictEqual(l.over, true);
l = S.lunch(3700, 3600, false); assert.strictEqual(l.remain, 0); assert.strictEqual(l.over, true);
assert.strictEqual(S.clock(S.lunch(3541, 3600, false).remain, false), '00:01');   // без секунд — вверх, как и у нормы
// высота мини-окна с задачами: растёт до 5 строк и дальше не растёт
assert.strictEqual(S.tasksHeight(0), 190); assert.strictEqual(S.tasksHeight(1), 186); assert.strictEqual(S.tasksHeight(5), 322);
assert.strictEqual(S.tasksHeight(30), 322); assert.ok(S.tasksHeight(3) > S.tasksHeight(2));
console.log('shift logic: OK');
