// pkg/dynamic_call.js — calls computeTotal ONLY through a string-literal
// member access (`mathutils["computeTotal"]`). A plain rename could never
// update this, so this file is the JavaScript dynamic-risk demo.

const mathutils = require('./mathutils');

function callComputeTotal(items) {
  return mathutils["computeTotal"](items);
}

module.exports = { callComputeTotal };