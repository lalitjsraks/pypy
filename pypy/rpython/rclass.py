import types
from pypy.annotation import model as annmodel
#from pypy.annotation.classdef import isclassdef
from pypy.annotation import description
from pypy.rpython.error import TyperError
from pypy.rpython.rmodel import Repr, getgcflavor


class FieldListAccessor(object):

    def initialize(self, TYPE, fields):
        assert type(fields) is dict
        self.TYPE = TYPE
        self.fields = fields

    def __repr__(self):
        return '<FieldListAccessor for %s>' % getattr(self, 'TYPE', '?')

    def _freeze_(self):
        return True

class ImmutableConflictError(Exception):
    """Raised when the _immutable_ or _immutable_fields_ hints are
    not consistent across a class hierarchy."""


def getclassrepr(rtyper, classdef):
    try:
        result = rtyper.class_reprs[classdef]
    except KeyError:
        result = rtyper.type_system.rclass.ClassRepr(rtyper, classdef)
        rtyper.class_reprs[classdef] = result
        rtyper.add_pendingsetup(result)
    return result

def getinstancerepr(rtyper, classdef, default_flavor='gc'):
    if classdef is None:
        flavor = default_flavor
    else:
        flavor = getgcflavor(classdef)
    try:
        result = rtyper.instance_reprs[classdef, flavor]
    except KeyError:
        result = buildinstancerepr(rtyper, classdef, gcflavor=flavor)

        rtyper.instance_reprs[classdef, flavor] = result
        rtyper.add_pendingsetup(result)
    return result


def buildinstancerepr(rtyper, classdef, gcflavor='gc'):
    from pypy.rlib.objectmodel import UnboxedValue
    from pypy.objspace.flow.model import Constant
    
    if classdef is None:
        unboxed = []
        virtualizable2 = False
    else:
        unboxed = [subdef for subdef in classdef.getallsubdefs()
                          if subdef.classdesc.pyobj is not None and
                             issubclass(subdef.classdesc.pyobj, UnboxedValue)]
        virtualizable2 = classdef.classdesc.read_attribute('_virtualizable2_',
                                                           Constant(False)).value
    config = rtyper.annotator.translator.config
    usetagging = len(unboxed) != 0 and config.translation.taggedpointers

    if virtualizable2:
        assert len(unboxed) == 0
        assert gcflavor == 'gc'
        return rtyper.type_system.rvirtualizable2.Virtualizable2InstanceRepr(rtyper, classdef)
    elif usetagging and rtyper.type_system.name == 'lltypesystem':
        # the UnboxedValue class and its parent classes need a
        # special repr for their instances
        if len(unboxed) != 1:
            raise TyperError("%r has several UnboxedValue subclasses" % (
                classdef,))
        assert gcflavor == 'gc'
        from pypy.rpython.lltypesystem import rtagged
        return rtagged.TaggedInstanceRepr(rtyper, classdef, unboxed[0])
    else:
        return rtyper.type_system.rclass.InstanceRepr(rtyper, classdef, gcflavor)


class MissingRTypeAttribute(TyperError):
    pass

class AbstractClassRepr(Repr):
    def __init__(self, rtyper, classdef):
        self.rtyper = rtyper
        self.classdef = classdef

    def _setup_repr(self):
        pass

    def __repr__(self):
        if self.classdef is None:
            clsname = 'object'
        else:
            clsname = self.classdef.name
        return '<ClassRepr for %s>' % (clsname,)

    def compact_repr(self):
        if self.classdef is None:
            clsname = 'object'
        else:
            clsname = self.classdef.name
        return 'ClassR %s' % (clsname,)

    def convert_desc(self, desc):
        subclassdef = desc.getuniqueclassdef()
        if self.classdef is not None:
            if self.classdef.commonbase(subclassdef) != self.classdef:
                raise TyperError("not a subclass of %r: %r" % (
                    self.classdef.name, desc))
        
        r_subclass = getclassrepr(self.rtyper, subclassdef)
        return r_subclass.getruntime(self.lowleveltype)

    def convert_const(self, value):
        if not isinstance(value, (type, types.ClassType)):
            raise TyperError("not a class: %r" % (value,))
        bk = self.rtyper.annotator.bookkeeper
        return self.convert_desc(bk.getdesc(value))

    def prepare_method(self, s_value):
        # special-casing for methods:
        #  if s_value is SomePBC([MethodDescs...])
        #  return a PBC representing the underlying functions
        if isinstance(s_value, annmodel.SomePBC):
            if not s_value.isNone() and s_value.getKind() == description.MethodDesc:
                s_value = self.classdef.lookup_filter(s_value)
                funcdescs = [mdesc.funcdesc for mdesc in s_value.descriptions]
                return annmodel.SomePBC(funcdescs)
        return None   # not a method

    def get_ll_eq_function(self):
        return None

def get_type_repr(rtyper):
    return getclassrepr(rtyper, None)

# ____________________________________________________________


class __extend__(annmodel.SomeInstance):
    def rtyper_makerepr(self, rtyper):
        return getinstancerepr(rtyper, self.classdef)
    def rtyper_makekey(self):
        return self.__class__, self.classdef


class AbstractInstanceRepr(Repr):
    def __init__(self, rtyper, classdef):
        self.rtyper = rtyper
        self.classdef = classdef

    def _setup_repr(self):
        pass

    def _check_for_immutable_hints(self, hints):
        if self.classdef.classdesc.lookup('_immutable_') is not None:
            hints = hints.copy()
            hints['immutable'] = True
        self.immutable_field_list = []  # unless overwritten below
        if self.classdef.classdesc.lookup('_immutable_fields_') is not None:
            hints = hints.copy()
            immutable_fields = self.classdef.classdesc.classdict.get(
                '_immutable_fields_')
            if immutable_fields is not None:
                self.immutable_field_list = immutable_fields.value
            accessor = FieldListAccessor()
            hints['immutable_fields'] = accessor
        return hints

    def __repr__(self):
        if self.classdef is None:
            clsname = 'object'
        else:
            clsname = self.classdef.name
        return '<InstanceRepr for %s>' % (clsname,)

    def compact_repr(self):
        if self.classdef is None:
            clsname = 'object'
        else:
            clsname = self.classdef.name
        return 'InstanceR %s' % (clsname,)

    def _setup_repr_final(self):
        self._setup_immutable_field_list()
        self._check_for_immutable_conflicts()

    def _setup_immutable_field_list(self):
        hints = self.object_type._hints
        if "immutable_fields" in hints:
            accessor = hints["immutable_fields"]
            if not hasattr(accessor, 'fields'):
                immutable_fields = []
                rbase = self
                while rbase.classdef is not None:
                    immutable_fields += rbase.immutable_field_list
                    rbase = rbase.rbase
                self._parse_field_list(immutable_fields, accessor)

    def _parse_field_list(self, fields, accessor):
        with_suffix = {}
        for name in fields:
            if name.endswith('[*]'):
                name = name[:-3]
                suffix = '[*]'
            else:
                suffix = ''
            try:
                mangled_name, r = self._get_field(name)
            except KeyError:
                continue
            with_suffix[mangled_name] = suffix
        accessor.initialize(self.object_type, with_suffix)
        return with_suffix

    def _check_for_immutable_conflicts(self):
        # check for conflicts, i.e. a field that is defined normally as
        # mutable in some parent class but that is now declared immutable
        from pypy.rpython.lltypesystem.lltype import Void
        is_self_immutable = "immutable" in self.object_type._hints
        base = self
        while base.classdef is not None:
            base = base.rbase
            for fieldname in base.fields:
                try:
                    mangled, r = base._get_field(fieldname)
                except KeyError:
                    continue
                if r.lowleveltype == Void:
                    continue
                base._setup_immutable_field_list()
                if base.object_type._immutable_field(mangled):
                    continue
                # 'fieldname' is a mutable, non-Void field in the parent
                if is_self_immutable:
                    raise ImmutableConflictError(
                        "class %r has _immutable_=True, but parent class %r "
                        "defines (at least) the mutable field %r" % (
                        self, base, fieldname))
                if fieldname in self.immutable_field_list:
                    raise ImmutableConflictError(
                        "field %r is defined mutable in class %r, but "
                        "listed in _immutable_fields_ in subclass %r" % (
                        fieldname, base, self))

    def new_instance(self, llops, classcallhop=None):
        raise NotImplementedError

    def convert_const(self, value):
        if value is None:
            return self.null_instance()
        if isinstance(value, types.MethodType):
            value = value.im_self   # bound method -> instance
        bk = self.rtyper.annotator.bookkeeper
        try:
            classdef = bk.getuniqueclassdef(value.__class__)
        except KeyError:
            raise TyperError("no classdef: %r" % (value.__class__,))
        if classdef != self.classdef:
            # if the class does not match exactly, check that 'value' is an
            # instance of a subclass and delegate to that InstanceRepr
            if classdef.commonbase(self.classdef) != self.classdef:
                raise TyperError("not an instance of %r: %r" % (
                    self.classdef.name, value))
            rinstance = getinstancerepr(self.rtyper, classdef)
            result = rinstance.convert_const(value)
            return self.upcast(result)
        # common case
        return self.convert_const_exact(value)

    def convert_const_exact(self, value):
        try:
            return self.iprebuiltinstances[value]
        except KeyError:
            self.setup()
            result = self.create_instance()
            self.iprebuiltinstances[value] = result
            self.initialize_prebuilt_instance(value, self.classdef, result)
            return result

    def get_reusable_prebuilt_instance(self):
        "Get a dummy prebuilt instance.  Multiple calls reuse the same one."
        try:
            return self._reusable_prebuilt_instance
        except AttributeError:
            self.setup()
            result = self.create_instance()
            self._reusable_prebuilt_instance = result
            self.initialize_prebuilt_data(Ellipsis, self.classdef, result)
            return result

    def initialize_prebuilt_instance(self, value, classdef, result):
        # must fill in the hash cache before the other ones
        # (see test_circular_hash_initialization)
        self.initialize_prebuilt_hash(value, result)
        self.initialize_prebuilt_data(value, classdef, result)

    def get_ll_hash_function(self):
        return ll_inst_hash

    def rtype_type(self, hop):
        raise NotImplementedError

    def rtype_getattr(self, hop):
        raise NotImplementedError

    def rtype_setattr(self, hop):
        raise NotImplementedError

    def rtype_is_true(self, hop):
        raise NotImplementedError

    def ll_str(self, i):
        raise NotImplementedError

    def get_ll_eq_function(self):
        return None    # defaults to compare by identity ('==' on pointers)

    def can_ll_be_null(self, s_value):
        return s_value.can_be_none()

# ____________________________________________________________

def rtype_new_instance(rtyper, classdef, llops, classcallhop=None):
    rinstance = getinstancerepr(rtyper, classdef)
    return rinstance.new_instance(llops, classcallhop)

def ll_inst_hash(ins):
    if not ins:
        return 0    # for None
    else:
        from pypy.rpython.lltypesystem import lltype
        return lltype.identityhash(ins)     # also works for ootype


_missing = object()

def fishllattr(inst, name, default=_missing):
    from pypy.rpython.lltypesystem import lltype
    from pypy.rpython.ootypesystem import ootype
    if isinstance(inst, (ootype._instance, ootype._view)):
        # XXX: we need to call ootypesystem.rclass.mangle, but we
        # can't because we don't have a config object
        mangled = 'o' + name
        if default is _missing:
            return getattr(inst, mangled)
        else:
            return getattr(inst, mangled, default)
    else:
        p = widest = lltype.normalizeptr(inst)
        while True:
            try:
                return getattr(p, 'inst_' + name)
            except AttributeError:
                pass
            try:
                p = p.super
            except AttributeError:
                break
        if default is _missing:
            raise AttributeError("%s has no field %s" % (lltype.typeOf(widest),
                                                         name))
        return default
