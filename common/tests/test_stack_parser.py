from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from redis import Redis

from buttercup.common.stack_parsing import CrashSet, get_crash_data, get_inst_key, parse_stacktrace

JAVA_TEST_INST_KEY = "\n".join([
    "JXPathFuzzer",
    "org.apache.commons.beanutils.DynaBean",
    "org.apache.commons.jxpath.CompiledExpression",
    "org.apache.commons.jxpath.ExpressionContext",
    "org.apache.commons.jxpath.Function",
    "org.apache.commons.jxpath.Functions",
    "org.apache.commons.jxpath.JXPathContext",
    "org.apache.commons.jxpath.JXPathContextFactory",
    "org.apache.commons.jxpath.JXPathContextFactoryConfigurationError",
    "org.apache.commons.jxpath.JXPathException",
    "org.apache.commons.jxpath.JXPathFunctionNotFoundException",
    "org.apache.commons.jxpath.JXPathInvalidAccessException",
    "org.apache.commons.jxpath.JXPathInvalidSyntaxException",
    "org.apache.commons.jxpath.JXPathNotFoundException",
    "org.apache.commons.jxpath.JXPathTypeConversionException",
    "org.apache.commons.jxpath.NodeSet",
    "org.apache.commons.jxpath.PackageFunctions",
    "org.apache.commons.jxpath.Pointer",
    "org.apache.commons.jxpath.Variables",
    "org.apache.commons.jxpath.ri.Compiler",
    "org.apache.commons.jxpath.ri.EvalContext",
    "org.apache.commons.jxpath.ri.InfoSetUtil",
    "org.apache.commons.jxpath.ri.JXPathContextFactoryReferenceImpl",
    "org.apache.commons.jxpath.ri.JXPathContextReferenceImpl",
    "org.apache.commons.jxpath.ri.NamespaceResolver",
    "org.apache.commons.jxpath.ri.Parser",
    "org.apache.commons.jxpath.ri.QName",
    "org.apache.commons.jxpath.ri.axes.AncestorContext",
    "org.apache.commons.jxpath.ri.axes.AttributeContext",
    "org.apache.commons.jxpath.ri.axes.ChildContext",
    "org.apache.commons.jxpath.ri.axes.DescendantContext",
    "org.apache.commons.jxpath.ri.axes.InitialContext",
    "org.apache.commons.jxpath.ri.axes.NamespaceContext",
    "org.apache.commons.jxpath.ri.axes.NodeSetContext",
    "org.apache.commons.jxpath.ri.axes.ParentContext",
    "org.apache.commons.jxpath.ri.axes.PrecedingOrFollowingContext",
    "org.apache.commons.jxpath.ri.axes.PredicateContext",
    "org.apache.commons.jxpath.ri.axes.RootContext",
    "org.apache.commons.jxpath.ri.axes.SelfContext",
    "org.apache.commons.jxpath.ri.axes.UnionContext",
    "org.apache.commons.jxpath.ri.compiler.Constant",
    "org.apache.commons.jxpath.ri.compiler.CoreFunction",
    "org.apache.commons.jxpath.ri.compiler.CoreOperation",
    "org.apache.commons.jxpath.ri.compiler.CoreOperationGreaterThan",
    "org.apache.commons.jxpath.ri.compiler.CoreOperationNegate",
    "org.apache.commons.jxpath.ri.compiler.CoreOperationRelationalExpression",
    "org.apache.commons.jxpath.ri.compiler.Expression",
    "org.apache.commons.jxpath.ri.compiler.ExpressionPath",
    "org.apache.commons.jxpath.ri.compiler.LocationPath",
    "org.apache.commons.jxpath.ri.compiler.NodeNameTest",
    "org.apache.commons.jxpath.ri.compiler.NodeTest",
    "org.apache.commons.jxpath.ri.compiler.NodeTypeTest",
    "org.apache.commons.jxpath.ri.compiler.Operation",
    "org.apache.commons.jxpath.ri.compiler.Path",
    "org.apache.commons.jxpath.ri.compiler.Step",
    "org.apache.commons.jxpath.ri.compiler.TreeCompiler",
    "org.apache.commons.jxpath.ri.model.NodeIterator",
    "org.apache.commons.jxpath.ri.model.NodePointer",
    "org.apache.commons.jxpath.ri.model.NodePointerFactory",
    "org.apache.commons.jxpath.ri.model.VariablePointer",
    "org.apache.commons.jxpath.ri.model.VariablePointerFactory",
    "org.apache.commons.jxpath.ri.model.beans.BeanPointer",
    "org.apache.commons.jxpath.ri.model.beans.BeanPointerFactory",
    "org.apache.commons.jxpath.ri.model.beans.CollectionPointer",
    "org.apache.commons.jxpath.ri.model.beans.CollectionPointerFactory",
    "org.apache.commons.jxpath.ri.model.beans.NullPointer",
    "org.apache.commons.jxpath.ri.model.beans.NullPropertyPointer",
    "org.apache.commons.jxpath.ri.model.beans.PropertyOwnerPointer",
    "org.apache.commons.jxpath.ri.model.beans.PropertyPointer",
    "org.apache.commons.jxpath.ri.model.container.ContainerPointer",
    "org.apache.commons.jxpath.ri.model.container.ContainerPointerFactory",
    "org.apache.commons.jxpath.ri.model.dom.DOMNodePointer",
    "org.apache.commons.jxpath.ri.model.dom.DOMPointerFactory",
    "org.apache.commons.jxpath.ri.model.dynabeans.DynaBeanPointer",
    "org.apache.commons.jxpath.ri.model.dynabeans.DynaBeanPointerFactory",
    "org.apache.commons.jxpath.ri.model.dynamic.DynamicPointer",
    "org.apache.commons.jxpath.ri.model.dynamic.DynamicPointerFactory",
    "org.apache.commons.jxpath.ri.model.jdom.JDOMNodePointer",
    "org.apache.commons.jxpath.ri.model.jdom.JDOMPointerFactory",
    "org.apache.commons.jxpath.ri.parser.ParseException",
    "org.apache.commons.jxpath.ri.parser.SimpleCharStream",
    "org.apache.commons.jxpath.ri.parser.Token",
    "org.apache.commons.jxpath.ri.parser.TokenMgrError",
    "org.apache.commons.jxpath.ri.parser.XPathParser",
    "org.apache.commons.jxpath.ri.parser.XPathParserConstants",
    "org.apache.commons.jxpath.ri.parser.XPathParserTokenManager",
    "org.apache.commons.jxpath.util.ClassLoaderUtil",
    "org.jdom.Comment",
    "org.jdom.Content",
    "org.jdom.ContentList",
    "org.jdom.DocType",
    "org.jdom.Document",
    "org.jdom.Element",
    "org.jdom.IllegalAddException",
    "org.jdom.Parent",
    "org.jdom.ProcessingInstruction",
    "org.w3c.dom.Document",
    "org.w3c.dom.DocumentType",
    "org.w3c.dom.Element",
    "org.w3c.dom.ElementTraversal",
    "org.w3c.dom.Node",
    "org.w3c.dom.NodeList",
    "org.w3c.dom.TypeInfo",
    "org.w3c.dom.events.DocumentEvent",
    "org.w3c.dom.events.EventTarget",
    "org.w3c.dom.ranges.DocumentRange",
    "org.w3c.dom.traversal.DocumentTraversal",
    "org.xml.sax.ContentHandler",
    "org.xml.sax.DTDHandler",
    "org.xml.sax.EntityResolver",
    "org.xml.sax.ErrorHandler",
    "org.xml.sax.InputSource",
    "org.xml.sax.SAXException",
    "org.xml.sax.SAXParseException",
    "org.xml.sax.helpers.DefaultHandler",
])


def get_tc_file(name: str) -> Path:
    """Get testcase file"""
    crash_file = Path(__file__).parent / "data" / "stacktrace_corpus" / f"{name}_stacktrace.txt"
    if not crash_file.exists():
        raise FileNotFoundError(f"Crash file not found at {crash_file}")

    return crash_file


@pytest.fixture
def java_crash_testcase() -> Path:
    """Get java crash_test_case"""
    return get_tc_file("java")


@pytest.fixture
def c_crash_testcase() -> Path:
    """Get c crash_test_case"""
    return get_tc_file("c")


@pytest.fixture
def c2_crash_testcase() -> Path:
    """Get c crash_test_case"""
    return get_tc_file("c_2")


@pytest.fixture
def mock_crash_set() -> Iterator[CrashSet]:
    """Get mock crash_set"""
    res = CrashSet(MagicMock(spec=Redis))
    set_data = set()

    def add_mock(value: str) -> bool:
        if value in set_data:
            return True
        set_data.add(value)
        return False

    res.set.add = add_mock
    yield res


def test_get_crash_data_basic():
    # Simple stacktrace example
    stacktrace = """
    #0 0x7f339b644844 in foo::bar::crash() /src/foo/bar.cc:123:4
    #1 0x7f339b644900 in main /src/main.cc:45:2
    """
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_symbolized():
    # Test with symbolized stacktrace
    stacktrace = """
    #0 foo::bar::crash() /src/foo/bar.cc:123:4
    #1 main /src/main.cc:45:2
    """
    crash_state = get_crash_data(stacktrace, symbolized=True)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_empty():
    # Test with empty stacktrace
    stacktrace = ""
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_get_crash_data_invalid():
    # Test with invalid stacktrace format
    stacktrace = "This is not a valid stacktrace"
    crash_state = get_crash_data(stacktrace)
    assert crash_state is not None
    assert isinstance(crash_state, str)


def test_java_stacktrace(java_crash_testcase: Path):
    with open(java_crash_testcase) as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    expected = (
        "org.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\n"
        "org.apache.commons.jxpath.ri.compiler.CoreOperation.toString\n"
        "org.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\n"
    )
    assert crash_state == expected


def test_c_stacktrace(c_crash_testcase: Path):
    with open(c_crash_testcase) as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    print(crash_state)
    assert crash_state is not None
    assert isinstance(crash_state, str)
    expected = "cil_destroy_block\ncil_destroy_data\ncil_tree_node_destroy\n"
    assert crash_state == expected


def test_c_instrumentation_key(c_crash_testcase: Path):
    with open(c_crash_testcase) as f:
        trace = f.read()

    inst_key = get_inst_key(trace)
    print(inst_key)
    assert inst_key == ""


def test_java_instrumentation_key(java_crash_testcase: Path):
    with open(java_crash_testcase) as f:
        trace = f.read()

    inst_key = get_inst_key(trace)
    print(inst_key)
    assert inst_key is not None
    assert isinstance(inst_key, str)
    assert inst_key == JAVA_TEST_INST_KEY


@pytest.mark.parametrize(
    "stacktrace_path,line_number",
    [
        (get_tc_file("c"), 249),
        (get_tc_file("c_2"), 230),
        (get_tc_file("java"), 0),
    ],
)
def test_crash_set(mock_crash_set: CrashSet, stacktrace_path: Path, line_number: int):
    with stacktrace_path.open("r") as f:
        stacktrace = f.read()

    assert not mock_crash_set.add("test", "test", "test", "test", stacktrace)
    assert mock_crash_set.add("test", "test", "test", "test", stacktrace)
    assert mock_crash_set._get_final_line_number(parse_stacktrace(stacktrace)) == line_number


def test_crash_set_diff_line_numbers(mock_crash_set: CrashSet, c_crash_testcase: Path, c2_crash_testcase: Path):
    with c_crash_testcase.open("r") as f:
        stacktrace1 = f.read()
    with c2_crash_testcase.open("r") as f:
        stacktrace2 = f.read()

    assert not mock_crash_set.add("test", "test", "test", "test", stacktrace1)
    assert not mock_crash_set.add("test", "test", "test", "test", stacktrace2)

    assert mock_crash_set.add("test", "test", "test", "test", stacktrace1)
    assert mock_crash_set.add("test", "test", "test", "test", stacktrace2)
