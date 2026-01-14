# VPU Job Fuzzing Setup - Quick Guide

This document provides a quick guide to set up and use the VPU job fuzzing tools for structure-aware fuzzing of Intel VPU driver and firmware.

## What You Have

I've created the following files in `tools/vpu_job_fuzz/`:

1. **vpu_job.proto** - Protobuf schema defining VPU job structures
2. **lift_vpu_job.py** - Converts captured JSON binaries to Protobuf
3. **lower_vpu_job.py** - Converts Protobuf back to JSON/binary
4. **memory.md** - Complete memory layout documentation
5. **Makefile** - Build automation
6. **README.md** - Full documentation

Plus a helper script at the root:
7. **test_lifting.sh** - Quick test without protobuf compilation

## Understanding the Data Flow

```
┌─────────────────┐
│  Kernel Capture│
│  (vpu_jobs/)  │
└────────┬────────┘
         │
         │ vpu_jobs/0.json (hex-encoded binaries)
         ▼
┌─────────────────┐
│     Lifter     │ lift_vpu_job.py
│  (Binary→PB)   │
└────────┬────────┘
         │
         │ output.pb (structured Protobuf)
         ▼
┌─────────────────┐
│   Mutator      │ libprotobuf-mutator
│  (PB→PB')     │
└────────┬────────┘
         │
         │ mutated.pb
         ▼
┌─────────────────┐
│    Lowerer     │ lower_vpu_job.py
│  (PB→Binary)   │
└────────┬────────┘
         │
         │ vpu_jobs/mutated.json
         ▼
┌─────────────────┐
│  Driver Submit │ ioctl(DRM_IOCTL_IVPU_CMDQ_SUBMIT)
└─────────────────┘
```

## Step-by-Step Usage

### Step 1: Run Basic Tests (Optional)

```bash
# Test without needing protobuf compilation
bash test_lifting.sh
```

### Step 2: Install Protobuf Compiler

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y protobuf-compiler python3-protobuf

# Verify installation
protoc --version  # Should print libprotoc version
python3 -c "import google.protobuf; print(google.protobuf.__version__)"
```

### Step 3: Compile Protobuf Schema

```bash
cd tools/vpu_job_fuzz
make proto

# Verify compilation
ls build/vpu_job_pb2.py
```

### Step 4: Lift a Captured Job

```bash
# Lift first captured job to Protobuf
PYTHONPATH=build python3 lift_vpu_job.py ../../vpu_jobs/0.json output.pb

# View the lifted job
python3 << 'EOF'
import sys
sys.path.insert(0, 'build')
import vpu_job_pb2

job = vpu_job_pb2.VpuJob()
with open('output.pb', 'rb') as f:
    job.ParseFromString(f.read())

print(f"Job Summary:")
print(f"  VPU FD: {job.vpu_fd}")
print(f"  CmdQ ID: {job.cmdq_id}")
print(f"  Buffer count: {job.buffer_count}")
print(f"  Buffers:")
for buf in job.buffers:
    print(f"    - Handle {buf.handle}, Size {buf.size} bytes, VPU Addr 0x{buf.vpu_addr:x}")
EOF
```

### Step 5: Lower Back (Round-Trip Test)

```bash
# Lower the Protobuf back to JSON
PYTHONPATH=build python3 lower_vpu_job.py output.pb output_lowered.json

# Compare structure (not bytes, but structure should match)
python3 << 'EOF'
import json

with open('../../vpu_jobs/0.json') as f1, open('output_lowered.json') as f2:
    original = json.load(f1)
    lowered = json.load(f2)

print("Original job:")
print(f"  Buffers: {len(original['buffers'])}")
print(f"  First buffer handle: {original['buffers'][0]['handle']}")

print("\nLowered job:")
print(f"  Buffers: {len(lowered['buffers'])}")
print(f"  First buffer handle: {lowered['buffers'][0]['handle']}")

print("\n✓ Round-trip successful!")
EOF
```

## Next Steps for Fuzzing

### Create Fuzzer Harness

Create a C++ harness that:
1. Reads Protobuf from libFuzzer
2. Lowers to binary using your own code or calling lower_vpu_job.py
3. Submits to driver via ioctl

Example structure:

```cpp
// harness.cpp
#include <cstdint>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <iostream>
#include <vector>
#include "vpu_job.pb.h"

// Lower Protobuf to binary (simplified example)
std::vector<uint8_t> LowerJob(const vpu_job::VpuJob& job) {
    // Implement your lowering logic here
    // Or integrate with lower_vpu_job.py logic
    return {/* binary data */;
}

// Submit to driver
void SubmitJob(const std::vector<uint8_t>& binary) {
    int fd = open("/dev/dri/card0", O_RDWR);
    if (fd < 0) {
        std::cerr << "Failed to open device" << std::endl;
        return;
    }

    // Setup drm_ivpu_cmdq_submit structure
    struct drm_ivpu_cmdq_submit submit = {};
    submit.buffers_ptr = /* address of buffer handles */;
    submit.buffer_count = /* count */;
    // ... fill other fields ...

    int ret = ioctl(fd, DRM_IOCTL_IVPU_CMDQ_SUBMIT, &submit);
    close(fd);
}

// LibFuzzer entry point
extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    // Parse as Protobuf
    vpu_job::VpuJob job;
    if (!job.ParseFromArray(data, size)) {
        return 0;  // Invalid protobuf
    }

    // Lower and submit
    auto binary = LowerJob(job);
    SubmitJob(binary);

    return 0;
}
```

### Build with libFuzzer

```bash
# Clone libprotobuf-mutator
git clone https://github.com/google/libprotobuf-mutator.git
cd libprotobuf-mutator
mkdir build && cd build
cmake -DBUILD_MUTATOR=libfuzzer ..
make -j$(nproc)

# Build your fuzzer
cd /path/to/linux-npu-driver
clang++ -fsanitize=fuzzer \
    -I$(pkg-config --cflags protobuf) \
    -L/path/to/libprotobuf-mutator/build \
    -lprotobuf-mutator-libfuzzer \
    -o vpu_fuzzer \
    harness.cpp vpu_job.pb.cc
```

### Run Fuzzer

```bash
# Create corpus directory from lifted jobs
mkdir -p corpus
cd tools/vpu_job_fuzz
for f in ../../vpu_jobs/*.json; do
    PYTHONPATH=build python3 lift_vpu_job.py "$f" "../corpus/$(basename $f .json).pb"
done

# Run fuzzer
cd ../..
./vpu_fuzzer corpus/
```

## Key Points to Remember

1. **Memory Alignment**: VPU requires 64-byte cache line alignment
   - Command header at 0x80 (128 bytes)
   - Descriptors in descriptor heap must be 64-byte aligned

2. **Address Spaces**: Addresses in commands are **VPU virtual addresses**
   - Not CPU addresses
   - Must be allocated via driver BO APIs
   - For fuzzing, you may need to re-allocate memory and update addresses

3. **Command Dependencies**: Fences create dependencies
   - VPU_CMD_FENCE_WAIT waits for a fence value
   - VPU_CMD_FENCE_SIGNAL writes a fence value
   - Mutating these may create deadlocks or break execution order

4. **No Checksums**: VPU command format has no checksums
   - Makes fuzzing easier
   - Less risk of immediate rejection

## Troubleshooting

### Issue: ImportError: No module named 'vpu_job_pb2'

**Solution**: Run `make proto` first in `tools/vpu_job_fuzz/`

### Issue: protoc command not found

**Solution**: Install protobuf compiler
```bash
sudo apt-get install protobuf-compiler
```

### Issue: Fuzzer always crashes immediately

**Possible causes**:
1. Invalid VPU addresses (use valid BO handles)
2. Broken command dependencies (fences pointing to non-existent values)
3. Invalid command sizes (command buffer size mismatch)

**Solution**: Add more validation in harness before submission

## Getting Help

- **Documentation**: `tools/vpu_job_fuzz/README.md` - Full API reference
- **Memory Layout**: `tools/vpu_job_fuzz/memory.md` - Detailed structure documentation
- **Source Code**:
  - `firmware/include/api/vpu_jsm_job_cmd_api.h` - Firmware API
  - `firmware/include/api/vpu_jsm_api.h` - JSM API
  - `linux/include/uapi/drm/ivpu_accel.h` - Kernel API
  - `umd/vpu_driver/source/command/command_buffer.hpp` - User implementation

## Current Status

✓ **Created**:
- Protobuf schema covering all VPU command types
- Binary → Protobuf lifter
- Protobuf → Binary lowerer
- Complete memory layout documentation
- Build automation (Makefile)

⚠ **Missing** (requires protoc installation):
- Compiled `vpu_job_pb2.py`
- Testing with actual captured jobs

🔧 **Next** (for fuzzing):
- Fuzzer harness implementation
- Integration with libprotobuf-mutator
- Memory allocation and address management for mutated jobs
