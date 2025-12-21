import ctypes
import os
import sys

try:

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    LIB_PATH = os.path.join(BASE_DIR, "libmontecarlo.so")
    
    lib = ctypes.CDLL(LIB_PATH)
    print("Library loaded successfully.")
    
    # Test mc_list_candidate_drivers
    buffer = ctypes.create_string_buffer(256 * 128)
    count = lib.mc_list_candidate_drivers(buffer, 256)
    print(f"Candidates found: {count}")
    
    for i in range(count):
        offset = i * 128
        name = buffer[offset:offset+128].split(b'\0', 1)[0]
        print(f" - {name.decode()}")

except Exception as e:
    print(f"Failed: {e}")
    sys.exit(1)
