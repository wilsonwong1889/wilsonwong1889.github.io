// Calendar dates are business-local, never UTC. `toISOString()` converts to UTC
// first, so it reports the wrong day for roughly half of every local day: in
// Alberta (UTC-6/-7) anything after 6 PM local rolls forward, and in UTC+
// timezones local midnight rolls backward. Both shift the studio calendar by a
// day. Build the ISO string from the local Y/M/D fields instead.

/** `YYYY-MM-DD` for a Date, in the viewer's local timezone. */
export function toLocalISODate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Today's `YYYY-MM-DD`, local. */
export function todayISO() {
  return toLocalISODate();
}

/** Parse a `YYYY-MM-DD` as local midnight (not UTC midnight). */
export function parseLocalDate(value) {
  return new Date(`${value}T00:00:00`);
}

/** First day of the month containing `value` (`YYYY-MM-DD` in, `YYYY-MM-01` out). */
export function firstOfMonthISO(value) {
  const date = parseLocalDate(value);
  date.setDate(1);
  return toLocalISODate(date);
}

/** Shift a `YYYY-MM-DD` month anchor by whole months, returning the 1st. */
export function shiftMonthISO(monthValue, delta) {
  const date = parseLocalDate(monthValue);
  date.setDate(1);
  date.setMonth(date.getMonth() + delta);
  return toLocalISODate(date);
}

/** True when `value` (`YYYY-MM-DD`) is earlier than today, local. */
export function isDateBeforeToday(value) {
  return Boolean(value && value < todayISO());
}
