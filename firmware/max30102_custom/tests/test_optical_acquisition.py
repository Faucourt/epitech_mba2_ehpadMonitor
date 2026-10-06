"""Native C++ regression tests for the production optical acquisition function.

Run with CXX=g++ (or clang++). The harness supplies I2C faults and checks which
samples reach the algorithm; it does not claim to validate the optical algorithm.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpticalAcquisitionTest(unittest.TestCase):
    def test_production_acquisition(self):
        compiler = shutil.which(os.environ.get('CXX', 'g++'))
        if not compiler:
            self.skipTest('C++ compiler required; also runnable in chip toolchain container')
        source = (ROOT / 'simulation/sensors.h').read_text(encoding='utf-8')
        function = source[source.index('void readOptical() {'):source.index('\nvoid readSerialSensor()')]
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / 'read_optical_under_test.h').write_text(function, encoding='utf-8')
            executable = temp / ('optical.exe' if os.name == 'nt' else 'optical')
            subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(temp),
                            str(ROOT / 'tests/optical_acquisition.cpp'), '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
