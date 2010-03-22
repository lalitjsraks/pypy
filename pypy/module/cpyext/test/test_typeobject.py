from pypy.module.cpyext.test.test_cpyext import AppTestCpythonExtensionBase

import py
import sys

class AppTestTypeObject(AppTestCpythonExtensionBase):
    def test_typeobject(self):
        import sys
        module = self.import_module(name='foo')
        assert 'foo' in sys.modules
        assert "copy" in dir(module.fooType)
        obj = module.new()
        print "Obj has type", type(obj)
        assert type(obj) is module.fooType
        print "type of obj has type", type(type(obj))
        obj2 = obj.copy()
        assert module.new().name == "Foo Example"
        skip("In progress")
        assert "copy" in repr(module.fooType.copy)
