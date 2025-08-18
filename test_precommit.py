#!/usr/bin/env python3
"""Test file to verify pre-commit hooks detect issues."""

import os
import sys  # unused import
from typing import Optional


def bad_function(x, y, z):
    """Function with too many issues."""
    unused_var = 10  # unused variable
    if x == True:  # should use 'is True' or just 'if x'
        print("x is true")
        return x
    elif y == False:  # should use 'is False' or just 'if not y'
        print("y is false")
        return y
    else:
        print("neither")
        
    # unreachable code after return
    print("This won't execute")
    return z


class BadClass:
    """Class with issues."""
    
    def __init__(self):
        self.value = None
        
    def method_with_issues(self, param: Optional[str] = None):
        """Method with issues."""
        if param == None:  # should use 'is None'
            return "None"
        else:
            return param
            
            
# Multiple blank lines above (should be max 2)


def another_bad_function():
    """Function with more issues."""
    list_comp = [x for x in range(10)]  # could use list(range(10))
    dict_comp = dict([(k, v) for k, v in enumerate(range(5))])  # unnecessary list comp
    
    # Line too long
    really_long_line = "This is a really long line that exceeds the maximum line length limit of 120 characters and should be broken up into multiple lines for better readability"
    
    return list_comp, dict_comp