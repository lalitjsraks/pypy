from pypy.rpython.lltypesystem import rffi, lltype
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.api import PyObject
from pypy.module.cpyext.pyobject import Py_DecRef

class AppTestBufferObject(AppTestCpythonExtensionBase):
    def test_FromMemory(self):
        module = self.import_extension('foo', [
            ("get_FromMemory", "METH_NOARGS",
             """
                 cbuf = malloc(4);
                 cbuf[0] = 'a';
                 cbuf[1] = 'b';
                 cbuf[2] = 'c';
                 cbuf[3] = '\\0';
                 return PyBuffer_FromMemory(cbuf, 4);
             """),
            ("free_buffer", "METH_NOARGS",
             """
                 free(cbuf);
                 Py_RETURN_NONE;
             """)
            ], prologue = """
            static char* cbuf = NULL;
            """)
        buffer = module.get_FromMemory()
        assert str(buffer) == 'abc\0'
        module.free_buffer()
