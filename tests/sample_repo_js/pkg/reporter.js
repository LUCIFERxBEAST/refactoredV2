// pkg/reporter.js — imports and calls computeTotal normally (static use).
const mathutils = require('./mathutils');

function reportTotal(items) {
  const result = mathutils.computeTotal(items);
  return `The sum of your items is ${result}`;
}

module.exports = { reportTotal };