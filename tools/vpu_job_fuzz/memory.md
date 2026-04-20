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

### Parsing Command Buffer (Lifting Process)

```python
def parse_command_buffer(buffer_bytes: bytes):
    """Parse command buffer from raw bytes (see lift_vpu_job.py:219-273)."""

    # 1. Parse prefix (first 128 bytes)
    context_save_area = buffer_bytes[0:64]           # 64 bytes
    fence_value = struct.unpack('<Q', buffer_bytes[64:72])[0]  # 8 bytes
    reserved = struct.unpack('<7Q', buffer_bytes[72:128])      # 56 bytes

    # 2. Parse vpu_cmd_buffer_header (offset 128, 64 bytes)
    # Note: First 40 bytes are used (4 * uint32 + 3 * uint64)
    header_fields = struct.unpack('<4I3Q', buffer_bytes[128:168])
    cmd_buffer_size = header_fields[0]
    cmd_offset = header_fields[1]
    api_version = header_fields[2]
    descriptor_heap_base_address = header_fields[4]
    submission_timestamp = header_fields[5]
    fence_heap_base_address = header_fields[6]

    # 3. Parse internal fences (2 fences, starting at offset 192)
    internal_fence_offset = 192  # 128 + 64 (header size)
    for i in range(2):
        fence_offset = internal_fence_offset + i * 24
        fence_type = struct.unpack('<H', buffer_bytes[fence_offset:fence_offset + 2])[0]
        fence_size = struct.unpack('<H', buffer_bytes[fence_offset + 2:fence_offset + 4])[0]
        fence_offset_value = struct.unpack('<Q', buffer_bytes[fence_offset + 8:fence_offset + 16])[0]
        fence_value = struct.unpack('<Q', buffer_bytes[fence_offset + 16:fence_offset + 24])[0]

    # 4. Parse command list
    cmd_list_offset = 128 + cmd_offset
    current_offset = cmd_list_offset
    end_offset = cmd_list_offset + (cmd_buffer_size - cmd_offset)

    while current_offset < end_offset:
        # Read command header (4 bytes: uint16 + uint16)
        cmd_type, cmd_size = struct.unpack('<HH', buffer_bytes[current_offset:current_offset + 4])

        # Parse based on command type
        if cmd_type == 0x0001:  # NOP
            pass  # No additional fields
        elif cmd_type == 0x0100:  # TIMESTAMP
            ts_type = struct.unpack('<I', buffer_bytes[current_offset + 4:current_offset + 8])[0]
            ts_address = struct.unpack('<Q', buffer_bytes[current_offset + 8:current_offset + 16])[0]
        elif cmd_type == 0x0101 or cmd_type == 0x0102:  # FENCE_WAIT/FENCE_SIGNAL
            fence_offset_value = struct.unpack('<Q', buffer_bytes[current_offset + 8:current_offset + 16])[0]
            fence_value = struct.unpack('<Q', buffer_bytes[current_offset + 16:current_offset + 24])[0]
        elif cmd_type == 0x0306:  # INFERENCE_EXECUTE
            inference_id = struct.unpack('<Q', buffer_bytes[current_offset + 8:current_offset + 16])[0]
            hpi_address = struct.unpack('<Q', buffer_bytes[current_offset + 16:current_offset + 24])[0]

        current_offset += cmd_size
```

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

### Address Space Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Host (CPU) Memory Space                                      │
│                                                               │
│  host_va (returned by mmap)                                  │
│     │                                                         │
│     │  0x7f1234000000 ─────────────────────┐                │
│     │                                       │                │
│     │  Buffer contents (readable by CPU)    │                │
│     │                                       │                │
│     └───────────────────────────────────────┘                │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ VPU (Firmware) Memory Space                                  │
│                                                               │
│  vpu_addr (assigned by firmware)                             │
│     │                                                         │
│     │  0x100016000 ──────────────────────┐                  │
│     │                                     │                  │
│     │  Buffer contents (readable by VPU) │                  │
│     │                                     │                  │
│     └─────────────────────────────────────┘                  │
│                                                               │
│  Commands reference buffers using vpu_addr:                  │
│    - descriptor_heap_base_address                            │
│    - COPY descriptor src_address/dst_address                  │
│    - INFERENCE_EXECUTE host_mapped_inference.address          │
│                                                               │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ Kernel Buffer Object (GEM)                                   │
│                                                               │
│  struct drm_ivpu_bo_info {                                   │
│      handle: 4,                                              │
│      vpu_addr: 0x100016000,     // VPU virtual address      │
│      size: 4096,                                            │
│      mmap_offset: 4399427584,   // Offset for mmap()        │
│      flags: 2                                               │
│  };                                                          │
│                                                               │
└─────────────────────────────────────────────────────────────┘

Mapping:
  mmap(NULL, info.size, PROT_READ | PROT_WRITE,
       MAP_SHARED, vpuFd, info.mmap_offset)
       ↓
  Returns host_va (0x7f1234000000)

  host_va and vpu_addr refer to the SAME physical memory,
  but in different virtual address spaces!
```

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

**NOTE: Hardware is 40xx series - all structures below are for 40xx only.**

## Lifting to Protobuf

The captured JSON binaries can be lifted to structured Protobuf format:

```bash
# Compile protobuf schema
protoc --python_out=. vpu_job.proto

# Lift JSON to protobuf
python3 lift_vpu_job.py vpu_jobs/0.json output.pb
```

### Lifting Process (`lift_vpu_job.py`)

1. **Load JSON**: Parse captured job JSON file
2. **Parse Buffer 1**: Attempt to parse as VpuHostParsedInference (384 bytes)
   - ResourceRequirements (12 bytes)
   - VpuPerformanceMetrics (320 bytes)
   - VpuTaskReference (24 bytes)
3. **Parse Buffer 0**: Parse command buffer structure
   - Context save area (64 bytes)
   - Fence value (8 bytes)
   - Reserved (56 bytes)
   - VpuCmdBufferHeader (64 bytes)
   - Internal fences (48 bytes)
   - Command list (variable)
4. **Parse Commands**: Iterate through command list and parse each command type
   - NOP, TIMESTAMP, FENCE, BARRIER, METRIC_QUERY
   - MEMORY_FILL, COPY, INFERENCE_EXECUTE
5. **Save as Protobuf**: Serialize to `.pb` file

### Binary to Proto Conversion Notes

**Command Header Size Mismatch:**
- Binary format: `uint16_t type + uint16_t size` = 4 bytes
- Proto format: `uint32 type + uint32 size` = 8 bytes
- **Lifting**: Read 2 bytes, store as 4 bytes
- **Lowering**: Write as 2 bytes using only low 16 bits (`value & 0xFFFF`)

**Command Type Encoding:**

| Binary Type | Proto Enum | Size (bytes) |
|-------------|------------|--------------|
| 0x0001 | NOP | 4 |
| 0x0100 | TIMESTAMP | 16 |
| 0x0101 | FENCE_WAIT | 24 |
| 0x0102 | FENCE_SIGNAL | 24 |
| 0x0103 | BARRIER | 8 |
| 0x0104 | METRIC_QUERY_BEGIN | 16 |
| 0x0105 | METRIC_QUERY_END | 16 |
| 0x0202 | MEMORY_FILL | 32 |
| 0x0302 | COPY | 24 |
| 0x0306 | INFERENCE_EXECUTE | 32 |

## Lowering to Binary

The Protobuf can be lowered back to binary format:

```bash
# Lower protobuf to JSON (for testing)
python3 lower_vpu_job.py output.pb output_lowered.json
```

### Lowering Process (`lower_vpu_job.py`)

1. **Load Protobuf**: Parse `.pb` file
2. **Lower Commands**: Convert each command back to binary
   - Pack struct fields with `<` (little-endian)
   - Truncate `type` and `size` to 16 bits: `value & 0xFFFF`
3. **Lower Host Parsed Inference**: Convert HPI structure back to bytes
   - Pack ResourceRequirements (12 bytes)
   - Pack VpuPerformanceMetrics (320 bytes)
   - Pack VpuTaskReference (24 bytes)
4. **Lower Command Buffer**: Rebuild command buffer binary
   - Prefix (128 bytes)
   - Header (64 bytes)
   - Internal fences (48 bytes)
   - Commands (variable)
5. **Output**: Save as JSON with hex-encoded `data` field

### Struct Packing Format

All structs use little-endian byte order (`<` prefix):

```python
# Example: VpuCmdNop (4 bytes)
struct.pack('<HH', nop.header.type & 0xFFFF, nop.header.size & 0xFFFF)

# Example: VpuCmdTimestamp (16 bytes)
struct.pack('<HH IQ',
            ts.header.type & 0xFFFF,
            ts.header.size & 0xFFFF,
            ts.type,
            ts.timestamp_address)
```

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

Buffer 1 contains the `VpuHostParsedInference` structure for VPU 40xx architectures. This structure holds metadata and resource requirements for the inference execution.

### VpuHostParsedInference Structure (384 bytes)

```c
struct VPU_ALIGNED_STRUCT(64) VpuHostParsedInference {
    uint64_t reserved_;                                   // Offset 0: 8 bytes
    VpuResourceRequirements resource_requirements_;            // Offset 8: 12 bytes

    /**
     * @brief Determines whether access to VpuManagedMappedInference is direct or indirect.
     */
    enum VpuMmiAccessMode : uint8_t {
        INDIRECT = 0,    /**< The managed inference is accessed indirectly */
        DIRECT,          /**< The managed inference is accessed directly */
        UNKNOWN = 255
    };

    VpuMmiAccessMode mmi_access_;                       // Offset 20: 1 byte
    uint8_t pad_[3];                                    // Offset 21: 3 bytes
    struct VpuPerformanceMetrics performance_metrics_;      // Offset 24: 320 bytes
    union VPU_ALIGNED_STRUCT(8) {
        VpuTaskReference<VpuMappedInference> mapped_;
        VpuTaskReference<VpuManagedMappedInference> managed_inference_;
    };
};  // Total: 384 bytes, aligned to 64 bytes
```

### ResourceRequirements Structure (12 bytes)

```c
struct VPU_ALIGNED_STRUCT(4) VpuResourceRequirements {
    uint32_t nn_slice_length_;  // Network slice length (4 bytes)
    uint8_t deprecated_[6]; // Deprecated member, do not reuse until next API major version update
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

For `VpuTaskReference<VpuManagedMappedInference>` (40xx DIRECT mode):
- `address`: VPU address of the Managed Mapped Inference structure
- `count`: Number of entries
- `offset`: Offset to the data

## Buffer 2-N: Data Buffers and VpuMappedInference

Buffers 2 and beyond contain the actual data referenced by the inference. VpuMappedInference is also stored in one of these buffers when used.

### Common Buffer Types

| Buffer Purpose | Typical Content | Size | Description |
|----------------|------------------|-------|-------------|
| **Weights** | Network weights | Variable | Model parameters from compiled model |
| **Inputs** | Input tensors | Depends on model | Model input data (e.g., images, tensors) |
| **Outputs** | Output tensors | Depends on model | Computed inference results |
| **Scratch** | Temporary storage | Depends on model | Allocated by firmware during execution |
| **Kernel Data** | DPU kernel code | Depends on model | Executable kernel binaries |
| **Metadata** | Model metadata | Variable | Network metadata from compiled model |
| **VpuMappedInference** | Task structure | 1728 bytes (40xx) | Inference task definitions |

### VpuMappedInference Structure (40xx: 1728 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:351`.

```c
struct VPU_ALIGNED_STRUCT(32) VpuMappedInference {
    uint32_t vpu_nnrt_api_ver;                         // 4 bytes
    uint8_t pad0_[4];                                    // 4 bytes
    uint64_t reserved0_;                                  // 8 bytes
    uint64_t logaddr_dma_hwp_;                            // 8 bytes

    VpuTaskCounts task_storage_counts_;                   // 36 bytes
    uint32_t task_storage_size_;                           // 4 bytes

    // Task arrays (VPU_MAX_TILES = 6 elements each)
    VpuTaskReference<VpuDMATask> dma_tasks_ddr_[VPU_MAX_TILES];  // 6 x 24 = 144 bytes
    VpuTaskReference<VpuDMATask> dma_tasks_cmx_[VPU_MAX_TILES];  // 6 x 24 = 144 bytes
    VpuTaskReference<VpuDPUInvariant> invariants[VPU_MAX_TILES];     // 6 x 24 = 144 bytes
    VpuTaskReference<VpuDPUVariant> variants[VPU_MAX_TILES];         // 6 x 24 = 144 bytes
    VpuTaskReference<VpuActKernelRange> act_kernel_ranges[VPU_MAX_TILES];  // 6 x 24 = 144 bytes
    VpuTaskReference<VpuActKernelInvocation> act_kernel_invocations[VPU_MAX_TILES]; // 6 x 24 = 144 bytes
    VpuTaskReference<VpuMediaTask> media_tasks;               // 24 bytes
    VpuTaskReference<VpuBarrierCountConfig> barrier_configs;    // 24 bytes

    VpuNNShaveRuntimeConfigs shv_rt_configs;            // 52 bytes
    uint64_t hwp_workpoint_cfg_addr;                        // 8 bytes
    VpuTaskReference<VpuManagedMappedInference> managed_inference; // 24 bytes
};  // Total: 1728 bytes, aligned to 32 bytes
```

### Key Fields in VpuMappedInference

- **vpu_nnrt_api_ver**: NPU runtime API version (should be 0x00040000 for 40xx)
- **logaddr_dma_hwp_**: DMA hardware preloader address
- **task_storage_counts_**: Task counts per tile type
  - dma_ddr_count: DDR DMA tasks
  - dma_cmx_count: CMX DMA tasks
  - dpu_invariant_count: DPU invariant tasks
  - dpu_variant_count: DPU variant tasks
  - act_range_count: Activation kernel ranges
  - act_invo_count: Activation kernel invocations
  - media_count: Media tasks
- **Task arrays**: VPU_MAX_TILES (6) elements each
  - dma_tasks_ddr_[]: DDR DMA task arrays
  - dma_tasks_cmx_[]: CMX DMA task arrays
  - invariants[]: DPU invariant arrays
  - variants[]: DPU variant arrays
  - act_kernel_ranges[]: Kernel range arrays
  - act_kernel_invocations[]: Kernel invocation arrays
- **shv_rt_configs**: Shave runtime configuration
- **hwp_workpoint_cfg_addr**: Hardware preloader workpoint config address
- **managed_inference**: Reference to managed inference (for workload management)

### Buffer Address Resolution

The INFERENCE_EXECUTE command's `host_mapped_inference.address` field points to Buffer 1's VPU address. The contents of Buffer 1 contain:
- **If mmi_access_ = INDIRECT**: `mapped_` points to VpuMappedInference (in Buffer 2-N)
- **If mmi_access_ = DIRECT**: `managed_inference_` points directly to VpuManagedMappedInference (in Buffer 2-N)

### Example Buffer Layout (40xx)

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
  - Contains mmi_access_ mode
  - Contains reference to VpuMappedInference (INDIRECT mode)
  - Contains reference to VpuManagedMappedInference (DIRECT mode)
- Buffer 2: VpuMappedInference (1728 bytes)
  - Contains task counts
  - Contains task arrays (6 tiles)
  - Contains shv_rt_configs
- Buffer 3-N: Data buffers
  - Weights buffer (static model data)
  - Input tensor buffers (dynamic input data)
  - Output tensor buffers (results)
  - Scratch buffer (temporary workspace)
  - Kernel data (DPU executable code)
  - DMA task arrays (for each tile)
  - DPU invariants/variants (for each tile)
  - Activation kernels (for each tile)

### Buffer Reference Chain (40xx)

```
INFERENCE_EXECUTE Command (in Buffer 0)
    ↓
host_mapped_inference.address (VPU address of Buffer 1)
    ↓
Buffer 1: VpuHostParsedInference (384 bytes)
    ↓
If INDIRECT mode:
    ↓
    mapped_.address (VPU address of VpuMappedInference)
    ↓
    Buffer X: VpuMappedInference (1728 bytes)
If DIRECT mode:
    ↓
    managed_inference_.address (VPU address of VpuManagedMappedInference)
    ↓
    Buffer X: VpuManagedMappedInference
```

### Summary of Buffer Types

| Buffer Index | Name | Size | Purpose | Parse Status |
|--------------|------|-------|--------------|
| 0 | Command Buffer | ~4KB | ✅ Fully parsed (commands, descriptors) |
| 1 | Host Parsed Inference | 384 bytes | ✅ Fully parsed (VpuHostParsedInference) |
| 2+ | Data Buffers | Variable | ⬛ Partially parsed |
| 2+ (if used) | VpuMappedInference | 1728 bytes | ⬛ Metadata only (structure defined) |

**Data Buffer Contents (Buffer 2+):**
- **Metadata parsed**: Buffer size, VPU address, flags
- **Contents not parsed**: Actual tensor data, weights, kernels (kept as raw bytes)
- **VpuMappedInference**: Structure defined but parsing needs following VpuTaskReference arrays

**Fuzzing Implications:**
- Commands can be fully mutated (type, size, parameters, addresses)
- Descriptor heap entries can be mutated (type, addresses, sizes)
- Host Parsed Inference can be mutated (slice count, barriers, performance metrics, mmi_access mode)
- VpuMappedInference: Structure defined but task arrays not parsed (needs VpuTaskReference dereferencing)
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

## Job Capture Process

### Data Capture Location

Jobs are captured in `VPUDriverApi::commandQueueSubmit()` (`umd/vpu_driver/source/os_interface/vpu_driver_api.cpp:218-290`).

### Capture Flow

```cpp
int VPUDriverApi::commandQueueSubmit(drm_ivpu_cmdq_submit *arg) {
    // 1. Iterate through buffer handles
    uint32_t count = arg->buffer_count;
    uint32_t *buffers = (uint32_t*)arg->buffers_ptr;

    for (uint32_t i = 0; i < count; i++) {
        uint32_t handle = buffers[i];

        // 2. Query buffer metadata via ioctl
        drm_ivpu_bo_info info;
        info.handle = handle;
        doIoctl(DRM_IOCTL_IVPU_BO_INFO, &info);

        // 3. Map buffer to user space
        void *ptr = osInfc.osiMmap(nullptr, info.size, PROT_READ | PROT_WRITE,
                                   MAP_SHARED, vpuFd, info.mmap_offset);

        // 4. Read buffer contents byte-by-byte
        unsigned char* data = static_cast<unsigned char*>(ptr);

        // 5. Encode as hex string
        for (uint64_t j = 0; j < info.size; j++) {
            json << std::hex << std::setw(2) << std::setfill('0')
                 << static_cast<int>(data[j]);
        }

        // 6. Unmap
        osInfc.osiMunmap(ptr, info.size);
    }

    // 7. Save to ./vpu_jobs/{counter}.json
    job_counter++;
}
```

### Captured JSON Structure

```json
{
  "vpuFd": 3,                           // VPU device file descriptor
  "cmdq_id": 1,                         // Command queue ID
  "buffers_ptr": "0x5968a50a0660",      // Pointer to handle array (user space)
  "buffer_count": 3,                    // Number of buffers
  "buffers": [
    {
      "index": 0,                       // Buffer index in array
      "handle": 4,                      // GEM buffer handle
      "vpu_addr": "0x100016000",        // VPU virtual address
      "size": 4096,                     // Buffer size in bytes
      "mmap_offset": 4399427584,        // Offset for mmap() system call
      "flags": 2,                       // Buffer flags (cacheable, etc.)
      "data": "a1b2c3d4..."            // Hex-encoded buffer contents
    }
  ],
  "commands_offset": 128,               // Offset to first command in buffer 0
  "preempt_buffer_index": 0             // Index of preempt buffer
}
```

### drm_ivpu_bo_info Structure

```c
struct drm_ivpu_bo_info {
    __u32 handle;        // GEM buffer handle (used to identify buffer)
    __u64 vpu_addr;      // VPU virtual address (assigned by firmware)
    __u64 size;          // Buffer size in bytes
    __u64 mmap_offset;   // Offset for mmap() to access buffer
    __u32 flags;         // Buffer flags (cacheable, etc.)
};
```

### Memory Mapping Details

Buffers are accessed via `mmap()`:

```c
void *ptr = mmap(NULL, info.size, PROT_READ | PROT_WRITE,
                 MAP_SHARED, vpuFd, info.mmap_offset);
```

- `vpuFd`: Device file descriptor (e.g., /dev/dri/cardX)
- `mmap_offset`: Offset returned by `DRM_IOCTL_IVPU_BO_INFO`
- `info.size`: Buffer size

**Important:**
- `vpu_addr` is the VPU virtual address (used by firmware)
- `mmap_offset` is used by host to map the buffer
- These are different address spaces!

---

# Understanding Summary

## What We Understand (Fully Structured)

### ✅ Buffer 0: Command Buffer (100% parsed)
- Command buffer header (cmd_buffer_size, cmd_offset, api_version)
- Command list (all command types with parameters)
- Descriptor heap (64-byte aligned entries)
- Internal fences (synchronization)

### ✅ Buffer 1: Host Parsed Inference (100% parsed)
- **37xx version**: VpuHostParsedInference structure (384 bytes, aligned to 8 bytes)
  - Reserved (8 bytes)
  - VpuResourceRequirements (12 bytes): nn_slice_length, nn_slice_count, nn_barriers
  - Padding (4 bytes)
  - VpuPerformanceMetrics (320 bytes): FULLY PARSED
    - freq_base, freq_step (base frequency in MHz, frequency step in MHz)
    - bw_base, bw_step (base bandwidth in MB/s, bandwidth step in MB/s)
    - ticks table [5][5] = 25 uint64 values (200 bytes)
    - scalability table [5][5] = 25 float values (100 bytes)
    - activity_factor (4 bytes, float)
  - VpuTaskReference<VpuMappedInference> (24 bytes)

- **40xx version**: VpuHostParsedInference structure (384 bytes, aligned to 64 bytes)
  - Reserved (8 bytes)
  - VpuResourceRequirements (12 bytes)
  - VpuMmiAccessMode (1 byte): INDIRECT (0), DIRECT (1), UNKNOWN (255)
  - Padding (3 bytes)
  - VpuPerformanceMetrics (320 bytes): FULLY PARSED (same as 37xx)
  - Union:
    - VpuTaskReference<VpuMappedInference> (24 bytes) when INDIRECT mode
    - VpuTaskReference<VpuManagedMappedInference> (24 bytes) when DIRECT mode
    - managed_inference_ field (in VpuHostParsedInference union)

### ✅ Buffer Relationships (Understood)
- **INFERENCE_EXECUTE → Buffer 1** (Host Parsed Inference)
  - `host_mapped_inference.address` points to VPU address of HPI (Buffer 1)
  - When HPI's `mapped_.address = 0`, firmware uses HPI directly (common in captured jobs)
  - When HPI's `mapped_.address != 0`, firmware dereferences to VpuMappedInference (rare in captured jobs)
- **COPY command → Descriptor heap → Source/Destination buffers**
  - `desc_start_offset`: Absolute VPU address of descriptor array in descriptor heap
  - `desc_count`: Number of descriptors
  - Each descriptor: 64 bytes, contains src/dst VPU addresses and size
- **Command addresses are VPU virtual addresses**, not CPU addresses

## What We Don't Understand (Black Box)

### ⬛ Descriptor Heap Parsing (Partially implemented)
**Known (Parsed):**
- COPY descriptor structures for 37xx and 40xx
  - src_address (8 bytes), dst_address (8 bytes), size (4 bytes)
  - Reserved fields (rest of 64 bytes)

**Unknown (Black Box):**
- **Inference descriptors in descriptor heap**: When INFERENCE_EXECUTE is used, descriptor heap may contain inference-related descriptors (INPUT, OUTPUT, WEIGHTS, KERNEL_DATA, etc.)
- **Exact descriptor format for different types**: How SCRATCH, METADATA, WEIGHTS, KERNEL_DATA, INPUT, OUTPUT descriptors are structured

### ⬛ VpuMappedInference (Structurally known, rarely used in captured data)
**Known (Parsed - from firmware headers):**
- Full structure defined in protobuf for both 37xx (448 bytes) and 40xx (1728 bytes)
- VpuTaskCounts: dma_count, dpu_invariant_count, dpu_variant_count, act_range_count, act_invo_count
- VpuTaskReference arrays: dma_tasks, invariants, variants, act_kernel_ranges, act_kernel_invocations
- VpuNNShaveRuntimeConfigs: 52 bytes

**Unknown (Black Box):**
- **Most captured jobs have `mapped_.address = 0`**: These jobs don't use VpuMappedInference
- **Few jobs have valid VpuMappedInference data**: When present, can parse structure, but:
  - Task arrays (DMA, DPU invariants, DPU variants, etc.) contain VPU addresses
  - Need to parse VpuDPUInvariant (304 bytes), VpuDPUVariant (64 bytes), VpuActKernelRange (40 bytes), etc.
  - These structures are defined in firmware headers but not yet implemented in lifter

### ⬛ Data Buffers 2-N (Metadata only, content black box)

**Known (Parsed):**
- Buffer metadata (size, VPU address, flags)
- Buffer index and handle

**Unknown (Black Box):**
- **Tensor data structure**: Input/output tensors are raw byte arrays
- **Weights format**: Network weights are opaque binary blobs
- **Kernel code**: DPU executable code is opaque

**Fuzzing Impact:**
- Commands: Can mutate type, size, addresses, counts (structure-aware) ✅
- Host Parsed Inference: Can mutate slice count, barriers, metrics (structure-aware) ✅
- VpuMappedInference: Structure defined but rarely present in captured data ⚠️
- Data Buffers: Can only do byte-level mutations (blind flipping) ❌
- Descriptor heap: COPY descriptors can be parsed, inference descriptors not yet ⚠️

## Future Work

To improve fuzzing coverage, the following structures need reverse engineering:

1. **Inference Descriptor Format**: How INPUT/OUTPUT/WEIGHTS descriptors in descriptor heap are structured
2. **VpuTask Structures**: Implement parsing for:
   - VpuDPUInvariant (304 bytes)
   - VpuDPUVariant (64 bytes)
   - VpuActKernelRange (40 bytes)
   - VpuActKernelInvocation (64 bytes for 37xx, 96 bytes for 40xx)
   - VpuDMATask (128 bytes for 37xx, 224 bytes for 40xx)
3. **Tensor Format**: Input/output tensor layout and data types
4. **Weights Format**: Model weight encoding and organization
5. **Kernel Binary Format**: DPU executable instruction encoding

## Summary: Current Parsing Status

| Component | Parse Status | Coverage |
|-----------|---------------|-----------|
| Command buffer header | ✅ Full | 100% |
| All command types (NOP, COPY, INFERENCE_EXECUTE, etc.) | ✅ Full | 100% |
| COPY descriptors (40xx) | ✅ Full | 100% |
| Internal fences | ✅ Full | 100% |
| Host Parsed Inference (40xx) | ✅ Full | 100% |
| VpuPerformanceMetrics (ticks/scalability tables) | ✅ Full | 100% |
| VpuMappedInference structure (40xx) | ✅ Defined | Rarely used |
| VpuTask arrays (DMA, DPU, ActKernel) | ⬛ Defined in headers | Not implemented |
| Inference descriptors in descriptor heap | ⬛ Partial | Copy only |
| Data buffers (weights, inputs, outputs) | ❌ Metadata only | 0% |

**Hardware:** VPU 40xx series only (37xx structures removed from documentation)

# VPU Fuzzing Pipeline Overview - Syzkaller Approach

## VPU Fuzzing Pipeline Overview - Syzkaller Approach

### Why Syzkaller for VPU?

VPU fuzzing is ideal for syzkaller due to:
- Explicit command types (similar to CPU instructions)
- Clear state machine (barrier, fence synchronization)
- Independent address space (VPU virtual addresses)
- Strict alignment requirements

### Fuzzing Pipeline Comparison

| Aspect | Protobuf + libpb-mutator | Syzkaller |
|---------|---------------------------|------------|
| **State tracking** | ❌ No state machine | ✅ Full symbolic execution model |
| **Address management** | ❌ Manual VPU address remapping | ✅ Automatic symbolic address resolution |
| **Constraint checking** | ❌ No built-in validation | ✅ Built-in alignment/size constraints |
| **Coverage analysis** | ❌ Separate tool required | ✅ Built-in coverage statistics |
| **Fence semantics** | ❌ Blind mutation | ✅ Symbolic fence state modeling |
| **Dependency tracking** | ❌ Complex to implement | ✅ Automatic constraint solving |
| **State exploration** | ❌ Linear mutations only | ✅ Symbolic execution + concolic |

### Current Status

- ✅ Syzkaller spec file created (vpu.job.spec)
- ✅ Simple C++ fuzzer target created (vpu_fuzz.c)
- ✅ Basic state machine implemented
- ✅ Buffer management structure defined
- ✅ Command execution simulation
- ✅ Documented in README_syzkaller.md

### Next Steps

1. Compile syzkaller spec
2. Test basic execution model
3. Add descriptor heap parsing
4. Implement full DRM ioctl integration
5. Add coverage-driven mutation strategies

## Captured Job Analysis

Based on analysis of `vpu_jobs/` directory (260+ jobs) for 40xx hardware:

**Job Types Distribution:**
- COPY-only jobs: ~170 (65%)
- INFERENCE jobs: ~60 (23%)
- Other jobs (NOP, TIMESTAMP, etc.): ~31 (12%)

**Key Findings:**
1. **Most jobs use `mapped_.address = 0`**: These jobs use Host Parsed Inference directly without VpuMappedInference
2. **Few jobs have valid VpuMappedInference**: When present, often contains garbage data (likely from uninitialized buffers)
3. **Jobs with both COPY and INFERENCE**: Some jobs (e.g., job 224) have 25+ buffers, using COPY for data movement and INFERENCE_EXECUTE for execution
4. **API versions**: All captured jobs have api_version = 0x00000000 in command buffer header

**Buffer Size Patterns:**
- Command buffers: Usually 4KB (4096 bytes)
- Host Parsed Inference: Usually 4KB (384 bytes + padding to 64-byte alignment)
- Data buffers: Vary widely (4KB to 64MB+)
  - Weights: Large buffers (MB range)
  - Inputs/Outputs: Smaller buffers (KB range)

**Command Patterns:**
- COPY commands: 582 occurrences (most common after NOP)
- NOP commands: 254 occurrences
- TIMESTAMP commands: 161 occurrences
- FENCE commands: 47 occurrences (WAIT + SIGNAL)
- INFERENCE_EXECUTE: 60 occurrences

**40xx-Specific Observations:**
- Most captured jobs are for 40xx architecture
- VpuMappedInference size is 1728 bytes (vs 448 bytes for 37xx)
- Task arrays in VpuMappedInference have VPU_MAX_TILES (6) elements
- Separate DDR and CMX DMA task arrays
- Direct/Indirect access mode in Host Parsed Inference

**Implications for Fuzzing:**
- Can focus on COPY and INFERENCE_EXECUTE commands (most critical)
- VpuMappedInference (40xx) structure is defined in protobuf
- Host Parsed Inference (40xx) is fully parsed with mmi_access_ mode
- PerformanceMetrics (ticks/scalability tables) are present and structure-aware

## Fuzzing Pipeline Overview

### Seed Preparation Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Application submits inference job                             │
│    VPUDriverApi::commandQueueSubmit()                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. Capture raw job data (kernel space)                          │
│    - Query buffer metadata via DRM_IOCTL_IVPU_BO_INFO           │
│    - mmap each buffer and read contents                         │
│    - Encode as hex string in JSON format                        │
│    - Save to ./vpu_jobs/{counter}.json                          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. Lift to structured Protobuf (offline)                         │
│    python3 lift_vpu_job.py vpu_jobs/0.json 0.pb                 │
│    - Parse command buffer structure                             │
│    - Parse all commands (NOP, COPY, INFERENCE_EXECUTE, etc.)   │
│    - Parse Host Parsed Inference (Buffer 1)                     │
│    - Store in structure-aware format                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. Mutate with libprotobuf-mutator (fuzzer)                     │
│    - Structure-aware mutations                                  │
│    - Flip command types                                         │
│    - Mutate addresses, sizes, parameters                        │
│    - Add/remove commands                                        │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. Lower to binary format (fuzzer)                             │
│    - Convert protobuf back to binary                            │
│    - Pack structs with proper byte ordering                     │
│    - Handle uint16 -> uint32 truncation                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Submit to driver (fuzzer)                                    │
│    - Allocate new buffers via DRM_IOCTL_IVPU_BO_CREATE         │
│    - Write mutated data to buffers                              │
│    - Build drm_ivpu_cmdq_submit structure                      │
│    - Call DRM_IOCTL_IVPU_CMDQ_SUBMIT                            │
└─────────────────────────────────────────────────────────────────┘
```

### Tool Chain

| Tool | Purpose | Location |
|------|---------|----------|
| `vpu_driver_api.cpp` | Capture raw jobs from kernel | `umd/vpu_driver/source/os_interface/` |
| `lift_vpu_job.py` | JSON → Protobuf (structure-aware) | `tools/vpu_job_fuzz/` |
| `lower_vpu_job.py` | Protobuf → JSON/Binary | `tools/vpu_job_fuzz/` |
| `vpu_job.proto` | Protobuf schema | `tools/vpu_job_fuzz/` |
| `libprotobuf-mutator` | Structure-aware fuzzing | External |

### Address Mapping for Fuzzing

When submitting mutated jobs, addresses must be remapped:

```
Original captured job:
  Buffer 0: vpu_addr = 0x100016000
  Buffer 1: vpu_addr = 0x100017000
  Buffer 2: vpu_addr = 0x100018000

Mutated job submission:
  1. Allocate new buffers: DRM_IOCTL_IVPU_BO_CREATE
      → Returns new VPU addresses (e.g., 0x200016000, 0x200017000, ...)
  2. Update all address references:
      - Command buffer header addresses
      - COPY command descriptor addresses
      - INFERENCE_EXECUTE host_mapped_inference.address
      - Descriptor heap entries
  3. Submit mutated buffers with updated addresses
```

## Fuzzing Implementation Details

### Mutating Jobs with libprotobuf-mutator

When using libprotobuf-mutator to fuzz VPU jobs, the mutator will:

1. **Command mutations**:
   - Change command type (e.g., NOP → COPY, TIMESTAMP → INFERENCE_EXECUTE)
   - Modify command size (but must respect minimum sizes)
   - Mutate addresses (e.g., COPY descriptor addresses, INFERENCE_EXECUTE addresses)
   - Change counts (e.g., COPY `desc_count`)
   - Add/remove commands from the command list

2. **Structure-aware mutations**:
   - Command headers: `type` (2 bytes), `size` (2 bytes)
   - Addresses: 8-byte VPU virtual addresses
   - Flags and parameters: various 4-byte fields
   - Array elements: can add/remove entries

3. **Address dependency handling**:
   - After mutation, all VPU addresses must be consistent
   - New buffers allocated → new VPU addresses assigned
   - Update command buffer header: `descriptor_heap_base_address`, `fence_heap_base_address`
   - Update COPY command: `desc_start_offset` (absolute VPU address of descriptor heap)
   - Update INFERENCE_EXECUTE: `host_mapped_inference.address`
   - Update descriptor entries: `src_address`, `dst_address` for COPY descriptors

### Fuzzer Target Implementation

```c
// Example fuzzer target for VPU job submission
extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // 1. Parse protobuf from fuzz input
    vpu_job::VpuJob job;
    if (!job.ParseFromArray(data, size)) {
        return 0;
    }

    // 2. Lower protobuf to binary
    VpuJobLowerer lowerer;
    auto binary_job = lowerer.lower_job(job);

    // 3. Allocate new buffers
    std::vector<uint32_t> buffer_handles;
    std::vector<uint64_t> vpu_addrs;
    for (const auto& buffer : job.buffers()) {
        uint32_t handle;
        uint64_t vpu_addr;
        create_buffer(buffer.size(), buffer.flags(), handle, vpu_addr);
        buffer_handles.push_back(handle);
        vpu_addrs.push_back(vpu_addr);
    }

    // 4. Update addresses in binary data
    // Replace original addresses with new addresses
    update_addresses(binary_job, vpu_addrs);

    // 5. Write data to buffers
    for (size_t i = 0; i < binary_job.size(); i++) {
        void *ptr = mmap(NULL, job.buffers(i).size(),
                        PROT_READ | PROT_WRITE, MAP_SHARED,
                        vpuFd, get_mmap_offset(buffer_handles[i]));
        memcpy(ptr, binary_job[i].data(), binary_job[i].size());
        munmap(ptr, job.buffers(i).size());
    }

    // 6. Submit job
    drm_ivpu_cmdq_submit submit = {};
    submit.cmdq_id = job.cmdq_id();
    submit.buffer_count = buffer_handles.size();
    submit.buffers_ptr = (uint64_t)buffer_handles.data();
    submit.commands_offset = job.commands_offset();
    submit.preempt_buffer_index = job.preempt_buffer_index();

    ioctl(vpuFd, DRM_IOCTL_IVPU_CMDQ_SUBMIT, &submit);

    // 7. Cleanup
    for (auto handle : buffer_handles) {
        close_buffer(handle);
    }

    return 0;
}
```

### Key Challenges for Fuzzing

1. **Address remapping**: All VPU addresses must be updated to reflect new buffer allocations
2. **Alignment requirements**: 64-byte cache line alignment must be maintained
3. **Size constraints**: Command sizes must be valid (min size, max 16 MB for COPY)
4. **Buffer dependencies**: Commands reference data in other buffers; these must remain consistent
5. **Fence synchronization**: FENCE_WAIT/FENCE_SIGNAL commands depend on fence values; random mutations may break synchronization
6. **No checksums**: VPU command format does not include checksums, making fuzzing easier

## Additional Structures Available for Parsing

The following structures are defined in firmware headers and can be added to the fuzzer for 40xx series:

### VpuDPUInvariant (40xx: 224 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:245`.

```c
struct VPU_ALIGNED_STRUCT(32) VpuDPUInvariant {
    VpuDPUInvariantRegisters registers_;    // DPU register configuration
    VpuTaskBarrierDependency barriers_;     // Barrier dependencies (40 bytes)
    VpuTaskSchedulingBarrierConfig barriers_sched_; // Scheduling barriers
    uint8_t deprecated0_[8];           // Deprecated member
    uint16_t variant_count_;               // Number of DPU variants
    uint8_t pad_[6];                     // Padding
};
```

### VpuDPUVariant (40xx: 40 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:317`.

```c
struct VPU_ALIGNED_STRUCT(4) VpuDPUVariant {
    VpuDPUVariantRegisters registers_;     // DPU variant registers
    VpuPtr<VpuDPUInvariant> invariant_; // Pointer to invariant
    uint32_t invariant_index_;           // Index in variant array
    uint32_t weight_table_offset_;       // Weight table offset
    int32_t wload_id_;                 // Workload ID
    uint8_t cluster_;                   // Cluster ID
    uint8_t pad_[3];                   // Padding
};
```

### VpuActKernelRange (40xx: 40 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:283`.

```c
struct VPU_ALIGNED_STRUCT(8) VpuActKernelRange {
    VpuActWLType type;                      // Workload type
    uint8_t use_ram_barriers;               // Use RAM barriers
    uint8_t pad0_[6];                      // Padding
    VpuPtr<actKernelEntryFunction> kernel_entry; // Kernel entry point
    VpuPtr<void> text_window_base;            // Code window base
    uint32_t code_size;                      // Code size
    uint8_t deprecated_[4];                 // Deprecated member
    uint32_t kernel_invo_count;              // Number of invocations
    uint8_t pad1_[4];                      // Padding
};
```

### VpuActKernelInvocation (40xx: 96 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:298`.

```c
struct VPU_ALIGNED_STRUCT(32) VpuActKernelInvocation {
    VpuPtr<VpuActKernelRange> range;         // Pointer to kernel range
    VpuPtr<void> kernel_args;                // Kernel arguments
    VpuPtr<void> data_window_base;           // Data window base
    VpuPtr<void> perf_packet_out;            // Performance output
    VpuTaskBarrierDependency barriers;        // Barrier dependencies (40 bytes)
    VpuTaskSchedulingBarrierConfig barriers_sched; // Scheduling
    uint32_t invo_index;                   // Invocation index
    uint32_t invo_tile;                    // Tile index
    uint32_t kernel_range_index;            // Range index
    uint32_t next_aki_wl_addr;            // Next AKI workload address
    uint8_t pad_[4];                      // Padding
};
```

### VpuDMATask (40xx: 224 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:273`.

```c
struct VPU_ALIGNED_STRUCT(32) VpuDMATask {
    DmaDescriptor transaction_;  // DMA transaction descriptor
    VpuTaskSchedulingBarrierConfig barriers_sched_; // Scheduling
    uint8_t pad_[24];                   // Padding to 224 bytes
};
```

### VpuMediaTask (40xx: 240 bytes)

Located in `firmware/include/api/vpu_nnrt_api_40xx.h:316`.

```c
struct VPU_ALIGNED_STRUCT(16) VpuMediaTask {
    union VPU_ALIGNED_STRUCT(16) {
        struct VPU_ALIGNED_STRUCT(16) {
            VpuMediaBuffDescriptor buff_desc_;
            VpuMediaROIDescriptor roi_desc_;
        } standard;
        struct VPU_ALIGNED_STRUCT(16) {
            VpuMediaBuffDescriptor buff_desc_;
            VpuMediaExtendedHeader ext_hdr_;
            VpuMediaROIDescriptor roi_desc_;
        } extended;
    };
    VpuTaskSchedulingBarrierConfig barriers_sched_;
    uint8_t pad0_[8];
};
```

### Inference Descriptor Types

When using INFERENCE_EXECUTE, the descriptor heap may contain these descriptor types:

| Type ID | Name | Purpose | Size |
|----------|------|---------|-------|
| 0x100 | SCRATCH | Scratch buffer allocation | Variable |
| 0x101 | METADATA | Blob metadata reference | Variable |
| 0x102 | WEIGHTS | Network weights reference | Variable |
| 0x103 | KERNEL_DATA | DPU kernel code reference | Variable |
| 0x200 | INPUT | Input tensor reference | Variable |
| 0x201 | OUTPUT | Output tensor reference | Variable |
| 0x202 | PROFILING_OUTPUT | Performance profiling output | Variable |

Each descriptor is 64 bytes and typically contains:
- VPU address of the actual data
- Size information
- Additional metadata (format-dependent)

**Note**: The COPY descriptor format is known and implemented. Inference descriptor formats need reverse engineering.

### Key Constants for 40xx

```c
constexpr uint32_t VPU_MAX_TILES = 6;       // Maximum number of compute tiles
constexpr uint32_t VPU_MAX_DMA_ENGINES = 2;  // DDR + CMX DMA engines per tile
```

These constants define the array sizes in VpuMappedInference structure.

## Recommended Improvements to Lifter

1. **Parse descriptor heap entries**: When COPY or INFERENCE_EXECUTE commands reference descriptor heap, parse descriptors and extract:
   - For COPY: src_address, dst_address, size (already implemented)
   - For INFERENCE: Type-specific descriptor parsing (needs reverse engineering)

2. **Parse VpuMappedInference when present**: Add full parsing of:
   - Follow VpuTaskReference arrays to parse actual task structures
   - Parse VpuDPUInvariant, VpuDPUVariant for each tile
   - Parse VpuActKernelRange, VpuActKernelInvocation for each tile
   - Parse VpuDMATask arrays (DDR and CMX)
   - Parse VpuMediaTask if present

3. **Detect 40xx architecture**: Use `vpu_nnrt_api_ver` to verify:
   - 0x00040000 → 40xx architecture
   - Use correct structure sizes (VpuMappedInference = 1728 bytes)
   - Use VPU_MAX_TILES (6) for array sizes

4. **Handle both access modes in Host Parsed Inference**:
   - When `mmi_access_ = INDIRECT`: use `mapped_` field
   - When `mmi_access_ = DIRECT`: use `managed_inference_` field

5. **Parse task arrays**: For 40xx, parse these arrays with VPU_MAX_TILES elements:
   - dma_tasks_ddr_[], dma_tasks_cmx_[]
   - invariants[], variants[]
   - act_kernel_ranges[], act_kernel_invocations[]

6. **Update protobuf schema**: Add messages for:
   - VpuDPUInvariant (40xx)
   - VpuDPUVariant (40xx)
   - VpuActKernelRange (40xx)
   - VpuActKernelInvocation (40xx)
   - VpuDMATask (40xx)
   - VpuMediaTask (40xx)
   - DmaDescriptor (used in VpuDMATask)

**Priority for fuzzing:**
1. Focus on COPY commands and descriptors (already well-defined)
2. Focus on Host Parsed Inference (fully parsed)
3. VpuMappedInference and task arrays (structure defined but parsing complex)
4. Inference descriptors in descriptor heap (needs reverse engineering)
