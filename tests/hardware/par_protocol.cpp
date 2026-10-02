#include <initializer_list>
#include <cstring>
#include <cassert>
#include "../../firmware/all_sensors/src/protocols.h"
int main() {
  // Section 13.5's printed D2 conflicts with the modulo-256 rule in section 11.3.
  // The sum for these exact bytes is 0x40; do not weaken validation for that typo.
  const char sample[]="\x02S1;A0;C03;M00;P125080090;R075;T0005;;40\x03";
  NibpStatus s;
  assert(nibpStatus(reinterpret_cast<const uint8_t*>(sample),sizeof(sample)-1,s));
  assert(s.measurement&&s.sys==125&&s.dia==80&&s.mean==90);
  char invalid[sizeof(sample)];memcpy(invalid,sample,sizeof(sample));invalid[38]='D';invalid[39]='2';
  assert(!nibpStatus(reinterpret_cast<uint8_t*>(invalid),sizeof(invalid)-1,s));
  assert(!nibpStatus(reinterpret_cast<const uint8_t*>(sample),10,s));
  // Manufacturer section 13.6: an error may contain a PREVIOUS valid pressure.
  const char leak[]="\x02S2;A0;C00;M07;P120078090;R060;T    ;;FC\x03";
  assert(nibpStatus(reinterpret_cast<const uint8_t*>(leak),sizeof(leak)-1,s));
  assert(!s.measurement&&s.error==7);
}
