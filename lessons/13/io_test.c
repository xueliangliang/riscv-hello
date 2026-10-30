/* Disposable actual-U IOERR fixture; never seeded in the normal run image. */
#include "syscall.h"
#include "module_loader.h"
static unsigned char target[4096];
int app_main(void)
{
    for (unsigned i = 0; i < sizeof(target); i++) {
        target[i] = 0x5a;
    }
    long result = syscall3(SYS_READFILE, (unsigned long)"math.dll",
                           (unsigned long)target, sizeof(target));
    require(result == F_IO, "FAIL expected actual snapshot IOERR\n");
    for (unsigned i = 0; i < sizeof(target); i++) {
        require(target[i] == 0x5a, "FAIL IOERR copied partial snapshot\n");
    }
    require(!module_load("math.dll"), "FAIL IOERR activated module\n");
    require(!module_symbol(1, "ceil", DLL_UNARY), "FAIL failed module lookup\n");
    require(module_unload(1) < 0, "FAIL failed module unload\n");
    say("CHECK actual U IOERR snapshot unchanged and module inactive\n");
    return 43;
}
