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
2. **Buffer 1-N**: Associated data buffers (weights, activations, etc.)

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

## Related Files

- `linux/include/uapi/drm/ivpu_accel.h`: UAPI definitions
- `firmware/include/api/vpu_jsm_job_cmd_api.h`: Job command API
- `firmware/include/api/vpu_jsm_api.h`: JSM shared API
- `umd/vpu_driver/source/command/command_buffer.hpp`: Command buffer implementation
- `umd/vpu_driver/source/os_interface/vpu_driver_api.cpp`: Driver API with job capture
