#include <cassert>
#include <initializer_list>
#include <limits>
#include "../../firmware/all_sensors/collective_src/finite_float.h"
int main() {
  for(float value : {0.f, -0.f, 36.5f, -40.f, std::numeric_limits<float>::max(), std::numeric_limits<float>::denorm_min()}) {
    assert(finiteMeasurement(value));
  }
  assert(!finiteMeasurement(std::numeric_limits<float>::infinity()));
  assert(!finiteMeasurement(-std::numeric_limits<float>::infinity()));
  assert(!finiteMeasurement(std::numeric_limits<float>::quiet_NaN()));
}
