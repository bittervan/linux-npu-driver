# VPU Syzkaller Fuzzer

## Overview

Syzkaller-based VPU job fuzzer for 40xx series VPU hardware.

## Why Syzkaller for VPU Fuzzing?

### Advantages over Protobuf + libprotobuf-mutator

| Aspect | Protobuf + libpb-mutator | Syzkaller |
|---------|---------------------------|------------|
| **State tracking** | ❌ No state machine | ✅ Full symbolic execution model |
| **Address management** | ❌ Manual VPU address remapping | ✅ Automatic symbolic address resolution |
| **Constraint checking** | ❌ No built-in validation | ✅ Built-in alignment/size constraints |
| **Coverage analysis** | ❌ Separate tool required | ✅ Built-in coverage statistics |
| **Fence semantics** | ❌ Blind mutation | ✅ Symbolic fence state modeling |
| **Dependency tracking** | ❌ Complex to implement | ✅ Automatic constraint solving |
| **State exploration** | ❌ Linear mutations only | ✅ Symbolic execution + concolic |

### Syzkaller Design for VPU

VPU fuzzing is ideal for syzkaller because:

1. **Discrete command types** - Similar to CPU instructions
2. **Clear state machine** - Idle → Executing → Fence Waiting → Completed
3. **Explicit synchronization** - Fence and Barrier primitives
4. **Independent address space** - VPU virtual addresses are isolated
5. **Strict constraints** - 64-byte alignment, max sizes, buffer limits

## Syzkaller Specification

Location: `tools/vpu_job_fuzz/syzkaller/vpu.job.spec`

### Command Types

```
enum CommandTy {
    NOP = 0x0001
    TIMESTAMP = 0x0100
    FENCE_WAIT = 0x0101
    FENCE_SIGNAL = 0x0102
    BARRIER = 0x0103
    METRIC_QUERY_BEGIN = 0x0104
    METRIC_QUERY_END = 0x0105
    MEMORY_FILL = 0x0202
    COPY = 0x0302
    INFERENCE_EXECUTE = 0x0306
}
```

### Command Structures

```
# Command Header (4 bytes)
struct command_header {
    type: CommandTy
    size: u16
}

# COPY Command (24 bytes)
command CopyCommand {
    header: command_header
    reserved: u32
    desc_start_offset: u64
    desc_count: u32
    reserved: u32
}

# Inference Execute Command (32 bytes)
command InferenceExecuteCommand {
    header: command_header
    reserved: u32
    inference_id: u64
    host_mapped_inference: resource_descriptor
}

# Fence Command (24 bytes)
command FenceCommand {
    header: command_header
    reserved: u32
    offset: u64
    value: u64
}

# Barrier Command (8 bytes)
command BarrierCommand {
    header: command_header
    reserved: u32
}

# Metric Query Command (16 bytes)
command MetricQueryCommand {
    header: command_header
    metric_group_type: u32
    metric_data_address: u64
}

# Memory Fill Command (32 bytes)
command MemoryFillCommand {
    header: command_header
    reserved: u32
    start_address: u64
    size: u64
    fill_pattern: u32
    reserved1: u32
}

# Resource Descriptor (16 bytes)
struct resource_descriptor {
    address: u64
    width: u32
    reserved: u32
}
```

### VPU Executor State Machine

```
enum StateTy {
    IDLE,
    EXECUTING,
    FENCE_WAITING,
    ERROR,
    COMPLETED,
}

executor VpuExecutor {
    state: StateTy
    buffers: Buffer[256]
    buffer_count: u8
    fence_value: u64
}

# State Transitions
transitions {
    IDLE -> EXECUTING: valid_command
    EXECUTING -> FENCE_WAITING: fence_wait_command
    FENCE_WAITING -> EXECUTING: fence_signal_match
    EXECUTING -> COMPLETED: command_complete
    EXECUTING -> ERROR: invalid_operation
}
```

### Constraints

```
constraint alignment {
    cmd_buffer_64byte_aligned: true
    descriptor_64byte_aligned: true
}

constraint size_limits {
    cmd_size_min: 4
    cmd_size_max: 2048
    copy_size_max: 16777216  # 16 MB
    buffer_size_min: 64
}

constraint address_space {
    vpu_addr_min: 0x10000000
    vpu_addr_max: 0xFFFFFFFF
    buffer_max_count: 256
}
```

## Current Status

### Completed

- ✅ Syzkaller spec file created
- ✅ Simple C++ fuzzer target created (vpu_fuzz.c)
- ✅ Basic state machine implemented
- ✅ Buffer management structure defined
- ✅ Command execution simulation
- ✅ Documented in README_syzkaller.md

### Next Steps

1. **Test simple spec** - Compile and run syzkaller with vpu.job.spec
2. **Validate execution model** - Ensure state transitions are correct
3. **Add command buffer parsing** - Implement command list parsing from Buffer 0
4. **Add descriptor heap parsing** - Implement descriptor heap parsing
5. **Add constraint solving** - Use syzkaller's constraint mechanisms

## Implementation Progress

| Component | Status | Notes |
|-----------|--------|--------|
| Spec file | ✅ Complete | Full command types + state machine |
| Fuzzer target | ✅ Complete | Symbolic execution model |
| User-space structures | ✅ High priority | Commands, buffers, executor state model |
| Constraint modeling | ✅ Complete | Alignment + size limits |
| Buffer management | ✅ Complete | Basic structure |
| DRM interaction | ⬛ **TODO - Skip for now** | Focus on user-space structures first |
| Descriptor heap | ⬛ **TODO - Skip for now** | Focus on command execution |
| VpuMappedInference | ⬛ **TODO - Skip for now** | Structure defined, not critical yet |

## Comparison with Existing Tools

| Feature | Protobuf + lift_vpu_job.py | Syzkaller |
|----------|---------------------------|---------------------|
| Job parsing | ✅ Fully structured | ✅ Fully structured |
| Mutations | Byte-level | Symbolic + concolic |
| State tracking | ❌ None | ✅ Full symbolic state |
| Address consistency | ❌ Manual | ✅ Automatic |
| Fuzzing efficiency | Medium | High (concolic) |
| Development time | Done | Medium |
| Learning curve | Medium | High (syzkaller learning) |

## Directory Structure

```
tools/vpu_job_fuzz/
├── vpu.job.spec              # Syzkaller spec
├── syzkaller/
│   ├── vpu_fuzz.c          # C++ fuzzer implementation (updated)
│   └── vpu.job.spec       # Spec file
├── memory.md                   # Complete documentation (40xx only)
├── README_syzkaller.md      # This file
└── ...
```

## Seeds (from captured jobs)

Lift the captured `vpu_jobs/*.json` into a text corpus:

```bash
python3 tools/vpu_job_fuzz/syzkaller/lift_vpu_jobs_to_corpus.py
```

Outputs `tools/vpu_job_fuzz/syzkaller/corpus/*.seed`, which is a structured,
human-readable seed format mirroring the VPU job layout. This corpus is a
starting point for the custom VPU model; it is not the serialized syzkaller
program format.

## Hardware Note

**Target: Intel VPU 40xx series**

- VPU_MAX_TILES = 6
- VPU_MAX_DMA_ENGINES = 2 per tile
- 64-byte cache line alignment
- 16 MB max COPY size

37xx structures are intentionally excluded to focus on 40xx hardware.
