// tests/test_reporter.test.js — JS mirror of the Python test_reporter.py
const assert = require('node:assert');
const test = require('node:test');
const mathutils = require('../pkg/mathutils');
const { reportTotal } = require('../pkg/reporter');

test('reportTotal sums items', () => {
  assert.strictEqual(reportTotal([1, 2, 3]), 'The sum of your items is 6');
});

test('buildReport builds a report', () => {
  assert.strictEqual(mathutils.buildReport([1, 2, 3]), 'Total: 6 | Average: 2.00');
});

test('computeTotal sums items', () => {
  assert.strictEqual(mathutils.computeTotal([1, 2, 3, 4]), 10);
});