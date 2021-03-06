from __future__ import absolute_import

import py
from ctypes import *
try:
    from ctypes_support import standard_c_lib, get_errno, set_errno
except ImportError:    # on top of cpython
    from ..ctypes_support import standard_c_lib, get_errno, set_errno


def test_stdlib_and_errno():
    py.test.skip("this is expected on top of pypy, we need to fix ctypes in a way that is now in 2.6 in order to make this reliable")
    write = standard_c_lib.write
    write.argtypes = [c_int, c_char_p, c_size_t]
    write.restype = c_size_t
    # clear errno first
    set_errno(0)
    assert get_errno() == 0
    write(-345, "abc", 3)
    assert get_errno() != 0
    set_errno(0)
    assert get_errno() == 0

def test_argument_conversion_and_checks():
    import ctypes
    libc = ctypes.cdll.LoadLibrary("libc.so.6")
    libc.strlen.argtypes = ctypes.c_char_p,
    libc.strlen.restype = ctypes.c_size_t
    assert libc.strlen("eggs") == 4
    
    # Should raise ArgumentError, not segfault
    py.test.raises(ctypes.ArgumentError, libc.strlen, False)

