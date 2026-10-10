"""Validated arithmetic expressions for derived trace counters."""

import ast
import math


# No eval(), attribute access, indexing or calls outside this arithmetic grammar.
def compile_expression(source):
    if not isinstance(source, str) or len(source) > 4096:
        raise ValueError("Expression is too complex")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, RecursionError) as e:
        raise ValueError("Invalid arithmetic expression") from e
    if sum(1 for _ in ast.walk(tree)) > 80:
        raise ValueError("Expression is too complex")
    variables = set()
    functions = {
        "abs": (abs, 1, 1),
        "min": (min, 2, 16),
        "max": (max, 2, 16),
        "sqrt": (math.sqrt, 1, 1),
        "log": (math.log, 1, 2),
    }

    def build(n):
        if isinstance(n, ast.Expression):
            return build(n.body)
        if isinstance(n, ast.Constant) and type(n.value) in (int, float):
            try:
                value = float(n.value)
            except OverflowError as e:
                raise ValueError("Number is too large") from e
            if not math.isfinite(value):
                raise ValueError("Numbers must be finite")
            return lambda x, y: value
        if isinstance(n, ast.Name) and n.id in ("x", "y"):
            variables.add(n.id)
            return (lambda x, y: x) if n.id == "x" else (lambda x, y: y)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            value = build(n.operand)
            sign = 1 if isinstance(n.op, ast.UAdd) else -1
            return lambda x, y: sign * value(x, y)
        if isinstance(n, ast.BinOp):
            a, b = build(n.left), build(n.right)
            if isinstance(n.op, ast.Add):
                return lambda x, y: a(x, y) + b(x, y)
            if isinstance(n.op, ast.Sub):
                return lambda x, y: a(x, y) - b(x, y)
            if isinstance(n.op, ast.Mult):
                return lambda x, y: a(x, y) * b(x, y)
            if isinstance(n.op, ast.Div):
                return lambda x, y: a(x, y) / b(x, y)
        if (
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id in functions
            and not n.keywords
        ):
            function, low, high = functions[n.func.id]
            if not low <= len(n.args) <= high:
                raise ValueError("Invalid number of function arguments")
            args = [build(a) for a in n.args]
            return lambda x, y: function(*(a(x, y) for a in args))
        raise ValueError("Use x, y, numbers, + - * / and abs, min, max, sqrt or log")

    return build(tree), variables


def expression(source, x, y):
    return compile_expression(source)[0](x, y)
