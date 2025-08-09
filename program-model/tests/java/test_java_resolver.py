import pytest
from buttercup.program_model.api.fuzzy_imports_resolver import FuzzyJavaImportsResolver

test_cases = [
    ("a.b(c).d(e())", ("a.b(c)", "d", "method")),
    ("a.b(d.e()).f.c()", ("a.b(d.e()).f", "c", "method")),
    (
        "object.method1().method2(arg1, arg2.test()).property",
        ("object.method1().method2(arg1, arg2.test())", "property", "field"),
    ),
    ("a.b.c", ("a.b", "c", "field")),
    ("a().b().c()", ("a().b()", "c", "method")),
    (
        "complex.method(nested.calls(with.more.nesting()))",
        ("complex", "method", "method"),
    ),
    ("module.submodule.function()", ("module.submodule", "function", "method")),
    ("a.b().c.d().e", ("a.b().c.d()", "e", "field")),
    ("a.b(c.d).e.f(g.h().i)", ("a.b(c.d).e", "f", "method")),
    # Edge cases
    ("", ("", "", None)),  # Empty string
    ("single", ("", "single", "field")),  # Single identifier without dots
    ("method()", ("", "method", "method")),  # Just a method call
    ("a.(b.c).d", ("a.(b.c)", "d", "field")),  # Parenthesized expression
]


@pytest.mark.parametrize("input_expr,expected", test_cases)
def test_split_rightmost_component(input_expr, expected):
    """Test the split_rightmost_component function with various test cases."""
    resolver = FuzzyJavaImportsResolver(None, None)
    result = resolver.split_rightmost_dotexpr(input_expr)
    assert result == expected, (
        f"Failed on: {input_expr}\nExpected: {expected}\nGot: {result}"
    )
