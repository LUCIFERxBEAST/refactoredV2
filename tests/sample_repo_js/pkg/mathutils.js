// pkg/mathutils.js — math helpers for the JS demo package.
//
// The rename demo renames `computeTotal` -> `sumItems`: every *static* use
// below is safe to update, except the string-literal access in dynamic_call.js.

function computeTotal(items) {
  return items.reduce((a, b) => a + b, 0);
}

function computeAverage(items) {
  return items.length === 0 ? 0 : computeTotal(items) / items.length;
}

function buildReport(items) {
  const total = computeTotal(items);
  const average = computeAverage(items);
  return `Total: ${total} | Average: ${average.toFixed(2)}`;
}

module.exports = { computeTotal, computeAverage, buildReport };