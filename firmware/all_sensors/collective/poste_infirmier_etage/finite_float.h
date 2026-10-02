#pragma once
#include <stdint.h>
#include <string.h>
// ESP32 uses IEEE-754 binary32. Avoid Xtensa ULT.S, which the web simulator
// currently reports as unimplemented for the compiler's isfinite expansion.
inline bool finiteMeasurement(float value) {
  static_assert(sizeof(float) == sizeof(uint32_t), "Requires a 32-bit float");
  uint32_t bits;
  memcpy(&bits, &value, sizeof bits);
  return (bits & 0x7f800000u) != 0x7f800000u;
}
