// tests/test_dynamic.test.js — exercises the dynamic-risk caller
const assert = require('node:assert');
const test = require('node:test');
const { callComputeTotal } = require('../pkg/dynamic_call');

test('callComputeTotal sums items', () => {
  assert.strictEqual(callComputeTotal([1, 2, 3]), 6);
});

test('callComputeTotal empty list', () => {
  assert.strictEqual(callComputeTotal([]), 0);
});