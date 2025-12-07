import ctypes
import os
import sys

try:
    lib = ctypes.CDLL(os.path.abspath("./libmontecarlo.so"))
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
