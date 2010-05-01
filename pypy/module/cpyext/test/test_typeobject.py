from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase
from pypy.module.cpyext.test.test_api import BaseApiTest
from pypy.module.cpyext.pyobject import PyObject, make_ref, from_ref

import py
import sys

class AppTestTypeObject(AppTestCpythonExtensionBase):
    def test_typeobject(self):
        import sys
        module = self.import_module(name='foo')
        assert 'foo' in sys.modules
        assert "copy" in dir(module.fooType)
        obj = module.new()
        print obj.foo
        assert obj.foo == 42
        print "Obj has type", type(obj)
        assert type(obj) is module.fooType
        print "type of obj has type", type(type(obj))
        print "type of type of obj has type", type(type(type(obj)))

    def test_typeobject2(self):
        module = self.import_module(name='foo')
        obj = module.new()
        obj2 = obj.copy()
        assert module.new().name == "Foo Example"
        c = module.fooType.copy
        assert not "im_func" in dir(module.fooType.copy)
        assert module.fooType.copy.__objclass__ is module.fooType
        assert "copy" in repr(module.fooType.copy)
        assert repr(module.fooType) == "<type 'foo.foo'>"
        assert repr(obj2) == "<Foo>"
        assert repr(module.fooType.__call__) == "<slot wrapper '__call__' of 'foo' objects>"
        assert obj2(foo=1, bar=2) == dict(foo=1, bar=2)

        print obj.foo
        assert obj.foo == 42
        assert obj.int_member == obj.foo

    def test_typeobject3(self):
        module = self.import_module(name='foo')
        obj = module.new()
        obj.int_member = 23
        assert obj.int_member == 23
        obj.int_member = 42
        raises(TypeError, "obj.int_member = 'not a number'")
        raises(TypeError, "del obj.int_member")
        raises(TypeError, "obj.int_member_readonly = 42")
        exc = raises(TypeError, "del obj.int_member_readonly")
        assert "readonly" in str(exc.value)
        raises(SystemError, "obj.broken_member")
        raises(SystemError, "obj.broken_member = 42")
        assert module.fooType.broken_member.__doc__ is None
        assert module.fooType.object_member.__doc__ == "A Python object."

    def test_typeobject4(self):
        module = self.import_module(name='foo')
        obj = module.new()
        assert obj.object_member is None
        obj.object_member = "hello"
        assert obj.object_member == "hello"
        del obj.object_member
        del obj.object_member
        assert obj.object_member is None
        raises(AttributeError, "obj.object_member_ex")
        obj.object_member_ex = None
        assert obj.object_member_ex is None
        obj.object_member_ex = 42
        assert obj.object_member_ex == 42
        del obj.object_member_ex
        raises(AttributeError, "del obj.object_member_ex")

    def test_typeobject5(self):
        module = self.import_module(name='foo')
        obj = module.new()
        assert obj.string_member == "Hello from PyPy"
        raises(TypeError, "obj.string_member = 42")
        raises(TypeError, "del obj.string_member")
        obj.unset_string_member()
        assert obj.string_member is None
        assert obj.string_member_inplace == "spam"
        raises(TypeError, "obj.string_member_inplace = 42")
        raises(TypeError, "del obj.string_member_inplace")
        assert obj.char_member == "s"
        obj.char_member = "a"
        assert obj.char_member == "a"
        raises(TypeError, "obj.char_member = 'spam'")
        raises(TypeError, "obj.char_member = 42")

        a = module.fooType
        assert "cannot create" in raises(TypeError, "a()").value.message
        class bar(module.fooType):
            def baz(self):
                return self
        assert "cannot create" in raises(TypeError, "bar()").value.message
        fuu = module.FuuType
        class fuu2(fuu):
            def baz(self):
                return self
        assert fuu2(u"abc").baz().escape()
        raises(TypeError, module.fooType.object_member.__get__, 1)

    def test_sre(self):
        module = self.import_module(name='_sre')
        import sre_compile
        sre_compile._sre = module
        assert sre_compile.MAGIC == module.MAGIC
        import re
        import time
        s = u"Foo " * 1000 + u"Bar"
        prog = re.compile(ur"Foo.*Bar")
        assert prog.match(s)
        m = re.search(u"xyz", u"xyzxyz")
        assert m
        m = re.search("xyz", "xyzxyz")
        assert m
        assert "groupdict" in dir(m)
        re._cache.clear()
        re._cache_repl.clear()

class TestTypes(BaseApiTest):
    def test_multiple_inheritance(self, space, api):
        w_class = space.appexec([], """():
            class A(object):
                pass
            class B(object):
                pass
            class C(A, B):
                pass
            return C
            """)
        ref = make_ref(space, w_class)
        api.Py_DecRef(ref)
