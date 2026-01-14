# VPU Job Fuzzing Tools

Tools for lifting VPU job binaries to Protobuf format and back, enabling structure-aware fuzzing of the Intel VPU driver and firmware.

## Overview

This toolset provides:

- **Lifting**: Convert captured VPU job binaries (JSON format) to structured Protobuf
- **Lowering**: Convert Protobuf back to binary for submission to the driver
- **Documentation**: Complete memory layout documentation

This enables structure-aware fuzzing using libprotobuf-mutator (LPM) instead of blind bit-flipping.

## Project Structure

```
vpu_job_fuzz/
├── vpu_job.proto           # Protobuf schema definition
├── lift_vpu_job.py        # Binary -> Protobuf converter
├── lower_vpu_job.py       # Protobuf -> Binary converter
├── Makefile               # Build automation
└── memory.md              # Memory layout documentation
```

## Quick Start

### Prerequisites

```bash
# Install protobuf compiler
sudo apt-get install -y protobuf-compiler python3-protobuf

# Optional: Install for fuzzing
sudo apt-get install -y libprotobuf-dev
```

### Build

```bash
cd tools/vpu_job_fuzz
make proto
```

### Usage

#### Lifting (Binary -> Protobuf)

```bash
# Lift a captured job to Protobuf
python3 lift_vpu_job.py ../../vpu_jobs/0.json output.pb

# Or with build directory in path
PYTHONPATH=build python3 lift_vpu_job.py ../../vpu_jobs/0.json output.pb
```

#### Lowering (Protobuf -> Binary)

```bash
# Convert Protobuf back to JSON (for testing round-trip)
PYTHONPATH=build python3 lower_vpu_job.py output.pb output_lowered.json
```

#### Interactive Parsing

```bash
python3 -c "
import sys
sys.path.insert(0, 'build')
import vpu_job_pb2

job = vpu_job_pb2.VpuJob()
with open('output.pb', 'rb') as f:
    job.ParseFromString(f.read())

print(f'VPU FD: {job.vpu_fd}')
print(f'CmdQ ID: {job.cmdq_id}')
print(f'Buffer count: {job.buffer_count}')
"
```

## Fuzzing Workflow

### 1. Capture Seeds

Jobs are automatically captured in `VPUDriverApi::commandQueueSubmit()`:

```cpp
// vpu_driver/source/os_interface/vpu_driver_api.cpp
// Jobs are saved to ./vpu_jobs/{job_counter}.json
```

### 2. Lift to Protobuf

```bash
# Lift all captured jobs
for f in ../../vpu_jobs/*.json; do
    PYTHONPATH=build python3 lift_vpu_job.py "$f" "corpus/$(basename $f .json).pb"
done
```

### 3. Create Fuzzer Harness

Example C++ harness using libFuzzer and LPM:

```cpp
#include "vpu_job.pb.h"
#include "libprotobuf-mutator/src/libfuzzer/libfuzzer_macro.h"

DEFINE_PROTO_FUZZER(const vpu_job::VpuJob& job) {
    // 1. Lower Protobuf to binary
    std::string binary_job = LowerJobToBinary(job);

    // 2. Submit to driver via ioctl
    SubmitToVpuDriver(binary_job);

    return 0;
}
```

### 4. Mutate and Fuzz

```bash
# Build fuzzer with LPM
clang++ -fsanitize=fuzzer \
    -I$(pkg-config --cflags protobuf) \
    -lprotobuf-mutator-libfuzzer \
    harness.cpp vpu_job.pb.cc -o vpu_fuzzer

# Run fuzzer
./vpu_fuzzer corpus/
```

## Protobuf Schema

### VpuJob

Complete job submission structure:

```protobuf
message VpuJob {
    uint32 vpu_fd = 1;
    uint32 cmdq_id = 2;
    uint64 buffers_ptr = 3;
    uint32 buffer_count = 4;
    repeated VpuBuffer buffers = 5;
    uint32 commands_offset = 6;
    uint32 preempt_buffer_index = 7;
}
```

### VpuCommandBuffer

Parsed command buffer with all commands:

```protobuf
message VpuCommandBuffer {
    CommandHeaderPrefix prefix = 1;
    VpuCmdBufferHeader header = 2;
    VpuInternalFenceSync internal_sync = 3;
    repeated VpuCommand commands = 4;
}
```

### Supported Commands

- **NOP**: No operation
- **TIMESTAMP**: Query timestamp
- **FENCE_WAIT**: Wait for fence value
- **FENCE_SIGNAL**: Signal fence value
- **BARRIER**: Memory barrier
- **METRIC_QUERY**: Begin/end metric query
- **MEMORY_FILL**: Fill memory region
- **COPY**: Copy memory
- **INFERENCE_EXECUTE**: Execute inference

## Memory Layout

For detailed memory layout information, see [memory.md](memory.md).

### Command Buffer Structure

```
+-------------------+ 0x00
| Context Save Area | 64 bytes
+-------------------+ 0x40
| Fence Value       | 8 bytes
+-------------------+ 0x48
| Reserved          | 56 bytes
+-------------------+ 0x80
| Cmd Buffer Header | 64 bytes
+-------------------+ 0xC0
| Internal Fences  | 2 * 24 bytes
+-------------------+ 0xF0
| Command List      | Variable
+-------------------+
| Descriptor Heap   | Variable (64B aligned)
+-------------------+
```

## Command Types

| Type  | Name                 | Description |
|-------|----------------------|-------------|
| 0x0001 | VPU_CMD_NOP          | No operation |
| 0x0100 | VPU_CMD_TIMESTAMP     | Query timestamp |
| 0x0101 | VPU_CMD_FENCE_WAIT    | Wait for fence |
| 0x0102 | VPU_CMD_FENCE_SIGNAL  | Signal fence |
| 0x0103 | VPU_CMD_BARRIER       | Memory barrier |
| 0x0104 | VPU_CMD_METRIC_QUERY_BEGIN | Start metric query |
| 0x0105 | VPU_CMD_METRIC_QUERY_END   | End metric query |
| 0x0202 | VPU_CMD_MEMORY_FILL  | Fill memory with pattern |
| 0x0302 | VPU_CMD_COPY          | Copy memory |
| 0x0306 | VPU_CMD_INFERENCE_EXECUTE | Execute inference |

## Testing

### Test Lifting and Lowering

```bash
make test
```

### Manual Round-Trip Test

```bash
# Lift
PYTHONPATH=build python3 lift_vpu_job.py ../../vpu_jobs/0.json test.pb

# Lower back to JSON
PYTHONPATH=build python3 lower_vpu_job.py test.pb test_lowered.json

# Compare (should have identical structure)
diff <(python3 -c "import json; print(json.dumps(json.load(open('../../vpu_jobs/0.json')), sort_keys=True))" \
     <(python3 -c "import json; print(json.dumps(json.load(open('test_lowered.json')), sort_keys=True))
```

## Troubleshooting

### ImportError: No module named 'vpu_job_pb2'

```bash
# Compile the protobuf schema first
make proto
# Then run with PYTHONPATH
PYTHONPATH=build python3 lift_vpu_job.py ...
```

### Protobuf version mismatch

```bash
# Check protobuf version
protoc --version

# Update if needed
sudo apt-get install -y protobuf-compiler python3-protobuf
```

## References

- [memory.md](memory.md) - Complete memory layout documentation
- `firmware/include/api/vpu_jsm_job_cmd_api.h` - Firmware API definitions
- `firmware/include/api/vpu_jsm_api.h` - JSM shared API
- `linux/include/uapi/drm/ivpu_accel.h` - Kernel UAPI definitions
- `umd/vpu_driver/source/command/command_buffer.hpp` - Command buffer implementation

## License

Same as parent project: MIT
