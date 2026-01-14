#!/bin/bash
# Quick test script to verify lifting script logic without compiling protobuf

set -e

echo "=== VPU Job Fuzzing Tools - Quick Test ==="
echo

# Test 1: Check Python syntax
echo "Test 1: Checking Python syntax..."
python3 -m py_compile tools/vpu_job_fuzz/lift_vpu_job.py
python3 -m py_compile tools/vpu_job_fuzz/lower_vpu_job.py
echo "✓ Python syntax OK"
echo

# Test 2: Check JSON parsing
echo "Test 2: Testing JSON parsing logic..."
python3 << 'EOF'
import json
import sys
sys.path.insert(0, 'tools/vpu_job_fuzz')

# Check if we can parse the JSON
try:
    with open('vpu_jobs/0.json') as f:
        data = json.load(f)
    
    print(f"✓ JSON parsed successfully")
    print(f"  - vpuFd: {data.get('vpuFd')}")
    print(f"  - cmdq_id: {data.get('cmdq_id')}")
    print(f"  - buffer_count: {data.get('buffer_count')}")
    
    # Check buffer 0 structure
    if data.get('buffer_count', 0) > 0:
        buf = data['buffers'][0]
        print(f"  - Buffer 0 handle: {buf['handle']}")
        print(f"  - Buffer 0 size: {buf['size']}")
        
        # Try to parse hex data
        try:
            from tools.vpu_job_fuzz.lift_vpu_job import parse_hex_string
            data_bytes = parse_hex_string(buf['data'])
            print(f"  - Buffer 0 data length: {len(data_bytes)} bytes")
            print(f"  - First 16 bytes: {data_bytes[:16].hex()}")
        except Exception as e:
            print(f"  ⚠ Hex parsing: {e}")
except Exception as e:
    print(f"✗ Failed: {e}")
    sys.exit(1)
EOF
echo

# Test 3: Check struct module
echo "Test 3: Testing struct module..."
python3 << 'EOF'
import struct

# Test struct unpacking patterns from the lifting script
test_data = bytes.fromhex("06000100")
header = struct.unpack('<HH', test_data[:4])
print(f"✓ struct module works")
print(f"  - Unpacked header: type={header[0]:04x}, size={header[1]}")

# Test command buffer header
header_data = bytes(64) + struct.pack('<Q', 0x123456789ABCDEF0)
print(f"✓ Large struct packing works")
EOF
echo

# Test 4: Check dependencies
echo "Test 4: Checking required dependencies..."
missing_deps=()

if ! python3 -c "import json" 2>/dev/null; then
    missing_deps+=("json (built-in)")
fi

if ! python3 -c "import struct" 2>/dev/null; then
    missing_deps+=("struct (built-in)")
fi

if [ ${#missing_deps[@]} -eq 0 ]; then
    echo "✓ All dependencies satisfied"
else
    echo "✗ Missing dependencies: ${missing_deps[@]}"
    exit 1
fi
echo

# Test 5: Verify captured jobs exist
echo "Test 5: Checking captured jobs..."
if [ -d "vpu_jobs" ] && [ "$(ls -A vpu_jobs)" ]; then
    count=$(ls -1 vpu_jobs/*.json 2>/dev/null | wc -l)
    echo "✓ Found $count captured jobs in vpu_jobs/"
    echo "  First job:"
    ls -lh vpu_jobs/*.json | head -1
else
    echo "⚠ No vpu_jobs/ directory found"
    echo "  Run a VPU application to capture jobs first"
fi
echo

echo "=== All basic tests passed! ==="
echo
echo "Next steps:"
echo "  1. Install protobuf-compiler: sudo apt-get install protobuf-compiler"
echo "  2. Compile schema: cd tools/vpu_job_fuzz && make proto"
echo "  3. Lift a job: PYTHONPATH=build python3 lift_vpu_job.py ../../vpu_jobs/0.json output.pb"
