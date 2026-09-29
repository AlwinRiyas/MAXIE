import ast
import operator
import re


class CalculatorSkill:
    """Safe arithmetic evaluator.

    Expression strings are parsed with the stdlib ``ast`` module and
    only a small set of operators/functions are allowed. Arbitrary code
    can never run. Also understands spoken-style math in text.
    """

    OPERATORS = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    FUNCTIONS = {
        "sqrt": {"value": lambda x: x ** 0.5, "args": 1},
        "sin": {"value": lambda x: __import__("math").sin(x), "args": 1},
        "cos": {"value": lambda x: __import__("math").cos(x), "args": 1},
        "tan": {"value": lambda x: __import__("math").tan(x), "args": 1},
        "abs": {"value": abs, "args": 1},
        "round": {"value": round, "args": 1},
        "log": {"value": lambda x: __import__("math").log10(x), "args": 1},
        "ln": {"value": lambda x: __import__("math").log(x), "args": 1},
    }

    WORD_NUMBER = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
        "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
        "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
        "ninety": 90, "hundred": 100, "thousand": 1000,
    }

    WORD_OPS = {
        "plus": "+", "and": "+", "added to": "+", "add": "+",
        "minus": "-", "subtract": "-", "minus by": "-", "less": "-",
        "times": "*", "multiplied by": "*", "multiply": "*", "x": "*",
        "divided by": "/", "over": "/", "divide": "/", "by": "/",
        "percent of": "/ 100 *", "to the power of": "**", "power": "**",
        "squared": "**2", "cubed": "**3", "square root of": "sqrt(",
        "square of": "**2",
    }

    def execute(self, text):
        expression = self._to_expression(text)
        if expression is None:
            return "I couldn't understand that calculation."
        try:
            result = self.evaluate(expression)
        except (ZeroDivisionError, ValueError) as error:
            return f"That calculation isn't possible: {error}."
        except Exception:
            return "I couldn't calculate that."

        return f"The answer is {result:g}."

    def evaluate(self, expression):
        """Evaluate a validated expression string to a number."""
        tree = ast.parse(expression, mode="eval").body
        result = self._eval_node(tree)
        if isinstance(result, float) and result.is_integer():
            return int(result)
        return result

    def _eval_node(self, node):
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("unsupported literal")
        if isinstance(node, ast.BinOp):
            op = self.OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError("unsupported operator")
            return op(self._eval_node(node.left), self._eval_node(node.right))
        if isinstance(node, ast.UnaryOp):
            op = self.OPERATORS.get(type(node.op))
            if op is None:
                raise ValueError("unsupported operator")
            return op(self._eval_node(node.operand))
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.Name):
            if node.id in ("pi", "e"):
                math = __import__("math")
                return getattr(math, node.id)
            raise ValueError("unsupported name")
        raise ValueError("unsupported expression")

    def _call(self, node):
        if not isinstance(node.func, ast.Name):
            raise ValueError("unsupported call")
        name = node.func.id.lower()
        spec = self.FUNCTIONS.get(name)
        if spec is None or len(node.args) != spec["args"]:
            raise ValueError("unsupported function")
        arg = self._eval_node(node.args[0])
        return spec["value"](arg)

    def _to_expression(self, text):
        """Convert a natural-language math phrase to an expression."""
        if not text:
            return None

        expr = text.lower().strip().rstrip("?")

        for phrase in ("what is", "whats", "what's", "calculate",
                       "can you calculate", "compute", "work out",
                       "the answer to"):
            expr = re.sub(r"\b" + re.escape(phrase) + r"\b", " ", expr)

        expr = re.sub(r"\s+", " ", expr).strip()

        # ---- Function-style phrases (both prefix and suffix) ----
        expr = re.sub(
            r"(?:square root of|square root|sqrt of|sqrt)\s*([\d.]+)",
            r"sqrt(\1)", expr,
        )
        expr = re.sub(r"square of\s*([\d.]+)", r"(\1)**2", expr)
        expr = re.sub(r"([\d.]+)\s*squared\b", r"(\1)**2", expr)
        expr = re.sub(r"([\d.]+)\s*cubed\b", r"(\1)**3", expr)

        # ---- Spoken operators -> symbols (longest phrase first) ----
        # ("to the power of" must be matched whole, so this runs before
        # the filler-word cleanup below.)
        for word, symbol in sorted(self.WORD_OPS.items(), key=lambda kv: -len(kv[0])):
            expr = re.sub(
                r"\b" + re.escape(word) + r"\b",
                lambda m, s=symbol: f" {s} ",
                expr,
            )

        expr = re.sub(r"\bthe\b", " ", expr).strip()

        # ---- Spoken numbers -> digits ----
        for word, num in self.WORD_NUMBER.items():
            expr = re.sub(rf"\b{word}\b", str(num), expr)

        expr = expr.replace(" ", "").replace("x", "*")

        if not expr or not any(ch.isdigit() for ch in expr):
            return None

        # Balance parentheses so "sqrt(16" still parses.
        expr = expr + ")" * max(0, expr.count("(") - expr.count(")"))

        # Safety net: lowercase letters + digits + arithmetic symbols only.
        # Function names (sqrt/log/sin/...) are validated by the AST walk,
        # so arbitrary code can never evaluate here.
        if re.search(r"[^0-9+\-*/().%^a-z]", expr):
            return None

        return expr.replace("^", "**")