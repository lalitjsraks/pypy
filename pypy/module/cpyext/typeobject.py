import os
import sys

from pypy.rpython.lltypesystem import rffi, lltype
from pypy.tool.pairtype import extendabletype
from pypy.rpython.annlowlevel import llhelper
from pypy.interpreter.gateway import ObjSpace, W_Root, Arguments
from pypy.interpreter.gateway import interp2app, unwrap_spec
from pypy.interpreter.baseobjspace import Wrappable, DescrMismatch
from pypy.objspace.std.typeobject import W_TypeObject, _CPYTYPE, call__Type
from pypy.objspace.std.typetype import _precheck_for_new
from pypy.objspace.std.objectobject import W_ObjectObject
from pypy.interpreter.typedef import TypeDef, GetSetProperty
from pypy.module.cpyext.api import cpython_api, cpython_struct, bootstrap_function, \
    PyVarObjectFields, Py_ssize_t, Py_TPFLAGS_READYING, generic_cpy_call, \
    Py_TPFLAGS_READY, Py_TPFLAGS_HEAPTYPE, ADDR, \
    Py_TPFLAGS_HAVE_CLASS, METH_VARARGS, METH_KEYWORDS, \
    CANNOT_FAIL, PyBufferProcs, build_type_checkers
from pypy.module.cpyext.pyobject import PyObject, make_ref, create_ref, from_ref
from pypy.module.cpyext.pyobject import get_typedescr, make_typedescr, track_reference
from pypy.interpreter.module import Module
from pypy.interpreter.function import FunctionWithFixedCode, StaticMethod
from pypy.module.cpyext import structmemberdefs
from pypy.module.cpyext.modsupport import convert_method_defs, PyCFunction
from pypy.module.cpyext.state import State
from pypy.module.cpyext.methodobject import PyDescr_NewWrapper, \
     PyCFunction_NewEx
from pypy.module.cpyext.pyobject import Py_IncRef, Py_DecRef, _Py_Dealloc
from pypy.module.cpyext.structmember import PyMember_GetOne, PyMember_SetOne
from pypy.module.cpyext.typeobjectdefs import PyTypeObjectPtr, PyTypeObject, \
        PyGetSetDef, PyMemberDef, newfunc
from pypy.module.cpyext.slotdefs import slotdefs
from pypy.interpreter.error import OperationError, operationerrfmt
from pypy.rlib.rstring import rsplit
from pypy.rlib.objectmodel import we_are_translated, specialize
from pypy.module.__builtin__.abstractinst import abstract_issubclass_w
from pypy.module.__builtin__.interp_classobj import W_ClassObject

WARN_ABOUT_MISSING_SLOT_FUNCTIONS = False

PyType_Check, PyType_CheckExact = build_type_checkers("Type", "w_type")

class W_GetSetPropertyEx(GetSetProperty):
    def __init__(self, getset, pto):
        self.getset = getset
        self.name = rffi.charp2str(getset.c_name)
        self.pto = pto
        doc = set = get = None
        if doc:
            doc = rffi.charp2str(getset.c_doc)
        if getset.c_get:
            get = GettersAndSetters.getter.im_func
        if getset.c_set:
            set = GettersAndSetters.setter.im_func
        GetSetProperty.__init__(self, get, set, None, doc,
                                cls=None, use_closure=True,
                                tag="cpyext_1")

def PyDescr_NewGetSet(space, getset, pto):
    return space.wrap(W_GetSetPropertyEx(getset, pto))

class W_MemberDescr(GetSetProperty):
    def __init__(self, member, pto):
        self.member = member
        self.name = rffi.charp2str(member.c_name)
        self.pto = pto
        flags = rffi.cast(lltype.Signed, member.c_flags)
        doc = set = None
        if member.c_doc:
            doc = rffi.charp2str(member.c_doc)
        get = GettersAndSetters.member_getter.im_func
        del_ = GettersAndSetters.member_delete.im_func
        if not (flags & structmemberdefs.READONLY):
            set = GettersAndSetters.member_setter.im_func
        GetSetProperty.__init__(self, get, set, del_, doc,
                                cls=None, use_closure=True,
                                tag="cpyext_2")

def convert_getset_defs(space, dict_w, getsets, pto):
    getsets = rffi.cast(rffi.CArrayPtr(PyGetSetDef), getsets)
    if getsets:
        i = -1
        while True:
            i = i + 1
            getset = getsets[i]
            name = getset.c_name
            if not name:
                break
            name = rffi.charp2str(name)
            w_descr = PyDescr_NewGetSet(space, getset, pto)
            dict_w[name] = w_descr

def convert_member_defs(space, dict_w, members, pto):
    members = rffi.cast(rffi.CArrayPtr(PyMemberDef), members)
    if members:
        i = 0
        while True:
            member = members[i]
            name = member.c_name
            if not name:
                break
            name = rffi.charp2str(name)
            w_descr = space.wrap(W_MemberDescr(member, pto))
            dict_w[name] = w_descr
            i += 1

def update_all_slots(space, w_obj, pto):
    #  XXX fill slots in pto
    state = space.fromcache(State)
    for method_name, slot_name, slot_func, _, _, _ in slotdefs:
        w_descr = space.lookup(w_obj, method_name)
        if w_descr is None:
            # XXX special case iternext
            continue
        if slot_func is None:
            if WARN_ABOUT_MISSING_SLOT_FUNCTIONS:
                os.write(2, method_name + " defined by the type but no slot function defined!\n")
            continue
        slot_func_helper = llhelper(slot_func.api_func.functype,
                slot_func.api_func.get_wrapper(space))
        # XXX special case wrapper-functions and use a "specific" slot func

        # the special case of __new__ in CPython works a bit differently, hopefully
        # this matches the semantics
        if method_name == "__new__" and not pto.c_tp_new:
            continue
        if len(slot_name) == 1:
            setattr(pto, slot_name[0], slot_func_helper)
        else:
            assert len(slot_name) == 2
            struct = getattr(pto, slot_name[0])
            if not struct:
                continue
            setattr(struct, slot_name[1], slot_func_helper)

def add_operators(space, dict_w, pto):
    # XXX support PyObject_HashNotImplemented
    state = space.fromcache(State)
    for method_name, slot_name, _, wrapper_func, wrapper_func_kwds, doc in slotdefs:
        if method_name in dict_w:
            continue
        if len(slot_name) == 1:
            func = getattr(pto, slot_name[0])
        else:
            assert len(slot_name) == 2
            struct = getattr(pto, slot_name[0])
            if not struct:
                continue
            func = getattr(struct, slot_name[1])
        func_voidp = rffi.cast(rffi.VOIDP_real, func)
        if not func:
            continue
        if wrapper_func is None and wrapper_func_kwds is None:
            continue
        dict_w[method_name] = PyDescr_NewWrapper(space, pto, method_name, wrapper_func,
                wrapper_func_kwds, doc, func_voidp)
    if pto.c_tp_new:
        add_tp_new_wrapper(space, dict_w, pto)

@cpython_api([PyObject, PyObject, PyObject], PyObject, external=False)
def tp_new_wrapper(space, w_self, w_args, w_kwds): # XXX untested code
    args_w = space.listview(w_args)[:]
    args_w.insert(0, w_self)
    w_args_new = space.newlist(args_w)
    return space.call(space.lookup(space.w_type, "__new__"), w_args_new, w_kwds)

@specialize.memo()
def get_new_method_def(space):
    state = space.fromcache(State)
    if state.new_method_def:
        return state.new_method_def
    from pypy.module.cpyext.modsupport import PyMethodDef
    ptr = lltype.malloc(PyMethodDef, flavor="raw", zero=True)
    ptr.c_ml_name = rffi.str2charp("__new__")
    rffi.setintfield(ptr, 'c_ml_flags', METH_VARARGS | METH_KEYWORDS)
    ptr.c_ml_doc = rffi.str2charp("T.__new__(S, ...) -> a new object with type S, a subtype of T")
    state.new_method_def = ptr
    return ptr

def setup_new_method_def(space):
    ptr = get_new_method_def(space)
    ptr.c_ml_meth = rffi.cast(PyCFunction,
        llhelper(tp_new_wrapper.api_func.functype,
                 tp_new_wrapper.api_func.get_wrapper(space)))

def add_tp_new_wrapper(space, dict_w, pto):
    if "__new__" in dict_w:
        return
    pyo = rffi.cast(PyObject, pto)
    dict_w["__new__"] = PyCFunction_NewEx(space, get_new_method_def(space),
            from_ref(space, pyo))

def inherit_special(space, pto, base_pto):
    # XXX missing: copy basicsize and flags in a magical way
    flags = rffi.cast(lltype.Signed, pto.c_tp_flags)
    base_object_pyo = make_ref(space, space.w_object, steal=True)
    base_object_pto = rffi.cast(PyTypeObjectPtr, base_object_pyo)
    if base_pto != base_object_pto or flags & Py_TPFLAGS_HEAPTYPE:
        if not pto.c_tp_new:
            pto.c_tp_new = base_pto.c_tp_new

class __extend__(W_Root):
    __metaclass__ = extendabletype
    __slots__ = ("_pyolifeline", ) # hint for the annotator
    _pyolifeline = None
    def set_pyolifeline(self, lifeline):
        self._pyolifeline = lifeline
    def get_pyolifeline(self):
        return self._pyolifeline

class PyOLifeline(object):
    def __init__(self, space, pyo):
        self.pyo = pyo
        self.space = space

    def __del__(self):
        if self.pyo:
            assert self.pyo.c_ob_refcnt == 0
            _Py_Dealloc(self.space, self.pyo)
            self.pyo = lltype.nullptr(PyObject.TO)
        # XXX handle borrowed objects here

def check_descr(space, w_self, pto):
    w_type = from_ref(space, (rffi.cast(PyObject, pto)))
    if not space.is_true(space.isinstance(w_self, w_type)):
        raise DescrMismatch()

class GettersAndSetters:
    def getter(self, space, w_self):
        check_descr(space, w_self, self.pto)
        return generic_cpy_call(
            space, self.getset.c_get, w_self,
            self.getset.c_closure)

    def setter(self, space, w_self, w_value):
        check_descr(space, w_self, self.pto)
        res = generic_cpy_call(
            space, self.getset.c_set, w_self, w_value,
            self.getset.c_closure)
        if rffi.cast(lltype.Signed, res) < 0:
            state = space.fromcache(State)
            state.check_and_raise_exception()

    def member_getter(self, space, w_self):
        check_descr(space, w_self, self.pto)
        return PyMember_GetOne(space, w_self, self.member)

    def member_delete(self, space, w_self):
        check_descr(space, w_self, self.pto)
        PyMember_SetOne(space, w_self, self.member, None)

    def member_setter(self, space, w_self, w_value):
        check_descr(space, w_self, self.pto)
        PyMember_SetOne(space, w_self, self.member, w_value)

def c_type_descr__call__(space, w_type, __args__):
    if isinstance(w_type, W_PyCTypeObject):
        pyo = make_ref(space, w_type)
        pto = rffi.cast(PyTypeObjectPtr, pyo)
        tp_new = pto.c_tp_new
        try:
            if tp_new:
                args_w, kw_w = __args__.unpack()
                w_args = space.newtuple(args_w)
                w_kw = space.newdict()
                for key, w_obj in kw_w.items():
                    space.setitem(w_kw, space.wrap(key), w_obj)
                return generic_cpy_call(space, tp_new, pto, w_args, w_kw)
            else:
                raise operationerrfmt(space.w_TypeError,
                    "cannot create '%s' instances", w_type.getname(space, '?'))
        finally:
            Py_DecRef(space, pyo)
    else:
        w_type = _precheck_for_new(space, w_type)
        return call__Type(space, w_type, __args__)

def c_type_descr__new__(space, w_typetype, w_name, w_bases, w_dict):
    # copied from typetype.descr__new__, XXX missing logic: metaclass resolving
    w_typetype = _precheck_for_new(space, w_typetype)

    bases_w = space.fixedview(w_bases)
    name = space.str_w(w_name)
    dict_w = {}
    dictkeys_w = space.listview(w_dict)
    for w_key in dictkeys_w:
        key = space.str_w(w_key)
        dict_w[key] = space.getitem(w_dict, w_key)
    w_type = space.allocate_instance(W_PyCTypeObject, w_typetype)
    W_TypeObject.__init__(w_type, space, name, bases_w or [space.w_object],
                          dict_w)
    w_type.ready()
    return w_type

class W_PyCTypeObject(W_TypeObject):
    def __init__(self, space, pto):
        bases_w = space.fixedview(from_ref(space, pto.c_tp_bases))
        dict_w = {}

        add_operators(space, dict_w, pto)
        convert_method_defs(space, dict_w, pto.c_tp_methods, pto)
        convert_getset_defs(space, dict_w, pto.c_tp_getset, pto)
        convert_member_defs(space, dict_w, pto.c_tp_members, pto)

        full_name = rffi.charp2str(pto.c_tp_name)
        if '.' in full_name:
            module_name, extension_name = rsplit(full_name, ".", 1)
            dict_w["__module__"] = space.wrap(module_name)
        else:
            extension_name = full_name

        W_TypeObject.__init__(self, space, extension_name,
            bases_w or [space.w_object], dict_w)
        self.__flags__ = _CPYTYPE # mainly disables lookup optimizations

W_PyCTypeObject.typedef = TypeDef(
    'C_type', W_TypeObject.typedef,
    __call__ = interp2app(c_type_descr__call__, unwrap_spec=[ObjSpace, W_Root, Arguments]),
    __new__ = interp2app(c_type_descr__new__),
    )

@bootstrap_function
def init_typeobject(space):
    make_typedescr(space.w_type.instancetypedef,
                   basestruct=PyTypeObject,
                   attach=type_attach,
                   realize=type_realize,
                   dealloc=type_dealloc)
    make_typedescr(W_PyCTypeObject.typedef,
                   basestruct=PyTypeObject,
                   make_ref=pyctype_make_ref,
                   attach=type_attach,
                   realize=type_realize,
                   dealloc=type_dealloc)

    # some types are difficult to create because of cycles.
    # - object.ob_type = type
    # - type.ob_type   = type
    # - tuple.ob_type  = type
    # - type.tp_base   = object
    # - tuple.tp_base  = object
    # - type.tp_bases is a tuple
    # - object.tp_bases is a tuple
    # - tuple.tp_bases is a tuple

    # insert null placeholders to please make_ref()
    state = space.fromcache(State)
    state.py_objects_w2r[space.w_type] = lltype.nullptr(PyObject.TO)
    state.py_objects_w2r[space.w_object] = lltype.nullptr(PyObject.TO)
    state.py_objects_w2r[space.w_tuple] = lltype.nullptr(PyObject.TO)

    # create the objects
    py_type = create_ref(space, space.w_type)
    py_object = create_ref(space, space.w_object)
    py_tuple = create_ref(space, space.w_tuple)

    # form cycles
    pto_type = rffi.cast(PyTypeObjectPtr, py_type)
    py_type.c_ob_type = pto_type
    py_object.c_ob_type = pto_type
    py_tuple.c_ob_type = pto_type

    pto_object = rffi.cast(PyTypeObjectPtr, py_object)
    pto_type.c_tp_base = pto_object
    pto_tuple = rffi.cast(PyTypeObjectPtr, py_tuple)
    pto_tuple.c_tp_base = pto_object

    pto_type.c_tp_bases.c_ob_type = pto_tuple
    pto_object.c_tp_bases.c_ob_type = pto_tuple
    pto_tuple.c_tp_bases.c_ob_type = pto_tuple

    # Restore the mapping
    track_reference(space, py_type, space.w_type)
    track_reference(space, py_object, space.w_object)
    track_reference(space, py_tuple, space.w_tuple)


@cpython_api([PyObject], lltype.Void, external=False)
def subtype_dealloc(space, obj):
    pto = obj.c_ob_type
    base = pto
    this_func_ptr = llhelper(subtype_dealloc.api_func.functype,
            subtype_dealloc.api_func.get_wrapper(space))
    while base.c_tp_dealloc == this_func_ptr:
        base = base.c_tp_base
        assert base
    dealloc = base.c_tp_dealloc
    # XXX call tp_del if necessary
    generic_cpy_call(space, dealloc, obj)
    # XXX cpy decrefs the pto here but we do it in the base-dealloc
    # hopefully this does not clash with the memory model assumed in
    # extension modules

def pyctype_make_ref(space, w_type, w_obj, itemcount=0):
    lifeline = w_obj.get_pyolifeline()
    if lifeline is not None: # make old PyObject ready for use in C code
        py_obj = lifeline.pyo
        assert py_obj.c_ob_refcnt == 0
        Py_IncRef(space, py_obj)
    else:
        typedescr = get_typedescr(w_obj.typedef)
        py_obj = typedescr.allocate(space, w_type, itemcount=itemcount)
        w_obj.set_pyolifeline(PyOLifeline(space, py_obj))
    return py_obj

@cpython_api([PyObject, rffi.INTP], lltype.Signed, external=False,
             error=CANNOT_FAIL)
def str_segcount(space, w_obj, ref):
    if ref:
        ref[0] = rffi.cast(rffi.INT, space.int_w(space.len(w_obj)))
    return 1

@cpython_api([PyObject, lltype.Signed, rffi.VOIDPP], lltype.Signed,
             external=False, error=-1)
def str_getreadbuffer(space, w_str, segment, ref):
    from pypy.module.cpyext.stringobject import PyString_AsString
    if segment != 0:
        raise OperationError(space.w_SystemError, space.wrap
                             ("accessing non-existent string segment"))
    pyref = make_ref(space, w_str, steal=True)
    ref[0] = PyString_AsString(space, pyref)
    return space.int_w(space.len(w_str))

def setup_string_buffer_procs(space, pto):
    c_buf = lltype.malloc(PyBufferProcs, flavor='raw', zero=True)
    c_buf.c_bf_getsegcount = llhelper(str_segcount.api_func.functype,
                                      str_segcount.api_func.get_wrapper(space))
    c_buf.c_bf_getreadbuffer = llhelper(str_getreadbuffer.api_func.functype,
                                 str_getreadbuffer.api_func.get_wrapper(space))
    pto.c_tp_as_buffer = c_buf

@cpython_api([PyObject], lltype.Void, external=False)
def type_dealloc(space, obj):
    state = space.fromcache(State)
    obj_pto = rffi.cast(PyTypeObjectPtr, obj)
    type_pto = obj.c_ob_type
    base_pyo = rffi.cast(PyObject, obj_pto.c_tp_base)
    Py_DecRef(space, obj_pto.c_tp_bases)
    Py_DecRef(space, obj_pto.c_tp_cache) # lets do it like cpython
    if obj_pto.c_tp_flags & Py_TPFLAGS_HEAPTYPE:
        if obj_pto.c_tp_as_buffer:
            lltype.free(obj_pto.c_tp_as_buffer, flavor='raw')
        Py_DecRef(space, base_pyo)
        rffi.free_charp(obj_pto.c_tp_name)
        obj_pto_voidp = rffi.cast(rffi.VOIDP_real, obj_pto)
        generic_cpy_call(space, type_pto.c_tp_free, obj_pto_voidp)
        pto = rffi.cast(PyObject, type_pto)
        Py_DecRef(space, pto)


def type_attach(space, py_obj, w_type):
    """ Allocates a PyTypeObject from a w_type which must be a PyPy type. """
    from pypy.module.cpyext.object import PyObject_Del

    assert isinstance(w_type, W_TypeObject)

    pto = rffi.cast(PyTypeObjectPtr, py_obj)

    typedescr = get_typedescr(w_type.instancetypedef)

    # dealloc
    pto.c_tp_dealloc = typedescr.get_dealloc(space)
    # buffer protocol
    if space.is_w(w_type, space.w_str):
        setup_string_buffer_procs(space, pto)

    pto.c_tp_flags = Py_TPFLAGS_HEAPTYPE
    pto.c_tp_free = llhelper(PyObject_Del.api_func.functype,
            PyObject_Del.api_func.get_wrapper(space))
    pto.c_tp_name = rffi.str2charp(w_type.getname(space, "?"))
    pto.c_tp_basicsize = -1 # hopefully this makes malloc bail out
    pto.c_tp_itemsize = 0
    # uninitialized fields:
    # c_tp_print, c_tp_getattr, c_tp_setattr
    # XXX implement
    # c_tp_compare and the following fields (see http://docs.python.org/c-api/typeobj.html )
    w_base = best_base(space, w_type.bases_w)
    pto.c_tp_base = rffi.cast(PyTypeObjectPtr, make_ref(space, w_base))

    pto.c_tp_bases = lltype.nullptr(PyObject.TO)
    PyPyType_Ready(space, pto, w_type)


    pto.c_tp_basicsize = rffi.sizeof(typedescr.basestruct)
    if pto.c_tp_base:
        if pto.c_tp_base.c_tp_basicsize > pto.c_tp_basicsize:
            pto.c_tp_basicsize = pto.c_tp_base.c_tp_basicsize

    # will be filled later on with the correct value
    # may not be 0
    if space.is_w(w_type, space.w_object):
        pto.c_tp_new = rffi.cast(newfunc, 1)
    update_all_slots(space, w_type, pto)
    return pto

@cpython_api([PyTypeObjectPtr], rffi.INT_real, error=-1)
def PyType_Ready(space, pto):
    return PyPyType_Ready(space, pto, None)

def solid_base(space, w_type):
    typedef = w_type.instancetypedef
    return space.gettypeobject(typedef)

def best_base(space, bases_w):
    if not bases_w:
        return None

    w_winner = None
    w_base = None
    for w_base_i in bases_w:
        if isinstance(w_base_i, W_ClassObject):
            # old-style base
            continue
        assert isinstance(w_base_i, W_TypeObject)
        w_candidate = solid_base(space, w_base_i)
        if not w_winner:
            w_winner = w_candidate
            w_base = w_base_i
        elif space.abstract_issubclass_w(w_winner, w_candidate):
            pass
        elif space.abstract_issubclass_w(w_candidate, w_winner):
            w_winner = w_candidate
            w_base = w_base_i
        else:
            raise OperationError(
                space.w_TypeError,
                space.wrap("multiple bases have instance lay-out conflict"))
    if w_base is None:
        raise OperationError(
            space.w_TypeError,
                space.wrap("a new-style class can't have only classic bases"))

    return w_base

def inherit_slots(space, pto, w_base):
    # XXX missing: nearly everything
    base_pyo = make_ref(space, w_base)
    try:
        base = rffi.cast(PyTypeObjectPtr, base_pyo)
        if not pto.c_tp_dealloc:
            pto.c_tp_dealloc = base.c_tp_dealloc
        # XXX check for correct GC flags!
        if not pto.c_tp_free:
            pto.c_tp_free = base.c_tp_free
    finally:
        Py_DecRef(space, base_pyo)

def type_realize(space, ref):
    PyPyType_Ready(space, rffi.cast(PyTypeObjectPtr, ref), None)
    return from_ref(space, ref, True)

def PyPyType_Ready(space, pto, w_obj):
    try:
        pto.c_tp_dict = lltype.nullptr(PyObject.TO) # not supported
        if pto.c_tp_flags & Py_TPFLAGS_READY:
            return 0
        assert pto.c_tp_flags & Py_TPFLAGS_READYING == 0
        pto.c_tp_flags |= Py_TPFLAGS_READYING
        base = pto.c_tp_base
        if not base:
            base_pyo = make_ref(space, space.w_object, steal=True)
            base = pto.c_tp_base = rffi.cast(PyTypeObjectPtr, base_pyo)
        else:
            base_pyo = rffi.cast(PyObject, base)
        if base and not base.c_tp_flags & Py_TPFLAGS_READY:
            PyPyType_Ready(space, base, None)
        if base and not pto.c_ob_type: # will be filled later
            pto.c_ob_type = base.c_ob_type
        if not pto.c_tp_bases:
            if not base:
                bases = space.newtuple([])
            else:
                bases = space.newtuple([from_ref(space, base_pyo)])
            pto.c_tp_bases = make_ref(space, bases)
        if w_obj is None:
            PyPyType_Register(space, pto)
        if base:
            inherit_special(space, pto, base)
        for w_base in space.fixedview(from_ref(space, pto.c_tp_bases)):
            inherit_slots(space, pto, w_base)
        # missing:
        # setting __doc__ if not defined and tp_doc defined
        # inheriting tp_as_* slots
        # unsupported:
        # tp_mro, tp_subclasses
    finally:
        pto.c_tp_flags &= ~Py_TPFLAGS_READYING
    pto.c_tp_flags = (pto.c_tp_flags & ~Py_TPFLAGS_READYING) | Py_TPFLAGS_READY
    return 0

def PyPyType_Register(space, pto):
    state = space.fromcache(State)
    ptr = rffi.cast(ADDR, pto)
    if ptr not in state.py_objects_r2w:
        w_obj = space.allocate_instance(W_PyCTypeObject,
                space.gettypeobject(W_PyCTypeObject.typedef))
        state.non_heaptypes.append(w_obj)
        pyo = rffi.cast(PyObject, pto)
        state.py_objects_r2w[ptr] = w_obj
        state.py_objects_w2r[w_obj] = pyo
        w_obj.__init__(space, pto)
        w_obj.ready()
    return 1

@cpython_api([PyTypeObjectPtr, PyTypeObjectPtr], rffi.INT_real, error=CANNOT_FAIL)
def PyType_IsSubtype(space, a, b):
    """Return true if a is a subtype of b.
    """
    w_type1 = from_ref(space, rffi.cast(PyObject, a))
    w_type2 = from_ref(space, rffi.cast(PyObject, b))
    return int(abstract_issubclass_w(space, w_type1, w_type2)) #XXX correct?

@cpython_api([PyTypeObjectPtr, Py_ssize_t], PyObject)
def PyType_GenericAlloc(space, type, nitems):
    """This function used an int type for nitems. This might require
    changes in your code for properly supporting 64-bit systems."""
    from pypy.module.cpyext.object import _PyObject_NewVar
    return _PyObject_NewVar(space, type, nitems)
