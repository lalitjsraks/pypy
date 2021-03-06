import py
from pypy.jit.backend import detect_cpu

cpu = detect_cpu.autodetect()
def pytest_runtest_setup(item):
    if cpu not in ('x86', 'x86_64'):
        py.test.skip("x86/x86_64 tests skipped: cpu is %r" % (cpu,))
