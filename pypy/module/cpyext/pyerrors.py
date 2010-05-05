import os

from pypy.rpython.lltypesystem import rffi, lltype
from pypy.interpreter.error import OperationError, wrap_oserror
from pypy.module.cpyext.api import cpython_api, CANNOT_FAIL, CONST_STRING
from pypy.module.exceptions.interp_exceptions import W_RuntimeWarning
from pypy.module.cpyext.pyobject import (
    PyObject, PyObjectP, make_ref, Py_DecRef, register_container)
from pypy.module.cpyext.state import State
from pypy.module.cpyext.import_ import PyImport_Import
from pypy.rlib.rposix import get_errno

@cpython_api([PyObject, PyObject], lltype.Void)
def PyErr_SetObject(space, w_type, w_value):
    """This function is similar to PyErr_SetString() but lets you specify an
    arbitrary Python object for the "value" of the exception."""
    state = space.fromcache(State)
    state.set_exception(OperationError(w_type, w_value))

@cpython_api([PyObject, CONST_STRING], lltype.Void)
def PyErr_SetString(space, w_type, message_ptr):
    message = rffi.charp2str(message_ptr)
    PyErr_SetObject(space, w_type, space.wrap(message))

@cpython_api([PyObject], lltype.Void, error=CANNOT_FAIL)
def PyErr_SetNone(space, w_type):
    """This is a shorthand for PyErr_SetObject(type, Py_None)."""
    PyErr_SetObject(space, w_type, space.w_None)

@cpython_api([], PyObject, borrowed=True)
def PyErr_Occurred(space):
    state = space.fromcache(State)
    if state.operror is None:
        return None
    register_container(space, lltype.nullptr(PyObject.TO))
    return state.operror.w_type

@cpython_api([], lltype.Void)
def PyErr_Clear(space):
    state = space.fromcache(State)
    state.clear_exception()

@cpython_api([PyObjectP, PyObjectP, PyObjectP], lltype.Void)
def PyErr_Fetch(space, ptype, pvalue, ptraceback):
    """Retrieve the error indicator into three variables whose addresses are passed.
    If the error indicator is not set, set all three variables to NULL.  If it is
    set, it will be cleared and you own a reference to each object retrieved.  The
    value and traceback object may be NULL even when the type object is not.
    
    This function is normally only used by code that needs to handle exceptions or
    by code that needs to save and restore the error indicator temporarily."""
    state = space.fromcache(State)
    operror = state.clear_exception()
    if operror:
        ptype[0] = make_ref(space, operror.w_type)
        pvalue[0] = make_ref(space, operror.get_w_value(space))
    else:
        ptype[0] = lltype.nullptr(PyObject.TO)
        pvalue[0] = lltype.nullptr(PyObject.TO)
    ptraceback[0] = lltype.nullptr(PyObject.TO)

@cpython_api([PyObject, PyObject, PyObject], lltype.Void)
def PyErr_Restore(space, w_type, w_value, w_traceback):
    """Set  the error indicator from the three objects.  If the error indicator is
    already set, it is cleared first.  If the objects are NULL, the error
    indicator is cleared.  Do not pass a NULL type and non-NULL value or
    traceback.  The exception type should be a class.  Do not pass an invalid
    exception type or value. (Violating these rules will cause subtle problems
    later.)  This call takes away a reference to each object: you must own a
    reference to each object before the call and after the call you no longer own
    these references.  (If you don't understand this, don't use this function.  I
    warned you.)
    
    This function is normally only used by code that needs to save and restore the
    error indicator temporarily; use PyErr_Fetch() to save the current
    exception state."""
    state = space.fromcache(State)
    state.set_exception(OperationError(w_type, w_value))
    Py_DecRef(space, w_type)
    Py_DecRef(space, w_value)
    Py_DecRef(space, w_traceback)

@cpython_api([], lltype.Void)
def PyErr_BadArgument(space):
    """This is a shorthand for PyErr_SetString(PyExc_TypeError, message), where
    message indicates that a built-in operation was invoked with an illegal
    argument.  It is mostly for internal use."""
    raise OperationError(space.w_TypeError, 
            space.wrap("bad argument type for built-in operation"))

@cpython_api([], lltype.Void)
def PyErr_BadInternalCall(space):
    raise OperationError(space.w_SystemError, space.wrap("Bad internal call!"))

@cpython_api([], PyObject, error=CANNOT_FAIL)
def PyErr_NoMemory(space):
    """This is a shorthand for PyErr_SetNone(PyExc_MemoryError); it returns NULL
    so an object allocation function can write return PyErr_NoMemory(); when it
    runs out of memory.
    Return value: always NULL."""
    PyErr_SetNone(space, space.w_MemoryError)

@cpython_api([PyObject], PyObject)
def PyErr_SetFromErrno(space, w_type):
    """
    This is a convenience function to raise an exception when a C library function
    has returned an error and set the C variable errno.  It constructs a
    tuple object whose first item is the integer errno value and whose
    second item is the corresponding error message (gotten from strerror()),
    and then calls PyErr_SetObject(type, object).  On Unix, when the
    errno value is EINTR, indicating an interrupted system call,
    this calls PyErr_CheckSignals(), and if that set the error indicator,
    leaves it set to that.  The function always returns NULL, so a wrapper
    function around a system call can write return PyErr_SetFromErrno(type);
    when the system call returns an error.
    Return value: always NULL."""
    # XXX Doesn't actually do anything with PyErr_CheckSignals.
    errno = get_errno()
    raise wrap_oserror(space, OSError(errno, "PyErr_SetFromErrno"))

@cpython_api([], rffi.INT_real, error=-1)
def PyErr_CheckSignals(space):
    """
    This function interacts with Python's signal handling.  It checks whether a
    signal has been sent to the processes and if so, invokes the corresponding
    signal handler.  If the signal module is supported, this can invoke a
    signal handler written in Python.  In all cases, the default effect for
    SIGINT is to raise the  KeyboardInterrupt exception.  If an
    exception is raised the error indicator is set and the function returns -1;
    otherwise the function returns 0.  The error indicator may or may not be
    cleared if it was previously set."""
    # XXX implement me
    return 0

@cpython_api([PyObject, PyObject], rffi.INT_real, error=CANNOT_FAIL)
def PyErr_GivenExceptionMatches(space, w_given, w_exc):
    """Return true if the given exception matches the exception in exc.  If
    exc is a class object, this also returns true when given is an instance
    of a subclass.  If exc is a tuple, all exceptions in the tuple (and
    recursively in subtuples) are searched for a match."""
    if (space.is_true(space.isinstance(w_given, space.w_BaseException)) or
        space.is_oldstyle_instance(w_given)):
        w_given_type = space.exception_getclass(w_given)
    else:
        w_given_type = w_given
    return space.exception_match(w_given_type, w_exc)

@cpython_api([PyObject], rffi.INT_real, error=CANNOT_FAIL)
def PyErr_ExceptionMatches(space, w_exc):
    """Equivalent to PyErr_GivenExceptionMatches(PyErr_Occurred(), exc).  This
    should only be called when an exception is actually set; a memory access
    violation will occur if no exception has been raised."""
    w_type = PyErr_Occurred(space)
    return PyErr_GivenExceptionMatches(space, w_type, w_exc)


@cpython_api([PyObject, CONST_STRING, rffi.INT_real], rffi.INT_real, error=-1)
def PyErr_WarnEx(space, w_category, message_ptr, stacklevel):
    """Issue a warning message.  The category argument is a warning category (see
    below) or NULL; the message argument is a message string.  stacklevel is a
    positive number giving a number of stack frames; the warning will be issued from
    the  currently executing line of code in that stack frame.  A stacklevel of 1
    is the function calling PyErr_WarnEx(), 2 is  the function above that,
    and so forth.
    
    This function normally prints a warning message to sys.stderr; however, it is
    also possible that the user has specified that warnings are to be turned into
    errors, and in that case this will raise an exception.  It is also possible that
    the function raises an exception because of a problem with the warning machinery
    (the implementation imports the warnings module to do the heavy lifting).
    The return value is 0 if no exception is raised, or -1 if an exception
    is raised.  (It is not possible to determine whether a warning message is
    actually printed, nor what the reason is for the exception; this is
    intentional.)  If an exception is raised, the caller should do its normal
    exception handling (for example, Py_DECREF() owned references and return
    an error value).
    
    Warning categories must be subclasses of Warning; the default warning
    category is RuntimeWarning.  The standard Python warning categories are
    available as global variables whose names are PyExc_ followed by the Python
    exception name. These have the type PyObject*; they are all class
    objects. Their names are PyExc_Warning, PyExc_UserWarning,
    PyExc_UnicodeWarning, PyExc_DeprecationWarning,
    PyExc_SyntaxWarning, PyExc_RuntimeWarning, and
    PyExc_FutureWarning.  PyExc_Warning is a subclass of
    PyExc_Exception; the other warning categories are subclasses of
    PyExc_Warning.
    
    For information about warning control, see the documentation for the
    warnings module and the -W option in the command line
    documentation.  There is no C API for warning control."""
    if w_category is None:
        w_category = space.w_None
    w_message = space.wrap(rffi.charp2str(message_ptr))
    w_stacklevel = space.wrap(stacklevel)

    w_module = PyImport_Import(space, space.wrap("warnings"))
    w_warn = space.getattr(w_module, space.wrap("warn"))
    space.call_function(w_warn, w_message, w_category, w_stacklevel)
    return 0

@cpython_api([PyObject, CONST_STRING], rffi.INT_real, error=-1)
def PyErr_Warn(space, w_category, message):
    """Issue a warning message.  The category argument is a warning category (see
    below) or NULL; the message argument is a message string.  The warning will
    appear to be issued from the function calling PyErr_Warn(), equivalent to
    calling PyErr_WarnEx() with a stacklevel of 1.
    
    Deprecated; use PyErr_WarnEx() instead."""
    return PyErr_WarnEx(space, w_category, message, 1)


