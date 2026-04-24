#!/usr/bin/env python3
"""
VPU Job Lifter - Binary to Protobuf Converter
Converts VPU job binaries captured from the kernel to structured Protobuf format.
"""

import struct
import sys
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
import json

try:
    import vpu_job_pb2
except ImportError:
    print("Error: vpu_job_pb2 not found. Please compile vpu_job.proto first:")
    print("  protoc --python_out=. vpu_job.proto")
    sys.exit(1)

# Constants from firmware API
VPU_CONTEXT_SAVE_AREA_SIZE = 64
# Binary format uses uint16 (2 bytes), proto stores as uint32 (4 bytes)
# We read 2 bytes from binary, store as 4 bytes in proto
VPU_CMD_HEADER_SIZE = 4  # uint16_t type + uint16_t size
VPU_CMD_BUFFER_HEADER_SIZE = 48  # vpu_cmd_buffer_header_t

# VpuHostParsedInference sizes
VPU_HOST_PARSED_INFERENCE_SIZE = 384  # Total size
VPU_RESOURCE_REQUIREMENTS_SIZE = 12   # ResourceRequirements size
VPU_PERFORMANCE_METRICS_SIZE = 320   # PerformanceMetrics size
VPU_TASK_REFERENCE_SIZE = 40

# Command types
VPU_CMD_TYPE = {
    0x0000: 'UNKNOWN',
    0x0001: 'NOP',
    0x0100: 'TIMESTAMP',
    0x0101: 'FENCE_WAIT',
    0x0102: 'FENCE_SIGNAL',
    0x0103: 'BARRIER',
    0x0104: 'METRIC_QUERY_BEGIN',
    0x0105: 'METRIC_QUERY_END',
    0x0202: 'MEMORY_FILL',
    0x0302: 'COPY',
    0x0306: 'INFERENCE_EXECUTE',
}

# Descriptor types
VPU_DESC_TYPE = {
    0x100: 'SCRATCH',
    0x101: 'METADATA',
    0x102: 'WEIGHTS',
    0x103: 'KERNEL_DATA',
    0x200: 'INPUT',
    0x201: 'OUTPUT',
    0x202: 'PROFILING_OUTPUT',
}

# Command size mappings (minimum sizes, excluding header)
CMD_MIN_SIZE = {
    'NOP': 0,
    'TIMESTAMP': 12,
    'FENCE_WAIT': 20,
    'FENCE_SIGNAL': 20,
    'BARRIER': 4,
    'METRIC_QUERY_BEGIN': 12,
    'METRIC_QUERY_END': 12,
    'MEMORY_FILL': 28,
    'COPY': 20,
    'INFERENCE_EXECUTE': 24,
}

def fw_data_cache_align(size: int) -> int:
    """Align to 64 bytes as per firmware cache line requirement."""
    return (size + 63) & ~63

def parse_hex_string(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str.strip())

class VpuJobLifter:
    """Lifts VPU job binaries to Protobuf format."""

    def __init__(self, json_path: str):
        self.json_path = Path(json_path)
        with open(json_path, 'r') as f:
            self.job_data = json.load(f)

    def lift(self) -> vpu_job_pb2.VpuJob:
        """Main lifting function."""
        job = vpu_job_pb2.VpuJob()

        job.vpu_fd = self.job_data.get('vpuFd', 0)
        job.cmdq_id = self.job_data.get('cmdq_id', 0)
        job.buffers_ptr = int(self.job_data.get('buffers_ptr', '0'), 16)
        job.buffer_count = self.job_data.get('buffer_count', 0)
        job.commands_offset = self.job_data.get('commands_offset', 0)
        job.preempt_buffer_index = self.job_data.get('preempt_buffer_index', 0)

        for buf_data in self.job_data.get('buffers', []):
            buf = job.buffers.add()
            buf.index = buf_data.get('index', 0)
            buf.handle = buf_data.get('handle', 0)
            buf.vpu_addr = int(buf_data.get('vpu_addr', '0'), 16)
            buf.size = buf_data.get('size', 0)
            buf.mmap_offset = buf_data.get('mmap_offset', 0)
            buf.flags = buf_data.get('flags', 0)

            # Parse buffer content
            raw_data = parse_hex_string(buf_data.get('data', ''))
            buf.raw_data = raw_data

            # Try to parse as Host Parsed Inference (Buffer 1)
            if buf.index == 1 and len(raw_data) >= VPU_HOST_PARSED_INFERENCE_SIZE:
                parsed_hpi = self._parse_host_parsed_inference(raw_data)
                if parsed_hpi:
                    buf.host_parsed_inference.CopyFrom(parsed_hpi)

            # Try to parse as Mapped Inference
            elif len(raw_data) >= 448:  # Minimum size for VpuMappedInference
                mapped_inf = self._parse_mapped_inference(raw_data)
                if mapped_inf:
                    buf.mapped_inference.CopyFrom(mapped_inf)

        return job

    def _parse_host_parsed_inference(self, data: bytes) -> Optional[vpu_job_pb2.VpuHostParsedInference]:
        """Parse VpuHostParsedInference structure from buffer data."""
        if len(data) < VPU_HOST_PARSED_INFERENCE_SIZE:
            return None

        try:
            hpi = vpu_job_pb2.VpuHostParsedInference()

            # Parse reserved (offset 0-8)
            hpi.reserved = struct.unpack('<Q', data[0:8])[0]

            # Parse ResourceRequirements (offset 8-20)
            res_req = hpi.resource_requirements
            res_req.nn_slice_length = struct.unpack('<I', data[8:12])[0]
            res_req.deprecated = data[12:18]
            res_req.nn_slice_count = data[18]
            res_req.nn_barriers = data[19]

            # MMI access + padding (offset 20-24)
            hpi.mmi_access = data[20]
            hpi.pad_0 = data[21:24]

            # Parse VpuPerformanceMetrics (offset 24-344)
            perf = hpi.performance_metrics
            perf.freq_base = struct.unpack('<I', data[24:28])[0]
            perf.freq_step = struct.unpack('<I', data[28:32])[0]
            perf.bw_base = struct.unpack('<I', data[32:36])[0]
            perf.bw_step = struct.unpack('<I', data[36:40])[0]

            # Parse ticks and scalability tables (offset 44-364)
            # Each is [5][5] array: 25 elements of 8 bytes for ticks (200 bytes)
            #                        25 elements of 4 bytes for scalability (100 bytes)
            ticks_data = data[40:240]
            for i in range(25):
                tick_val = struct.unpack('<Q', ticks_data[i*8:(i+1)*8])[0]
                perf.ticks.append(tick_val)

            scal_data = data[240:340]
            for i in range(25):
                scal_val = struct.unpack('<f', scal_data[i*4:(i+1)*4])[0]
                perf.scalability.append(scal_val)

            perf.activity_factor = struct.unpack('<f', data[340:344])[0]

            # Parse VpuTaskReference union (offset 344-384)
            task_ref = self._parse_task_reference(data[344:384])
            if hpi.mmi_access == vpu_job_pb2.VPU_MMI_DIRECT:
                hpi.managed_inference.CopyFrom(task_ref)
            else:
                hpi.mapped.CopyFrom(task_ref)

            return hpi
        except Exception as e:
            print(f"Warning: Failed to parse Host Parsed Inference: {e}")
            return None

    def _parse_task_reference(self, data: bytes) -> vpu_job_pb2.VpuTaskReference:
        """Parse VpuTaskReference structure (40 bytes)."""
        ref = vpu_job_pb2.VpuTaskReference()
        if len(data) < VPU_TASK_REFERENCE_SIZE:
            return ref
        ref.reserved_0 = struct.unpack('<Q', data[0:8])[0]
        ref.reserved_1 = struct.unpack('<Q', data[8:16])[0]
        ref.reserved_2 = struct.unpack('<Q', data[16:24])[0]
        ref.address = struct.unpack('<Q', data[24:32])[0]
        ref.count = struct.unpack('<Q', data[32:40])[0]
        return ref

    def _parse_mapped_inference(self, data: bytes) -> Optional[vpu_job_pb2.VpuMappedInference]:
        """Parse VpuMappedInference structure from buffer data (40xx)."""
        if len(data) < 1728:
            return None

        try:
            mapped_inf = vpu_job_pb2.VpuMappedInference()

            mapped_inf.vpu_nnrt_api_ver = struct.unpack('<I', data[0:4])[0]
            mapped_inf.pad_0 = struct.unpack('<I', data[4:8])[0]
            mapped_inf.reserved_0 = struct.unpack('<Q', data[8:16])[0]
            mapped_inf.logaddr_dma_hwp_ = struct.unpack('<Q', data[16:24])[0]

            counts = mapped_inf.task_storage_counts
            counts.reserved1 = struct.unpack('<I', data[24:28])[0]
            counts.reserved2 = struct.unpack('<I', data[28:32])[0]
            counts.dma_ddr_count = struct.unpack('<I', data[32:36])[0]
            counts.dma_cmx_count = struct.unpack('<I', data[36:40])[0]
            counts.dpu_invariant_count = struct.unpack('<I', data[40:44])[0]
            counts.dpu_variant_count = struct.unpack('<I', data[44:48])[0]
            counts.act_range_count = struct.unpack('<I', data[48:52])[0]
            counts.act_invo_count = struct.unpack('<I', data[52:56])[0]
            counts.media_count = struct.unpack('<I', data[56:60])[0]

            mapped_inf.task_storage_size = struct.unpack('<I', data[60:64])[0]

            offset = 64
            offset = self._parse_task_reference_array(mapped_inf.dma_tasks_ddr, data, offset, 6)
            offset = self._parse_task_reference_array(mapped_inf.dma_tasks_cmx, data, offset, 6)
            offset = self._parse_task_reference_array(mapped_inf.invariants, data, offset, 6)
            offset = self._parse_task_reference_array(mapped_inf.variants, data, offset, 6)
            offset = self._parse_task_reference_array(mapped_inf.act_kernel_ranges, data, offset, 6)
            offset = self._parse_task_reference_array(mapped_inf.act_kernel_invocations, data, offset, 6)

            mapped_inf.media_tasks.CopyFrom(self._parse_task_reference(data[offset:offset + VPU_TASK_REFERENCE_SIZE]))
            offset += VPU_TASK_REFERENCE_SIZE
            mapped_inf.barrier_configs.CopyFrom(self._parse_task_reference(data[offset:offset + VPU_TASK_REFERENCE_SIZE]))
            offset += VPU_TASK_REFERENCE_SIZE

            mapped_inf.shv_rt_configs.CopyFrom(self._parse_nn_shave_runtime_configs(data[offset:offset + 96]))
            offset += 96

            mapped_inf.hwp_workpoint_cfg_addr = struct.unpack('<Q', data[offset:offset + 8])[0]
            offset += 8
            mapped_inf.managed_inference.CopyFrom(self._parse_task_reference(data[offset:offset + VPU_TASK_REFERENCE_SIZE]))

            return mapped_inf
        except Exception as e:
            print(f"Warning: Failed to parse Mapped Inference: {e}")
            return None

    def _parse_task_reference_array(self, target, data: bytes, offset: int, count: int) -> int:
        for _ in range(count):
            target.add().CopyFrom(self._parse_task_reference(data[offset:offset + VPU_TASK_REFERENCE_SIZE]))
            offset += VPU_TASK_REFERENCE_SIZE
        return offset

    def _parse_nn_shave_runtime_configs(self, data: bytes) -> vpu_job_pb2.VpuNNShaveRuntimeConfigs:
        cfg = vpu_job_pb2.VpuNNShaveRuntimeConfigs()
        if len(data) < 96:
            return cfg

        cfg.reserved = struct.unpack('<Q', data[0:8])[0]
        cfg.runtime_entry = struct.unpack('<Q', data[8:16])[0]
        cfg.act_rt_window_base = struct.unpack('<Q', data[16:24])[0]

        union_data = data[24:72]
        ref = self._parse_task_reference(union_data[0:40])
        pad = struct.unpack('<Q', union_data[40:48])[0]
        if ref.address != 0 or ref.count != 0:
            cfg.stack_frames_ref.ref.CopyFrom(ref)
            cfg.stack_frames_ref.pad_0 = pad
        else:
            for i in range(12):
                val = struct.unpack('<I', union_data[i * 4:(i + 1) * 4])[0]
                cfg.stack_frames_array.stack_frames.append(val)

        cfg.stack_size = struct.unpack('<I', data[72:76])[0]
        cfg.code_window_buffer_size = struct.unpack('<I', data[76:80])[0]
        cfg.perf_metrics_mask = struct.unpack('<I', data[80:84])[0]
        cfg.runtime_version = struct.unpack('<I', data[84:88])[0]
        cfg.use_schedule_embedded_rt = data[88]
        cfg.dpu_perf_mode = data[89]
        cfg.pad_0 = data[90:96]
        return cfg

    def parse_command_buffer(self, buffer_bytes: bytes) -> vpu_job_pb2.VpuCommandBuffer:
        """Parse command buffer structure."""
        if len(buffer_bytes) < 128:
            raise ValueError("Buffer too small for command header")

        cmd_buffer = vpu_job_pb2.VpuCommandBuffer()

        # Parse prefix (first 128 bytes)
        cmd_buffer.prefix.context_save_area = buffer_bytes[0:64]
        cmd_buffer.prefix.fence_value = struct.unpack('<Q', buffer_bytes[64:72])[0]
        reserved = struct.unpack('<7Q', buffer_bytes[72:128])
        cmd_buffer.prefix.reserved.extend(reserved)

        # Parse vpu_cmd_buffer_header (from offset 128)
        # Structure: 4 * uint32 + 3 * uint64 = 48 bytes
        header_offset = 128
        if len(buffer_bytes) < header_offset + VPU_CMD_BUFFER_HEADER_SIZE:
            raise ValueError("Buffer too small for vpu_cmd_buffer_header")

        try:
            header_fields = struct.unpack('<4I4Q', buffer_bytes[header_offset:header_offset + 48])
            cmd_buffer.header.cmd_buffer_size = header_fields[0]
            cmd_buffer.header.cmd_offset = header_fields[1]
            cmd_buffer.header.api_version = header_fields[2]
            cmd_buffer.header.reserved_0 = header_fields[3]
            cmd_buffer.header.descriptor_heap_base_address = header_fields[4]
            cmd_buffer.header.submission_timestamp = header_fields[5]
            cmd_buffer.header.fence_heap_base_address = header_fields[6]
            cmd_buffer.header.context_save_area_address = header_fields[7]
        except Exception as e:
            print(f"Warning: Failed to parse header at offset {header_offset}: {e}")
            cmd_buffer.header.cmd_buffer_size = 0
            cmd_buffer.header.cmd_offset = 0
            cmd_buffer.header.context_save_area_address = 0

        # Parse internal sync fences (2 fences after header, each 24 bytes)
        internal_sync_offset = header_offset + VPU_CMD_BUFFER_HEADER_SIZE
        for i in range(2):
            fence_offset = internal_sync_offset + i * 24
            if len(buffer_bytes) >= fence_offset + 4:
                fence = cmd_buffer.internal_sync.internal_fences.add()
                # Read uint16 (2 bytes) for type and size
                fence.header.type = struct.unpack('<H', buffer_bytes[fence_offset:fence_offset + 2])[0]
                fence.header.size = struct.unpack('<H', buffer_bytes[fence_offset + 2:fence_offset + 4])[0]
                if len(buffer_bytes) >= fence_offset + 24:
                    fence.reserved_0 = struct.unpack('<I', buffer_bytes[fence_offset + 4:fence_offset + 8])[0]
                    fence.offset = struct.unpack('<Q', buffer_bytes[fence_offset + 8:fence_offset + 16])[0]
                    fence.value = struct.unpack('<Q', buffer_bytes[fence_offset + 16:fence_offset + 24])[0]

        # Parse command list (starting at cmd_offset from header start)
        cmd_list_offset = header_offset + cmd_buffer.header.cmd_offset
        cmd_list_size = cmd_buffer.header.cmd_buffer_size - cmd_buffer.header.cmd_offset

        self._parse_commands(cmd_buffer, buffer_bytes, cmd_list_offset, cmd_list_size)

        return cmd_buffer

    def _parse_commands(self, cmd_buffer: vpu_job_pb2.VpuCommandBuffer,
                      buffer_bytes: bytes, offset: int, size: int):
        """Parse command list from buffer."""
        current_offset = offset
        end_offset = offset + size

        while current_offset < end_offset:
            if current_offset + VPU_CMD_HEADER_SIZE > len(buffer_bytes):
                print(f"Warning: Truncated command header at offset {current_offset}")
                break

            # Binary format uses uint16, proto stores as uint32
            # Read 2 bytes, store as 4 bytes
            try:
                cmd_type, cmd_size = struct.unpack('<HH',
                                                buffer_bytes[current_offset:current_offset + VPU_CMD_HEADER_SIZE])
            except Exception as e:
                print(f"Warning: Failed to read command header at offset {current_offset}: {e}")
                print(f"  Buffer length: {len(buffer_bytes)}")
                print(f"  Attempting to read at: {current_offset}")
                break

            cmd_name = VPU_CMD_TYPE.get(cmd_type, f'UNKNOWN({cmd_type:04x})')


            if cmd_type == 0x0000:  # UNKNOWN
                print(f"Warning: Unknown command type at offset {current_offset}")
                break

            if current_offset + cmd_size > len(buffer_bytes):
                print(f"Warning: Command {cmd_name} truncated at offset {current_offset}")
                break

            cmd = cmd_buffer.commands.add()
            cmd_data = buffer_bytes[current_offset:current_offset + cmd_size]

            try:
                self._parse_single_command(cmd, cmd_type, cmd_data)
            except Exception as e:
                print(f"Warning: Failed to parse command {cmd_name}: {e}")

            current_offset += cmd_size

    def _parse_single_command(self, cmd: vpu_job_pb2.VpuCommand,
                           cmd_type: int, cmd_data: bytes):
        """Parse a single command based on its type."""
        if cmd_type == 0x0001:  # NOP
            nop = vpu_job_pb2.VpuCmdNop()
            nop.header.type = cmd_type
            nop.header.size = len(cmd_data)
            cmd.nop.CopyFrom(nop)

        elif cmd_type == 0x0100:  # TIMESTAMP
            ts = vpu_job_pb2.VpuCmdTimestamp()
            ts.header.type = cmd_type
            ts.header.size = len(cmd_data)
            if len(cmd_data) >= 16:
                ts.type = struct.unpack('<I', cmd_data[4:8])[0]
                ts.timestamp_address = struct.unpack('<Q', cmd_data[8:16])[0]
            cmd.timestamp.CopyFrom(ts)

        elif cmd_type in (0x0101, 0x0102):  # FENCE_WAIT or FENCE_SIGNAL
            fence = vpu_job_pb2.VpuCmdFence()
            fence.header.type = cmd_type
            fence.header.size = len(cmd_data)
            if len(cmd_data) >= 24:
                fence.reserved_0 = struct.unpack('<I', cmd_data[4:8])[0]
                fence.offset = struct.unpack('<Q', cmd_data[8:16])[0]
                fence.value = struct.unpack('<Q', cmd_data[16:24])[0]
            cmd.fence.CopyFrom(fence)

        elif cmd_type == 0x0103:  # BARRIER
            barrier = vpu_job_pb2.VpuCmdBarrier()
            barrier.header.type = cmd_type
            barrier.header.size = len(cmd_data)
            if len(cmd_data) >= 8:
                barrier.reserved_0 = struct.unpack('<I', cmd_data[4:8])[0]
            cmd.barrier.CopyFrom(barrier)

        elif cmd_type in (0x0104, 0x0105):  # METRIC_QUERY
            metric = vpu_job_pb2.VpuCmdMetricQuery()
            metric.header.type = cmd_type
            metric.header.size = len(cmd_data)
            if len(cmd_data) >= 16:
                metric.metric_group_type = struct.unpack('<I', cmd_data[4:8])[0]
                metric.metric_data_address = struct.unpack('<Q', cmd_data[8:16])[0]
            cmd.metric_query.CopyFrom(metric)

        elif cmd_type == 0x0202:  # MEMORY_FILL
            fill = vpu_job_pb2.VpuCmdMemoryFill()
            fill.header.type = cmd_type
            fill.header.size = len(cmd_data)
            if len(cmd_data) >= 32:
                fill.reserved_0 = struct.unpack('<I', cmd_data[4:8])[0]
                fill.start_address = struct.unpack('<Q', cmd_data[8:16])[0]
                fill.size = struct.unpack('<Q', cmd_data[16:24])[0]
                fill.fill_pattern = struct.unpack('<I', cmd_data[24:28])[0]
                fill.reserved_1 = struct.unpack('<I', cmd_data[28:32])[0]
            cmd.memory_fill.CopyFrom(fill)

        elif cmd_type == 0x0302:  # COPY
            copy = vpu_job_pb2.VpuCmdCopyBuffer()
            copy.header.type = cmd_type
            copy.header.size = len(cmd_data)
            if len(cmd_data) >= 24:
                copy.reserved_0 = struct.unpack('<I', cmd_data[4:8])[0]
                copy.desc_start_offset = struct.unpack('<Q', cmd_data[8:16])[0]
                copy.desc_count = struct.unpack('<I', cmd_data[16:20])[0]
                copy.reserved_1 = struct.unpack('<I', cmd_data[20:24])[0]
            cmd.copy.CopyFrom(copy)

        elif cmd_type == 0x0306:  # INFERENCE_EXECUTE
            inf = vpu_job_pb2.VpuCmdInferenceExecute()
            inf.header.type = cmd_type
            inf.header.size = len(cmd_data)
            if len(cmd_data) >= 32:
                inf.reserved_0 = struct.unpack('<I', cmd_data[4:8])[0]
                inf.inference_id = struct.unpack('<Q', cmd_data[8:16])[0]
                if len(cmd_data) >= 32:
                    inf.host_mapped_inference.address = struct.unpack('<Q', cmd_data[16:24])[0]
                    inf.host_mapped_inference.width = struct.unpack('<I', cmd_data[24:28])[0]
                    inf.host_mapped_inference.reserved_0 = struct.unpack('<I', cmd_data[28:32])[0]
            cmd.inference_execute.CopyFrom(inf)

        elif cmd_type == 0x0100:  # TIMESTAMP (duplicate case)
            ts = vpu_job_pb2.VpuCmdTimestamp()
            ts.header.type = cmd_type
            ts.header.size = len(cmd_data)
            if len(cmd_data) >= 16:
                ts.type = struct.unpack('<I', cmd_data[4:8])[0]
                ts.timestamp_address = struct.unpack('<Q', cmd_data[8:16])[0]
            cmd.timestamp.CopyFrom(ts)

        else:
            # Unknown command, store as much as possible
            nop = vpu_job_pb2.VpuCmdNop()
            nop.header.type = cmd_type
            nop.header.size = len(cmd_data)
            cmd.nop.CopyFrom(nop)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lift_vpu_job.py <vpu_job.json> [output.pb]")
        print("\nConverts VPU job JSON dump to Protobuf format.")
        sys.exit(1)

    json_path = sys.argv[1]

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_path = Path(json_path).stem + '.pb'

    try:
        lifter = VpuJobLifter(json_path)
        job = lifter.lift()

        # Optionally parse the command buffer (first buffer)
        if job.buffer_count > 0:
            try:
                first_buffer = job.buffers[0]
                if first_buffer.HasField('raw_data'):
                    cmd_buffer = lifter.parse_command_buffer(first_buffer.raw_data)
                    print(f"Command buffer parsed successfully:")
                    print(f"  Buffer size: {first_buffer.size} bytes")
                    print(f"  Command buffer size: {cmd_buffer.header.cmd_buffer_size}")
                    print(f"  Number of commands: {len(cmd_buffer.commands)}")

                    for i, cmd in enumerate(cmd_buffer.commands):
                        cmd_type = 0
                        cmd_size = 0
                        if cmd.HasField('nop'):
                            cmd_type = cmd.nop.header.type
                            cmd_size = cmd.nop.header.size
                        elif cmd.HasField('timestamp'):
                            cmd_type = cmd.timestamp.header.type
                            cmd_size = cmd.timestamp.header.size
                        elif cmd.HasField('fence'):
                            cmd_type = cmd.fence.header.type
                            cmd_size = cmd.fence.header.size
                        elif cmd.HasField('barrier'):
                            cmd_type = cmd.barrier.header.type
                            cmd_size = cmd.barrier.header.size
                        elif cmd.HasField('metric_query'):
                            cmd_type = cmd.metric_query.header.type
                            cmd_size = cmd.metric_query.header.size
                        elif cmd.HasField('memory_fill'):
                            cmd_type = cmd.memory_fill.header.type
                            cmd_size = cmd.memory_fill.header.size
                        elif cmd.HasField('copy'):
                            cmd_type = cmd.copy.header.type
                            cmd_size = cmd.copy.header.size
                        elif cmd.HasField('inference_execute'):
                            cmd_type = cmd.inference_execute.header.type
                            cmd_size = cmd.inference_execute.header.size

                        cmd_name = VPU_CMD_TYPE.get(cmd_type, f'UNKNOWN({cmd_type:04x})')
                        print(f"    Command {i}: {cmd_name} (type=0x{cmd_type:04x}, size={cmd_size})")

                    # Check if Buffer 1 was parsed as Host Parsed Inference
                    if len(job.buffers) > 1 and job.buffers[1].HasField('host_parsed_inference'):
                        hpi = job.buffers[1].host_parsed_inference
                        print(f"\nHost Parsed Inference parsed:")
                        print(f"  nn_slice_count: {hpi.resource_requirements.nn_slice_count}")
                        print(f"  nn_barriers: {hpi.resource_requirements.nn_barriers}")
                        print(f"  activity_factor: {hpi.performance_metrics.activity_factor}")
            except Exception as e:
                print(f"Warning: Failed to parse command buffer: {e}")

        # Serialize to file
        with open(output_path, 'wb') as f:
            f.write(job.SerializeToString())

        print(f"\nSuccessfully lifted {json_path} -> {output_path}")
        print(f"Total buffers: {job.buffer_count}")
        print(f"VPU FD: {job.vpu_fd}, CmdQ ID: {job.cmdq_id}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
