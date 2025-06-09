import pytest
from buttercup.common.stack_parsing import get_crash_data, get_inst_key
from pathlib import Path

JAVA_TEST_INST_KEY = "JXPathFuzzer\norg.apache.commons.beanutils.DynaBean\norg.apache.commons.jxpath.CompiledExpression\norg.apache.commons.jxpath.ExpressionContext\norg.apache.commons.jxpath.Function\norg.apache.commons.jxpath.Functions\norg.apache.commons.jxpath.JXPathContext\norg.apache.commons.jxpath.JXPathContextFactory\norg.apache.commons.jxpath.JXPathContextFactoryConfigurationError\norg.apache.commons.jxpath.JXPathException\norg.apache.commons.jxpath.JXPathFunctionNotFoundException\norg.apache.commons.jxpath.JXPathInvalidAccessException\norg.apache.commons.jxpath.JXPathInvalidSyntaxException\norg.apache.commons.jxpath.JXPathNotFoundException\norg.apache.commons.jxpath.JXPathTypeConversionException\norg.apache.commons.jxpath.NodeSet\norg.apache.commons.jxpath.PackageFunctions\norg.apache.commons.jxpath.Pointer\norg.apache.commons.jxpath.Variables\norg.apache.commons.jxpath.ri.Compiler\norg.apache.commons.jxpath.ri.EvalContext\norg.apache.commons.jxpath.ri.InfoSetUtil\norg.apache.commons.jxpath.ri.JXPathContextFactoryReferenceImpl\norg.apache.commons.jxpath.ri.JXPathContextReferenceImpl\norg.apache.commons.jxpath.ri.NamespaceResolver\norg.apache.commons.jxpath.ri.Parser\norg.apache.commons.jxpath.ri.QName\norg.apache.commons.jxpath.ri.axes.AncestorContext\norg.apache.commons.jxpath.ri.axes.AttributeContext\norg.apache.commons.jxpath.ri.axes.ChildContext\norg.apache.commons.jxpath.ri.axes.DescendantContext\norg.apache.commons.jxpath.ri.axes.InitialContext\norg.apache.commons.jxpath.ri.axes.NamespaceContext\norg.apache.commons.jxpath.ri.axes.NodeSetContext\norg.apache.commons.jxpath.ri.axes.ParentContext\norg.apache.commons.jxpath.ri.axes.PrecedingOrFollowingContext\norg.apache.commons.jxpath.ri.axes.PredicateContext\norg.apache.commons.jxpath.ri.axes.RootContext\norg.apache.commons.jxpath.ri.axes.SelfContext\norg.apache.commons.jxpath.ri.axes.UnionContext\norg.apache.commons.jxpath.ri.compiler.Constant\norg.apache.commons.jxpath.ri.compiler.CoreFunction\norg.apache.commons.jxpath.ri.compiler.CoreOperation\norg.apache.commons.jxpath.ri.compiler.CoreOperationGreaterThan\norg.apache.commons.jxpath.ri.compiler.CoreOperationNegate\norg.apache.commons.jxpath.ri.compiler.CoreOperationRelationalExpression\norg.apache.commons.jxpath.ri.compiler.Expression\norg.apache.commons.jxpath.ri.compiler.ExpressionPath\norg.apache.commons.jxpath.ri.compiler.LocationPath\norg.apache.commons.jxpath.ri.compiler.NodeNameTest\norg.apache.commons.jxpath.ri.compiler.NodeTest\norg.apache.commons.jxpath.ri.compiler.NodeTypeTest\norg.apache.commons.jxpath.ri.compiler.Operation\norg.apache.commons.jxpath.ri.compiler.Path\norg.apache.commons.jxpath.ri.compiler.Step\norg.apache.commons.jxpath.ri.compiler.TreeCompiler\norg.apache.commons.jxpath.ri.model.NodeIterator\norg.apache.commons.jxpath.ri.model.NodePointer\norg.apache.commons.jxpath.ri.model.NodePointerFactory\norg.apache.commons.jxpath.ri.model.VariablePointer\norg.apache.commons.jxpath.ri.model.VariablePointerFactory\norg.apache.commons.jxpath.ri.model.beans.BeanPointer\norg.apache.commons.jxpath.ri.model.beans.BeanPointerFactory\norg.apache.commons.jxpath.ri.model.beans.CollectionPointer\norg.apache.commons.jxpath.ri.model.beans.CollectionPointerFactory\norg.apache.commons.jxpath.ri.model.beans.NullPointer\norg.apache.commons.jxpath.ri.model.beans.NullPropertyPointer\norg.apache.commons.jxpath.ri.model.beans.PropertyOwnerPointer\norg.apache.commons.jxpath.ri.model.beans.PropertyPointer\norg.apache.commons.jxpath.ri.model.container.ContainerPointer\norg.apache.commons.jxpath.ri.model.container.ContainerPointerFactory\norg.apache.commons.jxpath.ri.model.dom.DOMNodePointer\norg.apache.commons.jxpath.ri.model.dom.DOMPointerFactory\norg.apache.commons.jxpath.ri.model.dynabeans.DynaBeanPointer\norg.apache.commons.jxpath.ri.model.dynabeans.DynaBeanPointerFactory\norg.apache.commons.jxpath.ri.model.dynamic.DynamicPointer\norg.apache.commons.jxpath.ri.model.dynamic.DynamicPointerFactory\norg.apache.commons.jxpath.ri.model.jdom.JDOMNodePointer\norg.apache.commons.jxpath.ri.model.jdom.JDOMPointerFactory\norg.apache.commons.jxpath.ri.parser.ParseException\norg.apache.commons.jxpath.ri.parser.SimpleCharStream\norg.apache.commons.jxpath.ri.parser.Token\norg.apache.commons.jxpath.ri.parser.TokenMgrError\norg.apache.commons.jxpath.ri.parser.XPathParser\norg.apache.commons.jxpath.ri.parser.XPathParserConstants\norg.apache.commons.jxpath.ri.parser.XPathParserTokenManager\norg.apache.commons.jxpath.util.ClassLoaderUtil\norg.jdom.Comment\norg.jdom.Content\norg.jdom.ContentList\norg.jdom.DocType\norg.jdom.Document\norg.jdom.Element\norg.jdom.IllegalAddException\norg.jdom.Parent\norg.jdom.ProcessingInstruction\norg.w3c.dom.Document\norg.w3c.dom.DocumentType\norg.w3c.dom.Element\norg.w3c.dom.ElementTraversal\norg.w3c.dom.Node\norg.w3c.dom.NodeList\norg.w3c.dom.TypeInfo\norg.w3c.dom.events.DocumentEvent\norg.w3c.dom.events.EventTarget\norg.w3c.dom.ranges.DocumentRange\norg.w3c.dom.traversal.DocumentTraversal\norg.xml.sax.ContentHandler\norg.xml.sax.DTDHandler\norg.xml.sax.EntityResolver\norg.xml.sax.ErrorHandler\norg.xml.sax.InputSource\norg.xml.sax.SAXException\norg.xml.sax.SAXParseException\norg.xml.sax.helpers.DefaultHandler"


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
    with open(java_crash_testcase, "r") as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    expected = "org.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\norg.apache.commons.jxpath.ri.compiler.CoreOperation.toString\norg.apache.commons.jxpath.ri.compiler.CoreOperation.parenthesize\n"
    assert crash_state == expected


def test_c_stacktrace(c_crash_testcase: Path):
    with open(c_crash_testcase, "r") as f:
        trace = f.read()

    crash_state = get_crash_data(trace)
    print(crash_state)
    assert crash_state is not None
    assert isinstance(crash_state, str)
    expected = "cil_destroy_block\ncil_destroy_data\ncil_tree_node_destroy\n"
    assert crash_state == expected


def test_c_instrumentation_key(c_crash_testcase: Path):
    with open(c_crash_testcase, "r") as f:
        trace = f.read()

    inst_key = get_inst_key(trace)
    print(inst_key)
    assert inst_key == ""


def test_java_instrumentation_key(java_crash_testcase: Path):
    with open(java_crash_testcase, "r") as f:
        trace = f.read()

    inst_key = get_inst_key(trace)
    print(inst_key)
    assert inst_key is not None
    assert isinstance(inst_key, str)
    assert inst_key == JAVA_TEST_INST_KEY
