from pypy.rpython.tool import rffi_platform as platform
from pypy.rlib import rposix
from pypy.rlib.rarithmetic import intmask

from pypy.interpreter.error import OperationError
from pypy.interpreter.gateway import ObjSpace, W_Root

from pypy.rlib import rlocale
from pypy.module.exceptions.interp_exceptions import _new_exception, W_Exception
from pypy.rpython.lltypesystem import lltype, rffi

W_Error = _new_exception('Error', W_Exception, 'locale error')

import sys

def make_error(space, msg):
    return OperationError(space.gettypeobject(W_Error.typedef), space.wrap(msg))

def rewrap_error(space, e):
    return OperationError(space.gettypeobject(W_Error.typedef),
                          space.wrap(e.message))

def _fixup_ulcase(space):
    stringmod = space.call_function(
        space.getattr(space.getbuiltinmodule('__builtin__'),
                      space.wrap('__import__')), space.wrap('string'))
    # create uppercase map string
    ul = []
    for c in xrange(256):
        if rlocale.isupper(c):
            ul.append(chr(c))
    space.setattr(stringmod, space.wrap('uppercase'), space.wrap(''.join(ul)))

    # create lowercase string
    ul = []
    for c in xrange(256):
        if rlocale.islower(c):
            ul.append(chr(c))
    space.setattr(stringmod, space.wrap('lowercase'), space.wrap(''.join(ul)))

    # create letters string
    ul = []
    for c in xrange(256):
        if rlocale.isalpha(c):
            ul.append(chr(c))
    space.setattr(stringmod, space.wrap('letters'), space.wrap(''.join(ul)))

def setlocale(space, category, w_locale=None):
    "(integer,string=None) -> string. Activates/queries locale processing."

    if space.is_w(w_locale, space.w_None) or w_locale is None:
        locale = None
    else:
        locale = space.str_w(w_locale)
    try:
        result = rlocale.setlocale(category, locale)
    except rlocale.LocaleError, e:
        raise rewrap_error(space, e)

    # record changes to LC_CTYPE
    if category in (rlocale.LC_CTYPE, rlocale.LC_ALL):
        _fixup_ulcase(space)

    return space.wrap(result)

setlocale.unwrap_spec = [ObjSpace, int, W_Root]

_lconv = lltype.Ptr(rlocale.cConfig.lconv)
_localeconv = rlocale.external('localeconv', [], _lconv)

def _w_copy_grouping(space, text):
    groups = [ space.wrap(ord(group)) for group in text ]
    if groups:
        groups.append(space.wrap(0))
    return space.newlist(groups)

def localeconv(space):
    "() -> dict. Returns numeric and monetary locale-specific parameters."
    lp = _localeconv()

    # Numeric information
    w_result = space.newdict()
    w = space.wrap
    space.setitem(w_result, w("decimal_point"),
                  w(rffi.charp2str(lp.c_decimal_point)))
    space.setitem(w_result, w("thousands_sep"),
                  w(rffi.charp2str(lp.c_thousands_sep)))
    space.setitem(w_result, w("grouping"),
                  _w_copy_grouping(space, rffi.charp2str(lp.c_grouping)))
    space.setitem(w_result, w("int_curr_symbol"),
                  w(rffi.charp2str(lp.c_int_curr_symbol)))
    space.setitem(w_result, w("currency_symbol"),
                  w(rffi.charp2str(lp.c_currency_symbol)))
    space.setitem(w_result, w("mon_decimal_point"),
                  w(rffi.charp2str(lp.c_mon_decimal_point)))
    space.setitem(w_result, w("mon_thousands_sep"),
                  w(rffi.charp2str(lp.c_mon_thousands_sep)))
    space.setitem(w_result, w("mon_grouping"),
                  _w_copy_grouping(space, rffi.charp2str(lp.c_mon_grouping)))
    space.setitem(w_result, w("positive_sign"),
                  w(rffi.charp2str(lp.c_positive_sign)))
    space.setitem(w_result, w("negative_sign"),
                  w(rffi.charp2str(lp.c_negative_sign)))
    space.setitem(w_result, w("int_frac_digits"),
                  w(lp.c_int_frac_digits))
    space.setitem(w_result, w("frac_digits"),
                  w(lp.c_frac_digits))
    space.setitem(w_result, w("p_cs_precedes"),
                  w(lp.c_p_cs_precedes))
    space.setitem(w_result, w("p_sep_by_space"),
                  w(lp.c_p_sep_by_space))
    space.setitem(w_result, w("n_cs_precedes"),
                  w(lp.c_n_cs_precedes))
    space.setitem(w_result, w("n_sep_by_space"),
                  w(lp.c_n_sep_by_space))
    space.setitem(w_result, w("p_sign_posn"),
                  w(lp.c_p_sign_posn))
    space.setitem(w_result, w("n_sign_posn"),
                  w(lp.c_n_sign_posn))

    return w_result

localeconv.unwrap_spec = [ObjSpace]

_strcoll = rlocale.external('strcoll', [rffi.CCHARP, rffi.CCHARP], rffi.INT)
_wcscoll = rlocale.external('wcscoll', [rffi.CWCHARP, rffi.CWCHARP], rffi.INT)

def strcoll(space, w_s1, w_s2):
    "string,string -> int. Compares two strings according to the locale."

    if space.is_true(space.isinstance(w_s1, space.w_str)) and \
       space.is_true(space.isinstance(w_s2, space.w_str)):

        s1, s2 = space.str_w(w_s1), space.str_w(w_s2)
        return space.wrap(_strcoll(rffi.str2charp(s1), rffi.str2charp(s2)))

    #if not space.is_true(space.isinstance(w_s1, space.w_unicode)) and \
    #   not space.is_true(space.isinstance(w_s2, space.w_unicode)):
    #    raise OperationError(space.w_ValueError,
    #                         space.wrap("strcoll arguments must be strings"))

    s1, s2 = space.unicode_w(w_s1), space.unicode_w(w_s2)

    s1_c = rffi.unicode2wcharp(s1)
    s2_c = rffi.unicode2wcharp(s2)
    result = _wcscoll(s1_c, s2_c)
    return space.wrap(result)

strcoll.unwrap_spec = [ObjSpace, W_Root, W_Root]

_strxfrm = rlocale.external('strxfrm',
                    [rffi.CCHARP, rffi.CCHARP, rffi.SIZE_T], rffi.SIZE_T)

def strxfrm(space, s):
    "string -> string. Returns a string that behaves for cmp locale-aware."
    n1 = len(s) + 1

    buf = lltype.malloc(rffi.CCHARP.TO, n1, flavor="raw", zero=True)
    n2 = _strxfrm(buf, rffi.str2charp(s), n1) + 1
    if n2 > n1:
        # more space needed
        lltype.free(buf, flavor="raw")
        buf = lltype.malloc(rffi.CCHARP.TO, intmask(n2),
                            flavor="raw", zero=True)
        _strxfrm(buf, rffi.str2charp(s), n2)

    val = rffi.charp2str(buf)
    lltype.free(buf, flavor="raw")

    return space.wrap(val)

strxfrm.unwrap_spec = [ObjSpace, str]

if rlocale.HAVE_LANGINFO:

    def nl_langinfo(space, key):
        """nl_langinfo(key) -> string
        Return the value for the locale information associated with key."""

        try:
            return space.wrap(rlocale.nl_langinfo(key))
        except ValueError:
            raise OperationError(space.w_ValueError,
                                 space.wrap("unsupported langinfo constant"))

    nl_langinfo.unwrap_spec = [ObjSpace, int]

#___________________________________________________________________
# HAVE_LIBINTL dependence

if rlocale.HAVE_LIBINTL:
    _gettext = rlocale.external('gettext', [rffi.CCHARP], rffi.CCHARP)

    def gettext(space, msg):
        """gettext(msg) -> string
        Return translation of msg."""
        return space.wrap(rffi.charp2str(_gettext(rffi.str2charp(msg))))

    gettext.unwrap_spec = [ObjSpace, str]

    _dgettext = rlocale.external('dgettext', [rffi.CCHARP, rffi.CCHARP], rffi.CCHARP)

    def dgettext(space, w_domain, msg):
        """dgettext(domain, msg) -> string
        Return translation of msg in domain."""
        if space.is_w(w_domain, space.w_None):
            domain = None
            result = _dgettext(domain, rffi.str2charp(msg))
        else:
            domain = space.str_w(w_domain)
            result = _dgettext(rffi.str2charp(domain), rffi.str2charp(msg))

        return space.wrap(rffi.charp2str(result))

    dgettext.unwrap_spec = [ObjSpace, W_Root, str]

    _dcgettext = rlocale.external('dcgettext', [rffi.CCHARP, rffi.CCHARP, rffi.INT],
                                                                rffi.CCHARP)

    def dcgettext(space, w_domain, msg, category):
        """dcgettext(domain, msg, category) -> string
        Return translation of msg in domain and category."""

        if space.is_w(w_domain, space.w_None):
            domain = None
            result = _dcgettext(domain, rffi.str2charp(msg),
                                rffi.cast(rffi.INT, category))
        else:
            domain = space.str_w(w_domain)
            result = _dcgettext(rffi.str2charp(domain), rffi.str2charp(msg),
                                rffi.cast(rffi.INT, category))

        return space.wrap(rffi.charp2str(result))

    dcgettext.unwrap_spec = [ObjSpace, W_Root, str, int]


    _textdomain = rlocale.external('textdomain', [rffi.CCHARP], rffi.CCHARP)

    def textdomain(space, w_domain):
        """textdomain(domain) -> string
        Set the C library's textdomain to domain, returning the new domain."""

        if space.is_w(w_domain, space.w_None):
            domain = None
            result = _textdomain(domain)
        else:
            domain = space.str_w(w_domain)
            result = _textdomain(rffi.str2charp(domain))

        return space.wrap(rffi.charp2str(result))

    textdomain.unwrap_spec = [ObjSpace, W_Root]

    _bindtextdomain = rlocale.external('bindtextdomain', [rffi.CCHARP, rffi.CCHARP],
                                                                rffi.CCHARP)

    def bindtextdomain(space, domain, w_dir):
        """bindtextdomain(domain, dir) -> string
        Bind the C library's domain to dir."""

        if space.is_w(w_dir, space.w_None):
            dir = None
            dirname = _bindtextdomain(rffi.str2charp(domain), dir)
        else:
            dir = space.str_w(w_dir)
            dirname = _bindtextdomain(rffi.str2charp(domain),
                                        rffi.str2charp(dir))

        if not dirname:
            errno = rposix.get_errno()
            raise OperationError(space.w_OSError, space.wrap(errno))
        return space.wrap(rffi.charp2str(dirname))

    bindtextdomain.unwrap_spec = [ObjSpace, str, W_Root]

    _bind_textdomain_codeset = rlocale.external('bind_textdomain_codeset',
                                    [rffi.CCHARP, rffi.CCHARP], rffi.CCHARP)

    if rlocale.HAVE_BIND_TEXTDOMAIN_CODESET:
        def bind_textdomain_codeset(space, domain, w_codeset):
            """bind_textdomain_codeset(domain, codeset) -> string
            Bind the C library's domain to codeset."""

            if space.is_w(w_codeset, space.w_None):
                codeset = None
                result = _bind_textdomain_codeset(
                                            rffi.str2charp(domain), codeset)
            else:
                codeset = space.str_w(w_codeset)
                result = _bind_textdomain_codeset(rffi.str2charp(domain),
                                                rffi.str2charp(codeset))

            if not result:
                return space.w_None
            else:
                return space.wrap(rffi.charp2str(result))

        bind_textdomain_codeset.unwrap_spec = [ObjSpace, str, W_Root]

#___________________________________________________________________
# getdefaultlocale() implementation for Windows and MacOSX

if sys.platform == 'win32':
    from pypy.rlib import rwin32
    LCID = LCTYPE = rwin32.DWORD
    GetACP = rlocale.external('GetACP',
                      [], rffi.INT,
                      calling_conv='win')
    GetLocaleInfo = rlocale.external('GetLocaleInfoA',
                             [LCID, LCTYPE, rwin32.LPSTR, rffi.INT], rffi.INT,
                             calling_conv='win')

    def getdefaultlocale(space):
        encoding = "cp%d" % GetACP()

        BUFSIZE = 50
        buf_lang = lltype.malloc(rffi.CCHARP.TO, BUFSIZE, flavor='raw')
        buf_country = lltype.malloc(rffi.CCHARP.TO, BUFSIZE, flavor='raw')

        try:
            if (GetLocaleInfo(cConfig.LOCALE_USER_DEFAULT,
                              cConfig.LOCALE_SISO639LANGNAME,
                              buf_lang, BUFSIZE) and
                GetLocaleInfo(cConfig.LOCALE_USER_DEFAULT,
                              cConfig.LOCALE_SISO3166CTRYNAME,
                              buf_country, BUFSIZE)):
                lang = rffi.charp2str(buf_lang)
                country = rffi.charp2str(buf_country)
                return space.newtuple([space.wrap("%s_%s" % (lang, country)),
                                       space.wrap(encoding)])

            # If we end up here, this windows version didn't know about
            # ISO639/ISO3166 names (it's probably Windows 95).  Return the
            # Windows language identifier instead (a hexadecimal number)
            elif GetLocaleInfo(cConfig.LOCALE_USER_DEFAULT,
                               cConfig.LOCALE_IDEFAULTLANGUAGE,
                               buf_lang, BUFSIZE):
                lang = rffi.charp2str(buf_lang)
                return space.newtuple([space.wrap("0x%s" % lang),
                                       space.wrap(encoding)])
            else:
                return space.newtuple([space.w_None, space.wrap(encoding)])
        finally:
            lltype.free(buf_lang, flavor='raw')
            lltype.free(buf_country, flavor='raw')
