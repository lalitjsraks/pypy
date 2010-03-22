#ifndef _PYPY_LL_GROUP_H_
#define _PYPY_LL_GROUP_H_

/* Support code for CombinedSymbolics */


#if PYPY_LONG_BIT == 32 /************************************/
/* On 32-bit platforms, a CombinedSymbolic is two USHORTs, and the
   lower one stores the offset inside the group, divided by 4.  The
   limitation is to have at most 256KB of data in the whole group. */

typedef unsigned short pypy_halfword_t;

#define GROUP_MEMBER_OFFSET(grouptype, groupname, membername)           \
  ((unsigned short)(((long)&((grouptype*)NULL)->membername) / 4))

#define _OP_GET_GROUP_MEMBER(groupptr, compactoffset)  \
  (((char*)groupptr) + ((long)compactoffset)*4)

#define _OP_GET_NEXT_GROUP_MEMBER(groupptr, compactoffset, skipoffset)  \
  ((((char*)groupptr) + skipoffset) + ((long)compactoffset)*4)

/* A macro to crash at compile-time if sizeof(group) is too large.
   Uses a hack that I've found on some random forum.  Haaaaaaaaaackish. */
#define PYPY_GROUP_CHECK_SIZE(groupname, lastname)   \
  { typedef char group_##groupname##_is_too_large[   \
	2*(sizeof(groupname) <= 65536*4)-1]; }


#else /******************************************************/
/* On 64-bit platforms, a CombinedSymbolic is two UINTs, and the lower
   one stores a real pointer to the group memeber.  The limitation is
   that this pointer must fit inside 32-bit, i.e. the whole group must
   be located in the first 32 bits of address space. */

typedef unsigned int pypy_halfword_t;

#define GROUP_MEMBER_OFFSET(grouptype, groupname, membername)   \
  ((long)(&groupname.membername))

#define _OP_GET_GROUP_MEMBER(groupptr, compactoffset)  \
  ((long)compactoffset)

#define _OP_GET_NEXT_GROUP_MEMBER(groupptr, compactoffset, skipoffset)  \
  ((long)compactoffset + skipoffset)

/* A macro to check at run-time if the group is below the 32-bit limit. */
#define PYPY_GROUP_CHECK_SIZE(groupname, lastname)          \
  if ((unsigned long)(&groupname.lastname) > 0xFFFFFFFF)    \
    error = "group " #groupname " is not located in the "   \
            "initial 32 bits of address space"


#endif /*****************************************************/


#define OP_IS_GROUP_MEMBER_NONZERO(compactoffset, r)  \
  r = (compactoffset != 0)

#define OP_EXTRACT_USHORT(value, r)         r = (pypy_halfword_t)value
#define OP_COMBINE_USHORT(ushort, rest, r)  r = ((long)ushort) | rest

#endif /* _PYPY_LL_GROUP_H_ */
