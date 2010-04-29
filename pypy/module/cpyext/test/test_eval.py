from pypy.rpython.lltypesystem import rffi, lltype
from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.eval import Py_single_input, Py_file_input, Py_eval_input

class TestEval(BaseApiTest):
    def test_eval(self, space, api):
        w_l, w_f = space.fixedview(space.appexec([], """():
        l = []
        def f(arg1, arg2):
            l.append(arg1)
            l.append(arg2)
            return len(l)
        return l, f
        """))

        w_t = space.newtuple([space.wrap(1), space.wrap(2)])
        w_res = api.PyEval_CallObjectWithKeywords(w_f, w_t, None)
        assert space.int_w(w_res) == 2
        assert space.int_w(space.len(w_l)) == 2
        w_f = space.appexec([], """():
            def f(*args, **kwds):
                assert isinstance(kwds, dict)
                assert 'xyz' in kwds
                return len(kwds) + len(args) * 10
            return f
            """)
        w_t = space.newtuple([space.w_None, space.w_None])
        w_d = space.newdict()
        space.setitem(w_d, space.wrap("xyz"), space.wrap(3))
        w_res = api.PyEval_CallObjectWithKeywords(w_f, w_t, w_d)
        assert space.int_w(w_res) == 21
    
    def test_call_object(self, space, api):
        w_l, w_f = space.fixedview(space.appexec([], """():
        l = []
        def f(arg1, arg2):
            l.append(arg1)
            l.append(arg2)
            return len(l)
        return l, f
        """))

        w_t = space.newtuple([space.wrap(1), space.wrap(2)])
        w_res = api.PyObject_CallObject(w_f, w_t)
        assert space.int_w(w_res) == 2
        assert space.int_w(space.len(w_l)) == 2
        
        w_f = space.appexec([], """():
            def f(*args):
                assert isinstance(args, tuple)
                return len(args) + 8
            return f
            """)

        w_t = space.newtuple([space.wrap(1), space.wrap(2)])
        w_res = api.PyObject_CallObject(w_f, w_t)
        
        assert space.int_w(w_res) == 10

    def test_run_string(self, space, api):
        def run(code, start, w_globals, w_locals):
            buf = rffi.str2charp(code)
            try:
                return api.PyRun_String(buf, start, w_globals, w_locals)
            finally:
                rffi.free_charp(buf)

        w_globals = space.newdict()
        assert 42 * 43 == space.unwrap(
            run("42 * 43", Py_eval_input, w_globals, w_globals))
        assert api.PyObject_Size(w_globals) == 0

        assert run("a = 42 * 43", Py_single_input,
                   w_globals, w_globals) == space.w_None
        assert 42 * 43 == space.unwrap(
            api.PyObject_GetItem(w_globals, space.wrap("a")))


class AppTestCall(AppTestCpythonExtensionBase):
    def test_CallFunction(self):
        module = self.import_extension('foo', [
            ("call_func", "METH_VARARGS",
             """
                return PyObject_CallFunction(PyTuple_GetItem(args, 0),
                   "siO", "text", 42, Py_None);
             """),
            ("call_method", "METH_VARARGS",
             """
                return PyObject_CallMethod(PyTuple_GetItem(args, 0),
                   "count", "s", "t");
             """),
            ])
        def f(*args):
            return args
        assert module.call_func(f) == ("text", 42, None)
        assert module.call_method("text") == 2
