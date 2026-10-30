# LLVM compiler-rt source provenance

Unmodified Apache-2.0 WITH LLVM-exception upstream sources, llvmorg-19.1.7,
commit `cd708029e0b2869e80abe31ddb175f7c35361f90`, tag object
`f34bba6980332ba9447397fc8bd8a0951b224747`. LICENSE.TXT is verbatim.
Local integration and readable tests outside this directory use repository MIT.

UPSTREAM.json contains exact upstream paths, URLs, sizes and SHA256 for each
source/header/inc/license dependency; no objects or archives are vendored.
Selected C files: adddf3, subdf3, muldf3, divdf3, comparedf2, negdf2, fixdfdi,
fixunsdfdi, floatdidf, floatundidf, floatsidf, floatunsidf, fixdfsi, fixunsdfsi,
clzdi2, clzsi2, fp_mode. Headers/inc are their bounded upstream dependencies.
Build uses explicit source list (never wildcard test.c), RV64IMAC+Zicsr+Zifencei,
lp64, -ffreestanding -nostdinc -isystem GCC-own-include -D_LIBC_LIMITS_H_.
These header isolation flags apply ONLY to upstream helper compilation, avoiding
LP64D-only system glibc stubs without fake headers or mismatched libgcc.
Teaching int64 conversions use __floatdidf / __fixdfdi.
