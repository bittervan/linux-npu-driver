# VPU Job Memory Structure Documentation

This document describes the memory layout and data structures used in VPU job submissions, as captured from the Intel VPU (Vision Processing Unit) driver.

## Overview

The VPU driver submits jobs to the firmware via the `DRM_IOCTL_IVPU_CMDQ_SUBMIT` ioctl, which passes a batch of buffers to the NPU for execution. This document documents the structure of these buffers based on the captured `vpu_jobs` data.

## Job Submission Structure

### drm_ivpu_cmdq_submit

The main submission structure passed via ioctl:

```c
struct drm_ivpu_cmdq_submit {
    __u64 buffers_ptr;           // Pointer to array of GEM handles
    __u32 buffer_count;          // Number of buffers in the array
    __u32 cmdq_id;              // Command queue ID
    __u32 flags;                // Reserved, must be zero
    __u32 commands_offset;        // Offset to first command in buffer 0
    __u32 preempt_buffer_index;  // Index of preempt buffer in buffers_ptr
    __u32 reserved;
};
```

### Buffer Organization

1. **Buffer 0**: Command Buffer (contains the job commands)
2. **Buffer 1**: Host Parsed Inference (HPI) - contains inference metadata and resource requirements
3. **Buffer 2-N**: Associated data buffers (weights, inputs, outputs, kernel data, etc.)

## Command Buffer Structure

The command buffer (first buffer in `buffers_ptr`) has the following layout:

```
+-------------------+ 0x00
| Context Save Area | 64 bytes
+-------------------+ 0x40
| Fence Value       | 8 bytes
+-------------------+ 0x48
| Reserved          | 56 bytes (7 * uint64)
+-------------------+ 0x80
| vpu_cmd_buffer_header | 64 bytes
+-------------------+ 0xC0
| Internal Fence[0] | 24 bytes
+-------------------+ 0xD8
| Internal Fence[1] | 24 bytes
+-------------------+ 0xF0
| Command List      | variable size
+-------------------+
| Descriptor Heap   | variable size (64-byte aligned)
+-------------------+
```

All structures are packed with 8-byte alignment and 64-byte cache line alignment requirements.

### vpu_cmd_buffer_header

Located at offset 0x80 (128) from buffer start:

```c
struct vpu_cmd_buffer_header {
    uint32_t cmd_buffer_size;              // Total size of command buffer
    uint32_t cmd_offset;                   // Offset to first command
    uint32_t api_version;                 // API version (major << 16 | minor)
    uint32_t reserved_0;
    uint64_t descriptor_heap_base_address;  // VPU address of descriptor heap
    uint64_t submission_timestamp;         // Submission timestamp (microseconds)
    uint64_t fence_heap_base_address;      // VPU address of fence heap
    uint64_t context_save_area_address;   // VPU address of context save area
};
```

## Command Structure

All commands share a common header:

```c
struct vpu_cmd_header {
    uint16_t type;    // Command type (see VPU_CMD_TYPE)
    uint16_t size;    // Size of command in bytes (including header)
};
```

### Supported Commands

| Type ID | Name           | Size (min) | Description |
|---------|----------------|-------------|-------------|
| 0x0001 | VPU_CMD_NOP | 4 bytes | No operation |
| 0x0100 | VPU_CMD_TIMESTAMP | 16 bytes | Query timestamp |
| 0x0101 | VPU_CMD_FENCE_WAIT | 24 bytes | Wait for fence |
| 0x0102 | VPU_CMD_FENCE_SIGNAL | 24 bytes | Signal fence |
| 0x0103 | VPU_CMD_BARRIER | 8 bytes | Memory barrier |
| 0x0104 | VPU_CMD_METRIC_QUERY_BEGIN | 16 bytes | Start metric query |
| 0x0105 | VPU_CMD_METRIC_QUERY_END | 16 bytes | End metric query |
| 0x0202 | VPU_CMD_MEMORY_FILL | 32 bytes | Fill memory with pattern |
| 0x0302 | VPU_CMD_COPY | 24 bytes | Copy memory |
| 0x0306 | VPU_CMD_INFERENCE_EXECUTE | 32 bytes | Execute inference |

### Command Definitions

#### NOP Command

```c
struct vpu_cmd_nop {
    vpu_cmd_header header;  // type=0x0001, size=4
};
```

#### Timestamp Command

```c
struct vpu_cmd_timestamp {
    vpu_cmd_header header;      // type=0x0100, size=16
    uint32_t type;             // Timestamp type (0=raw, 1=systime, 2=delta)
    uint64_t timestamp_address;  // Address to write timestamp
};
```

#### Fence Command (Wait/Signal)

```c
struct vpu_cmd_fence {
    vpu_cmd_header header;   // type=0x0101 or 0x0102, size=24
    uint32_t reserved_0;
    uint64_t offset;          // Offset from fence_heap_base_address
    uint64_t value;          // Fence value to wait/signal
};
```

#### Barrier Command

```c
struct vpu_cmd_barrier {
    vpu_cmd_header header;   // type=0x0103, size=8
    uint32_t reserved_0;
};
```

#### Metric Query Command

```c
struct vpu_cmd_metric_query {
    vpu_cmd_header header;    // type=0x0104 or 0x0105, size=16
    uint32_t metric_group_type;  // Metric group bitmask
    uint64_t metric_data_address;  // Address to store metric data
};
```

#### Memory Fill Command

```c
struct vpu_cmd_memory_fill {
    vpu_cmd_header header;   // type=0x0202, size=32
    uint32_t reserved_0;
    uint64_t start_address;   // Address to start filling
    uint64_t size;          // Size to fill (max 16 MB)
    uint32_t fill_pattern;   // Pattern to fill
    uint32_t reserved_1;
};
```

#### Copy Command

```c
struct vpu_cmd_copy_buffer {
    vpu_cmd_header header;       // type=0x0302, size=24
    uint32_t reserved_0;
    uint64_t desc_start_offset;  // Offset in descriptor heap
    uint32_t desc_count;        // Number of descriptors
    uint32_t reserved_1;
};
```

Copy descriptors are stored in the descriptor heap:

**For VPU 37xx:**
```c
struct vpu_cmd_copy_descriptor_37xx {
    uint64_t reserved_0[2];
    uint64_t src_address;
    uint64_t dst_address;
    uint32_t size;              // Max 16 MB
    uint32_t reserved_1[7];
};  // 64 bytes
```

**For VPU 40xx+:**
```c
struct vpu_cmd_copy_descriptor_40xx {
    uint64_t reserved_0[3];
    uint32_t size;
    uint32_t reserved_1;
    uint64_t reserved_2;
    uint64_t src_address;
    uint64_t dst_address;
    uint64_t reserved_3[17];
};  // 160 bytes (but only 64 bytes used in practice)
```

#### Inference Execute Command

```c
struct vpu_cmd_inference_execute {
    vpu_cmd_header header;        // type=0x0306, size=32
    uint32_t reserved_0;
    uint64_t inference_id;
    vpu_cmd_resource_descriptor host_mapped_inference;
};

struct vpu_cmd_resource_descriptor {
    uint64_t address;
    uint32_t width;
    uint32_t reserved_0;
};
```

## Descriptor Table Entry Types

For inference execution, the descriptor heap contains entries:

| Type ID | Name           | Description |
|---------|----------------|-------------|
| 0x100 | SCRATCH        | Scratch buffer |
| 0x101 | METADATA       | Blob metadata |
| 0x102 | WEIGHTS        | Network weights |
| 0x103 | KERNEL_DATA    | Kernel data |
| 0x200 | INPUT          | Input tensor |
| 0x201 | OUTPUT         | Output tensor |
| 0x202 | PROFILING_OUTPUT | Profiling data |

## Alignment Requirements

- **Cache line alignment**: All command buffer structures must be aligned to 64 bytes
- **Descriptor alignment**: Descriptors in the descriptor heap must be 64-byte aligned
- **Fence alignment**: (37xx) 64-byte alignment, (40xx+) 8-byte alignment

## API Versioning

The command buffer header contains an `api_version` field that encodes:
- Major version (16 MSB): Breaking changes
- Minor version (16 LSB): Backward compatible changes

Current versions (from `vpu_jsm_job_cmd_api.h`):
- Major: 4
- Minor: 15

## Memory Address Spaces

The VPU uses its own virtual address space:

- **vpu_addr**: VPU virtual address (assigned by firmware)
- **host_va**: Host virtual address (CPU address)
- **mmap_offset**: Offset for mmap() to access buffer from host

Addresses in commands are **VPU virtual addresses**, not CPU addresses.

## Capturing Jobs from Kernel

Jobs are captured in `VPUDriverApi::commandQueueSubmit()`:

```cpp
int VPUDriverApi::commandQueueSubmit(drm_ivpu_cmdq_submit *arg) {
    // 1. Query buffer information
    drm_ivpu_bo_info info;
    info.handle = handle;
    doIoctl(DRM_IOCTL_IVPU_BO_INFO, &info);

    // 2. Map buffer to read contents
    void *ptr = mmap(NULL, info.size, PROT_READ | PROT_WRITE,
                    MAP_SHARED, vpuFd, info.mmap_offset);

    // 3. Read buffer data
    unsigned char* data = (unsigned char*)ptr;

    // 4. Serialize to JSON
    // ... (see vpu_driver_api.cpp)
}
```

The captured JSON structure:

```json
{
  "vpuFd": 3,
  "cmdq_id": 1,
  "buffers_ptr": "0x5968a50a0660",
  "buffer_count": 3,
  "buffers": [
    {
      "index": 0,
      "handle": 4,
      "vpu_addr": "0x100016000",
      "size": 4096,
      "mmap_offset": 4399427584,
      "flags": 2,
      "data": "hex-encoded-buffer-contents"
    }
  ],
  "commands_offset": 128,
  "preempt_buffer_index": 0
}
```

## Lifting to Protobuf

The captured JSON binaries can be lifted to structured Protobuf format using:

```bash
# Compile protobuf schema
protoc --python_out=. vpu_job.proto

# Lift JSON to protobuf
python3 lift_vpu_job.py vpu_jobs/0.json output.pb
```

The Protobuf schema (`vpu_job.proto`) defines:
- `VpuJob`: Complete job submission
- `VpuCommandBuffer`: Parsed command buffer with all commands
- `VpuCmd*`: Individual command types

## For Fuzzing

When fuzzing the VPU driver/firmware with libprotobuf-mutator:

1. **Lift** captured binaries to Protobuf
2. **Mutate** using LPM (structure-aware mutations)
3. **Lower** back to binary format
4. **Submit** to driver via ioctl

Key considerations:
- **Pointers**: VPU addresses must be re-allocated and updated
- **Alignment**: Maintain 64-byte cache line alignment
- **Checksums**: No checksums in VPU command format
- **Dependencies**: Commands may have order dependencies (fences)
- **Buffer relationships**: Commands reference data in other buffers via VPU addresses, must maintain consistency

## Descriptor Heap (Descriptor Heap) Details

The descriptor heap is a region in Buffer 0 (after commands) that contains data descriptors used by commands like COPY and INFERENCE_EXECUTE.

### Location

The descriptor heap location is determined by the command buffer header:
- Start: `descriptor_heap_base_address` (VPU absolute address)
- Alignment: 64-byte aligned
- Each entry: 64 bytes

### COPY Command Descriptors

For COPY commands, descriptors specify memory copy operations:

**VPU 37xx format (64 bytes):**
```c
struct vpu_cmd_copy_descriptor_37xx {
    uint64_t reserved_0[2];  // 16 bytes (unused)
    uint64_t src_address;      // Source VPU address
    uint64_t dst_address;      // Destination VPU address
    uint32_t size;             // Size in bytes (max 16 MB)
    uint32_t reserved_1[7];  // 28 bytes (unused)
};
```

**VPU 40xx+ format (160 bytes allocated, 64 used):**
```c
struct vpu_cmd_copy_descriptor_40xx {
    uint64_t reserved_0[3];  // 24 bytes (unused)
    uint32_t size;             // Size in bytes
    uint32_t reserved_1;       // 4 bytes (unused)
    uint64_t reserved_2;       // 8 bytes (unused)
    uint64_t src_address;      // Source VPU address
    uint64_t dst_address;      // Destination VPU address
    uint64_t reserved_3[17];  // 136 bytes (unused)
};
```

### Inference Descriptors

For INFERENCE_EXECUTE commands, the descriptor heap contains inference-related descriptors:

| Entry Type | Hex Value | Description |
|-------------|-------------|-------------|
| SCRATCH | 0x100 | Scratch buffer allocation |
| METADATA | 0x101 | Blob metadata reference |
| WEIGHTS | 0x102 | Network weights reference |
| KERNEL_DATA | 0x103 | DPU kernel code reference |
| INPUT | 0x200 | Input tensor reference |
| OUTPUT | 0x201 | Output tensor reference |
| PROFILING_OUTPUT | 0x202 | Performance profiling output |

Each descriptor entry is 64 bytes and contains VPU addresses pointing to actual data buffers.

### Example: COPY Command with Descriptor

```
Buffer 0 layout:
+-------------------+ 0x00
| Context Save Area | 64 bytes
+-------------------+ 0x40
| Fence Value       | 8 bytes
+-------------------+ 0x48
| Reserved          | 56 bytes
+-------------------+ 0x80
| Cmd Buffer Header | 64 bytes
+-------------------+ 0xC0
| Internal Fence[0] | 24 bytes
+-------------------+ 0xD8
| Internal Fence[1] | 24 bytes
+-------------------+ 0xF0
| Command List      |
|   - TIMESTAMP     | 16 bytes
|   - COPY         | 24 bytes
|   - NOP          | 24 bytes
+-------------------+ 0x140 (320)
| Descriptor Heap   |
|   [0] Copy Desc  | 64 bytes
|       - src_addr   | points to Buffer X
|       - dst_addr   | points to Buffer Y
|       - size       | N bytes
+-------------------+
```

The COPY command contains:
- `desc_start_offset`: Absolute VPU address of descriptor array (e.g., 0x100016140)
- `desc_count`: Number of descriptors (e.g., 1)

The driver converts this absolute address to a relative offset within Buffer 0 to access the descriptors.

## Buffer 1: Host Parsed Inference (HPI)

Buffer 1 contains the `VpuHostParsedInference` structure for VPU 37xx architectures. This structure holds metadata and resource requirements for the inference execution.

### VpuHostParsedInference Structure (384 bytes)

```c
struct VpuHostParsedInference {
    uint64_t reserved;                    // Offset 0: 8 bytes
    ResourceRequirements resource_requirements_;  // Offset 8: 12 bytes
    uint8_t pad_[4];                    // Offset 20: 4 bytes
    VpuPerformanceMetrics performance_metrics_; // Offset 24: 320 bytes
    VpuTaskReference<VpuMappedInference> mapped_; // Offset 344: 24 bytes
};  // Total: 384 bytes, aligned to 8 bytes
```

### ResourceRequirements Structure (12 bytes)

```c
struct ResourceRequirements {
    uint32_t nn_slice_length_;  // Network slice length (4 bytes)
    uint8_t pad_[6];           // Padding (6 bytes)
    uint8_t nn_slice_count_;   // Number of network slices (1 byte)
    uint8_t nn_barriers_;      // Number of barriers (1 byte)
};  // Total: 12 bytes
```

### VpuPerformanceMetrics Structure (320 bytes)

```c
struct VpuPerformanceMetrics {
    uint32_t freq_base;                              // Base frequency in MHz (4 bytes)
    uint32_t freq_step;                              // Frequency step in MHz (4 bytes)
    uint32_t bw_base;                                // Base bandwidth in MB/s (4 bytes)
    uint32_t bw_step;                                // Bandwidth step in MB/s (4 bytes)
    uint64_t ticks[5][5];                           // Execution time ticks table (200 bytes)
    float scalability[5][5];                          // Scalability table (100 bytes)
    float activity_factor;                               // Activity factor (4 bytes)
};  // Total: 320 bytes
```

The `ticks` and `scalability` arrays are 2D tables:
- Outer array: Different frequency values (5 entries)
- Inner array: Different bandwidth values (5 entries)

### VpuTaskReference Structure (24 bytes)

```c
template<typename T>
struct VpuTaskReference {
    uint64_t address;  // VPU address of the referenced structure
    uint32_t count;    // Number of entries
    uint32_t offset;   // Offset from address
};  // Total: 24 bytes
```

For `VpuTaskReference<VpuMappedInference>`:
- `address`: VPU address of the Mapped Inference structure
- `count`: Number of mapped inference entries (usually 1)
- `offset`: Offset to the Mapped Inference data

## Buffer 2-N: Data Buffers

Buffers 2 and beyond contain the actual data referenced by the inference:

### Common Buffer Types

| Buffer Purpose | Typical Content | Size | Description |
|----------------|------------------|-------|-------------|
| **Weights** | Network weights | Variable | Model parameters from compiled model |
| **Inputs** | Input tensors | Depends on model | Model input data (e.g., images, tensors) |
| **Outputs** | Output tensors | Depends on model | Computed inference results |
| **Scratch** | Temporary storage | Depends on model | Allocated by firmware during execution |
| **Kernel Data** | DPU kernel code | Depends on model | Executable kernel binaries |
| **Metadata** | Model metadata | Variable | Network metadata from compiled model |

### Buffer Address Resolution

The INFERENCE_EXECUTE command's `host_mapped_inference.address` field points to Buffer 1's VPU address. The contents of Buffer 1 contain a `VpuTaskReference` which points to the actual Mapped Inference structure (often in another buffer).

### Example Buffer Layout

A typical inference job might have:
- Buffer 0: Command buffer (4KB)
  - Contains INFERENCE_EXECUTE command pointing to Buffer 1
  - Contains COPY commands for data movement
  - Contains FENCE commands for synchronization
  - Contains Descriptor Heap (at offset after commands)
    - Copy descriptors (for COPY commands)
    - Inference descriptors (for INFERENCE_EXECUTE)
- Buffer 1: Host Parsed Inference (384 bytes)
  - Contains ResourceRequirements (slice count, barriers)
  - Contains PerformanceMetrics (timing tables)
  - Contains reference to Mapped Inference
- Buffer 2-N: Data buffers
  - Weights buffer (static model data)
  - Input tensor buffers (dynamic input data)
  - Output tensor buffers (results)
  - Scratch buffer (temporary workspace)
  - Kernel data (DPU executable code)

### Buffer Reference Chain

```
INFERENCE_EXECUTE Command (in Buffer 0)
    ↓
host_mapped_inference.address (VPU address)
    ↓
Buffer 1: VpuHostParsedInference (384 bytes)
    ↓
mapped_.address (VPU address of Mapped Inference)
    ↓
Buffer X: VpuMappedInference (448 bytes) or other data buffer
    - Contains DPU task references
    - Contains DMA task references
    - Contains kernel references
    - Contains workspace addresses
```

### Summary of Buffer Types

| Buffer Index | Name | Size | Purpose | Parse Status |
|--------------|------|-------|--------------|
| 0 | Command Buffer | ~4KB | ✅ Fully parsed (commands, descriptors) |
| 1 | Host Parsed Inference | 384 bytes | ✅ Fully parsed (VpuHostParsedInference) |
| 2+ | Data Buffers | Variable | ⬛ Partially parsed (buffer metadata only) |

**Data Buffer Contents (Buffer 2+):**
- **Metadata parsed**: Buffer size, VPU address, flags
- **Contents not parsed**: Actual tensor data, weights, kernels (kept as raw bytes)

**Fuzzing Implications:**
- Commands can be fully mutated (type, size, parameters, addresses)
- Descriptor heap entries can be mutated (type, addresses, sizes)
- Host Parsed Inference can be mutated (slice count, barriers, performance metrics)
- Data buffer contents can only be mutated at byte level (no structure awareness)

## Related Files

- `linux/include/uapi/drm/ivpu_accel.h`: UAPI definitions
- `firmware/include/api/vpu_jsm_job_cmd_api.h`: Job command API
- `firmware/include/api/vpu_jsm_api.h`: JSM shared API
- `firmware/include/api/vpu_nnrt_api_37xx.h`: VPU 37xx NPU runtime API
- `firmware/include/api/vpu_nnrt_api_40xx.h`: VPU 40xx NPU runtime API
- `firmware/include/api/vpu_pwrmgr_api.h`: Power manager and performance metrics API
- `third_party/npu_compiler_elf/hpi_component/include/common/vpux_hpi.hpp`: Host Parsed Inference API
- `third_party/npu_compiler_elf/loader/include/vpux_headers/metadata_primitives.hpp`: Metadata primitives
- `umd/vpu_driver/source/command/command_buffer.hpp`: Command buffer implementation
- `umd/vpu_driver/source/os_interface/vpu_driver_api.cpp`: Driver API with job capture

---

# Understanding Summary

## What We Understand (Fully Structured)

### ✅ Buffer 0: Command Buffer (100% parsed)
- Command buffer header (cmd_buffer_size, cmd_offset, api_version)
- Command list (all command types with parameters)
- Descriptor heap (64-byte aligned entries)
- Internal fences (synchronization)

### ✅ Buffer 1: Host Parsed Inference (100% parsed)
- VpuHostParsedInference structure (384 bytes)
- ResourceRequirements (slice count, barriers)
- VpuPerformanceMetrics (timing tables for power management)
- VpuTaskReference (points to Mapped Inference)

### ✅ Buffer Relationships (Understood)
- INFERENCE_EXECUTE → Buffer 1 (Host Parsed Inference)
- COPY command → Descriptor heap → Source/Destination buffers
- Command addresses are VPU virtual addresses
- Descriptor heap entries reference other buffers

## What We Don't Understand (Black Box)

### ⬛ Buffer 2-N: Data Buffers (Metadata only, content black box)

**Known (Parsed):**
- Buffer metadata (size, VPU address, flags)
- Buffer index and handle

**Unknown (Black Box):**
- **Tensor data structure**: Input/output tensors are raw byte arrays
- **Weights format**: Network weights are opaque binary blobs
- **Kernel code**: DPU executable code is opaque
- **Descriptor table entries**: The actual structure of inference descriptors in descriptor heap
- **Metadata format**: What VpuMappedInference structure contains

**Fuzzing Impact:**
- Commands: Can mutate type, size, addresses, counts (structure-aware)
- Host Parsed Inference: Can mutate slice count, barriers, metrics (structure-aware)
- Data Buffers: Can only do byte-level mutations (blind flipping)

## Future Work

To improve fuzzing coverage, the following structures need reverse engineering:

1. **VpuMappedInference Structure**: The actual mapped inference format used by firmware
2. **Descriptor Table Format**: How INPUT/OUTPUT/WEIGHTS descriptors are structured
3. **Tensor Format**: Input/output tensor layout and data types
4. **Weights Format**: Model weight encoding and organization
5. **Kernel Binary Format**: DPU executable instruction encoding
