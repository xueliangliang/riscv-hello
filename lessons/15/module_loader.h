#ifndef LESSON15_MODULE_LOADER_H
#define LESSON15_MODULE_LOADER_H
#include "formats.h"
typedef unsigned long Module;
Module module_load(const char *name);
void *module_symbol(Module handle, const char *name, unsigned signature);
int module_unload(Module handle);
unsigned long module_base(Module handle);
#endif
