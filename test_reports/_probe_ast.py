import tree_sitter_python
import tree_sitter_javascript
from tree_sitter import Language, Parser

py_parser = Parser(Language(tree_sitter_python.language()))
js_parser = Parser(Language(tree_sitter_javascript.language()))

py_src = b"""
import math as m
from pkg.mathutils import compute_total as ct
from pkg.mathutils import compute_total

def compute_total(items):
    total = sum(items)
    return total

def caller():
    compute_total([1, 2])
    obj.compute_total([1])
    getattr(obj, "compute_total")
    val = "compute_total"

def shadowed(compute_total):
    return compute_total + 1
"""

js_src = b"""
import { computeTotal as ct } from './mathutils';
import { computeTotal } from './mathutils';
const { computeTotal: renamedTotal } = require('./mathutils');
const { computeTotal } = require('./mathutils');

function computeTotal(items) {
    return items.length;
}

function caller() {
    computeTotal([1, 2]);
    obj.computeTotal([1]);
    obj["computeTotal"](x);
    eval("computeTotal");
    const s = "computeTotal";
}

function shadowed(computeTotal) {
    return computeTotal + 1;
}
"""

def inspect(parser, src, name, target):
    print(f"=== {name} ===")
    tree = parser.parse(src)
    def walk(n):
        yield n
        for c in n.named_children:
            yield from walk(c)
    for n in walk(tree.root_node):
        if target in n.text:
            p_type = n.parent.type if n.parent else "None"
            gp_type = n.parent.parent.type if (n.parent and n.parent.parent) else "None"
            print(f"Node: {n.type:25} | Parent: {p_type:25} | GrParent: {gp_type:20} | Range: {n.start_point.row+1}:{n.start_point.column+1} | Text: {n.text.decode('utf-8')[:30]!r}")

inspect(py_parser, py_src, "PYTHON", b"compute_total")
inspect(js_parser, js_src, "JAVASCRIPT", b"computeTotal")
