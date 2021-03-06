import sys
from pypy.rlib import debug
from pypy.jit.metainterp.test.oparser import pure_parse
from pypy.jit.metainterp import logger
from pypy.jit.metainterp.typesystem import llhelper
from StringIO import StringIO
from pypy.jit.metainterp.test.test_optimizeopt import equaloplists
from pypy.jit.metainterp.history import AbstractDescr, LoopToken, BasicFailDescr
from pypy.jit.backend.model import AbstractCPU


class Descr(AbstractDescr):
    pass

def capturing(func, *args, **kwds):
    log_stream = StringIO()
    debug._stderr = log_stream
    try:
        func(*args, **kwds)
    finally:
        debug._stderr = sys.stderr
    return log_stream.getvalue()

class Logger(logger.Logger):
    def log_loop(self, loop, namespace={}):
        self.namespace = namespace
        return capturing(logger.Logger.log_loop, self,
                         loop.inputargs, loop.operations)

    def repr_of_descr(self, descr):
        for k, v in self.namespace.items():
            if v == descr:
                return k
        return descr.repr_of_descr()

class TestLogger(object):
    ts = llhelper

    def make_metainterp_sd(self):
        class FakeMetaInterpSd:
            cpu = AbstractCPU()
            cpu.ts = self.ts
            def get_name_from_address(self, addr):
                return 'Name'
        return FakeMetaInterpSd()

    def reparse(self, inp, namespace=None, check_equal=True):
        """ parse loop once, then log it and parse again.
        Checks that we get the same thing.
        """
        if namespace is None:
            namespace = {}
        loop = pure_parse(inp, namespace=namespace)
        logger = Logger(self.make_metainterp_sd())
        output = logger.log_loop(loop, namespace)
        oloop = pure_parse(output, namespace=namespace)
        if check_equal:
            equaloplists(loop.operations, oloop.operations)
            assert oloop.inputargs == loop.inputargs
        return loop, oloop
    
    def test_simple(self):
        inp = '''
        [i0, i1, i2, p3, p4, p5]
        i6 = int_add(i1, i2)
        i8 = int_add(i6, 3)
        jump(i0, i8, i6, p3, p4, p5)
        '''
        self.reparse(inp)

    def test_descr(self):
        inp = '''
        [p0]
        setfield_gc(p0, 3, descr=somedescr)
        '''
        somedescr = Descr()
        self.reparse(inp, namespace=locals())

    def test_guard(self):
        inp = '''
        [i0]
        i1 = int_add(i0, 1)
        guard_true(i0) [i0, i1]
        finish(i1)
        '''
        self.reparse(inp)

    def test_guard_w_hole(self):
        inp = '''
        [i0]
        i1 = int_add(i0, 1)
        guard_true(i0) [i0, None, i1]
        finish(i1)
        '''
        self.reparse(inp)

    def test_debug_merge_point(self):
        inp = '''
        []
        debug_merge_point("info")
        '''
        loop, oloop = self.reparse(inp, check_equal=False)
        assert loop.operations[0].args[0]._get_str() == 'info'
        assert oloop.operations[0].args[0]._get_str() == 'info'
        
    def test_floats(self):
        inp = '''
        [f0]
        f1 = float_add(3.5, f0)
        '''
        loop, oloop = self.reparse(inp)
        equaloplists(loop.operations, oloop.operations)

    def test_jump(self):
        namespace = {'target': LoopToken(3)}
        inp = '''
        [i0]
        jump(i0, descr=target)
        '''
        loop = pure_parse(inp, namespace=namespace)
        logger = Logger(self.make_metainterp_sd())
        output = logger.log_loop(loop)
        assert output.splitlines()[-1] == "jump(i0, descr=<Loop3>)"
        pure_parse(output)
        
    def test_guard_descr(self):
        namespace = {'fdescr': BasicFailDescr()}
        inp = '''
        [i0]
        guard_true(i0, descr=fdescr) [i0]
        '''
        loop = pure_parse(inp, namespace=namespace)
        logger = Logger(self.make_metainterp_sd(), guard_number=True)
        output = logger.log_loop(loop)
        assert output.splitlines()[-1] == "guard_true(i0, descr=<Guard0>) [i0]"
        pure_parse(output)
        
        logger = Logger(self.make_metainterp_sd(), guard_number=False)
        output = logger.log_loop(loop)
        lastline = output.splitlines()[-1]
        assert lastline.startswith("guard_true(i0, descr=<")
        assert not lastline.startswith("guard_true(i0, descr=<Guard")

    def test_class_name(self):
        from pypy.rpython.lltypesystem import lltype
        AbcVTable = lltype.Struct('AbcVTable')
        abcvtable = lltype.malloc(AbcVTable, immortal=True)
        namespace = {'Name': abcvtable}
        inp = '''
        [i0]
        p = new_with_vtable(ConstClass(Name))
        '''
        loop = pure_parse(inp, namespace=namespace)
        logger = Logger(self.make_metainterp_sd())
        output = logger.log_loop(loop)
        assert output.splitlines()[-1].endswith(
            " = new_with_vtable(ConstClass(Name))")
        pure_parse(output, namespace=namespace)

    def test_intro_loop(self):
        bare_logger = logger.Logger(self.make_metainterp_sd())
        output = capturing(bare_logger.log_loop, [], [], 1, "foo")
        assert output.splitlines()[0] == "# Loop 1 : foo with 0 ops"
        pure_parse(output)

    def test_intro_bridge(self):
        bare_logger = logger.Logger(self.make_metainterp_sd())
        output = capturing(bare_logger.log_bridge, [], [], 3)
        assert output.splitlines()[0] == "# bridge out of Guard 3 with 0 ops"
        pure_parse(output)
