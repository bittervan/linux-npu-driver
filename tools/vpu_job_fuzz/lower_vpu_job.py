#!/usr/bin/env python3
"""
VPU Job Lowerer - Protobuf to Binary Converter
Converts Protobuf VPU jobs back to binary format for submission to the driver.
"""

import struct
import sys
from pathlib import Path
from typing import List, Dict

try:
    import vpu_job_pb2
except ImportError:
    print("Error: vpu_job_pb2 not found. Please compile vpu_job.proto first:")
    print("  protoc --python_out=. vpu_job.proto")
    sys.exit(1)

VPU_CONTEXT_SAVE_AREA_SIZE = 64
# Binary format uses uint16 (2 bytes), proto stores as uint32 (4 bytes)
# We write 2 bytes using only low 16 bits from proto
VPU_CMD_HEADER_SIZE = 4

class VpuJobLowerer:
    """Lowers Protobuf VPU jobs to binary format."""

    def __init__(self, protobuf_path: str):
        self.protobuf_path = Path(protobuf_path)

    def lower(self) -> vpu_job_pb2.VpuJob:
        """Lower Protobuf to binary command buffer."""
        with open(self.protobuf_path, 'rb') as f:
            job = vpu_job_pb2.VpuJob()
            job.ParseFromString(f.read())

        return job

    def lower_command_buffer(self, cmd_buffer: vpu_job_pb2.VpuCommandBuffer) -> bytes:
        """Lower command buffer to binary."""
        result = bytearray()

        # Add prefix (context save area + fence + reserved)
        result.extend(cmd_buffer.prefix.context_save_area)
        result.extend(struct.pack('<Q', cmd_buffer.prefix.fence_value))
        for reserved in cmd_buffer.prefix.reserved:
            result.extend(struct.pack('<Q', reserved))

        # Add vpu_cmd_buffer_header
        header_data = struct.pack(
            '<5Q2I',
            cmd_buffer.header.cmd_buffer_size,
            cmd_buffer.header.cmd_offset,
            cmd_buffer.header.api_version,
            cmd_buffer.header.reserved_0,
            cmd_buffer.header.descriptor_heap_base_address,
            cmd_buffer.header.submission_timestamp,
            cmd_buffer.header.fence_heap_base_address,
            cmd_buffer.header.context_save_area_address
        )
        result.extend(header_data)

        # Add internal fences
        for fence in cmd_buffer.internal_sync.internal_fences:
            fence_data = struct.pack(
                '<H HQQ',
                fence.header.type,
                fence.header.size,
                fence.reserved_0,
                fence.offset,
                fence.value
            )
            result.extend(fence_data)

        # Add commands
        for cmd in cmd_buffer.commands:
            cmd_data = self._lower_command(cmd)
            result.extend(cmd_data)

        return bytes(result)

    def _lower_command(self, cmd: vpu_job_pb2.VpuCommand) -> bytes:
        """Lower a single command to binary."""
        if cmd.HasField('nop'):
            return self._lower_nop(cmd.nop)
        elif cmd.HasField('timestamp'):
            return self._lower_timestamp(cmd.timestamp)
        elif cmd.HasField('fence'):
            return self._lower_fence(cmd.fence)
        elif cmd.HasField('barrier'):
            return self._lower_barrier(cmd.barrier)
        elif cmd.HasField('metric_query'):
            return self._lower_metric_query(cmd.metric_query)
        elif cmd.HasField('memory_fill'):
            return self._lower_memory_fill(cmd.memory_fill)
        elif cmd.HasField('copy'):
            return self._lower_copy(cmd.copy)
        elif cmd.HasField('inference_execute'):
            return self._lower_inference_execute(cmd.inference_execute)
        else:
            raise ValueError("Unknown command type")

    def _lower_nop(self, nop: vpu_job_pb2.VpuCmdNop) -> bytes:
        # Write as uint16 using only low 16 bits from proto uint32
        return struct.pack('<HH', nop.header.type & 0xFFFF, nop.header.size & 0xFFFF)

    def _lower_timestamp(self, ts: vpu_job_pb2.VpuCmdTimestamp) -> bytes:
        return struct.pack(
            '<HH I Q',
            ts.header.type & 0xFFFF,
            ts.header.size & 0xFFFF,
            ts.type,
            ts.timestamp_address
        )

    def _lower_fence(self, fence: vpu_job_pb2.VpuCmdFence) -> bytes:
        return struct.pack(
            '<HH I Q Q',
            fence.header.type & 0xFFFF,
            fence.header.size & 0xFFFF,
            fence.reserved_0,
            fence.offset,
            fence.value
        )

    def _lower_barrier(self, barrier: vpu_job_pb2.VpuCmdBarrier) -> bytes:
        return struct.pack(
            '<HH I',
            barrier.header.type & 0xFFFF,
            barrier.header.size & 0xFFFF,
            barrier.reserved_0
        )

    def _lower_metric_query(self, metric: vpu_job_pb2.VpuCmdMetricQuery) -> bytes:
        return struct.pack(
            '<HH I Q',
            metric.header.type & 0xFFFF,
            metric.header.size & 0xFFFF,
            metric.metric_group_type,
            metric.metric_data_address
        )

    def _lower_memory_fill(self, fill: vpu_job_pb2.VpuCmdMemoryFill) -> bytes:
        return struct.pack(
            '<HH I Q Q I I',
            fill.header.type & 0xFFFF,
            fill.header.size & 0xFFFF,
            fill.reserved_0,
            fill.start_address,
            fill.size,
            fill.fill_pattern,
            fill.reserved_1
        )

    def _lower_copy(self, copy: vpu_job_pb2.VpuCmdCopyBuffer) -> bytes:
        return struct.pack(
            '<HH I Q I I',
            copy.header.type & 0xFFFF,
            copy.header.size & 0xFFFF,
            copy.reserved_0,
            copy.desc_start_offset,
            copy.desc_count,
            copy.reserved_1
        )

    def _lower_inference_execute(self, inf: vpu_job_pb2.VpuCmdInferenceExecute) -> bytes:
        return struct.pack(
            '<HH I Q Q I I',
            inf.header.type & 0xFFFF,
            inf.header.size & 0xFFFF,
            inf.reserved_0,
            inf.inference_id,
            inf.host_mapped_inference.address,
            inf.host_mapped_inference.width,
            inf.host_mapped_inference.reserved_0
        )

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 lower_vpu_job.py <vpu_job.pb> [output.json]")
        print("\nConverts Protobuf VPU job back to JSON format.")
        sys.exit(1)

    pb_path = sys.argv[1]

    if len(sys.argv) >= 3:
        output_path = sys.argv[2]
    else:
        output_path = Path(pb_path).stem + '_lowered.json'

    try:
        lowerer = VpuJobLowerer(pb_path)
        job = lowerer.lower()

        # Convert back to JSON format
        json_data = {
            'vpuFd': job.vpu_fd,
            'cmdq_id': job.cmdq_id,
            'buffers_ptr': f"0x{job.buffers_ptr:x}",
            'buffer_count': job.buffer_count,
            'commands_offset': job.commands_offset,
            'preempt_buffer_index': job.preempt_buffer_index,
            'buffers': []
        }

        for buf in job.buffers:
            json_buffer = {
                'index': buf.index,
                'handle': buf.handle,
                'vpu_addr': f"0x{buf.vpu_addr:x}",
                'size': buf.size,
                'mmap_offset': buf.mmap_offset,
                'flags': buf.flags,
                'data': buf.data.hex()
            }
            json_data['buffers'].append(json_buffer)

        with open(output_path, 'w') as f:
            import json
            json.dump(json_data, f, indent=2)

        print(f"Successfully lowered {pb_path} -> {output_path}")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
