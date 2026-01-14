#!/usr/bin/env python3
"""
Demo script to parse VPU command buffer without protobuf compilation.
Shows how the binary lifting works step by step.
"""

import struct
import json
import sys

# Constants from firmware API
VPU_CONTEXT_SAVE_AREA_SIZE = 64
VPU_CMD_HEADER_SIZE = 4  # uint16_t type + uint16_t size

# Command types mapping
VPU_CMD_TYPE = {
    0x0000: ('UNKNOWN', 'Unknown command'),
    0x0001: ('NOP', 'No operation'),
    0x0100: ('TIMESTAMP', 'Query timestamp'),
    0x0101: ('FENCE_WAIT', 'Wait for fence'),
    0x0102: ('FENCE_SIGNAL', 'Signal fence'),
    0x0103: ('BARRIER', 'Memory barrier'),
    0x0104: ('METRIC_QUERY_BEGIN', 'Start metric query'),
    0x0105: ('METRIC_QUERY_END', 'End metric query'),
    0x0202: ('MEMORY_FILL', 'Fill memory with pattern'),
    0x0302: ('COPY', 'Copy memory'),
    0x0306: ('INFERENCE_EXECUTE', 'Execute inference'),
}

def parse_hex_string(hex_str: str) -> bytes:
    """Convert hex string to bytes."""
    return bytes.fromhex(hex_str.strip())

def print_section(title: str, data: bytes, max_show: int = 64):
    """Print a section of memory in a nice format."""
    print(f"\n{title}")
    print("=" * 60)
    print(f"Length: {len(data)} bytes")
    print(f"Raw hex: {data[:max_show].hex()}")
    if len(data) > max_show:
        print(f"         ... ({len(data) - max_show} more bytes)")

    # Try to interpret as common types
    if len(data) >= 8:
        print(f"As uint64: {struct.unpack('<Q', data[:8])[0]:#016x}")

def parse_cmd_buffer_header(buffer_data: bytes, offset: int = 128):
    """Parse vpu_cmd_buffer_header at given offset."""
    header_offset = offset
    if len(buffer_data) < header_offset + 64:
        print(f"Buffer too small for header at offset {header_offset}")
        return None

    header_data = buffer_data[header_offset:header_offset + 64]

    print("\n" + "="*60)
    print("COMMAND BUFFER HEADER")
    print("="*60)

    cmd_buffer_size = struct.unpack('<I', header_data[0:4])[0]
    cmd_offset = struct.unpack('<I', header_data[4:8])[0]
    api_version = struct.unpack('<I', header_data[8:12])[0]
    reserved_0 = struct.unpack('<I', header_data[12:16])[0]
    descriptor_heap_base = struct.unpack('<Q', header_data[16:24])[0]
    submission_timestamp = struct.unpack('<Q', header_data[24:32])[0]
    fence_heap_base = struct.unpack('<Q', header_data[32:40])[0]
    context_save_area = struct.unpack('<Q', header_data[40:48])[0]

    print(f"cmd_buffer_size:          {cmd_buffer_size} bytes")
    print(f"cmd_offset:               {cmd_offset} bytes (from header)")
    print(f"api_version:               0x{api_version:#08x} (major={api_version >> 16}, minor={api_version & 0xFFFF})")
    print(f"descriptor_heap_base:       0x{descriptor_heap_base:#018x}")
    print(f"submission_timestamp:       {submission_timestamp} µs")
    print(f"fence_heap_base_address:   0x{fence_heap_base:#018x}")
    print(f"context_save_area_address:  0x{context_save_area:#018x}")

    return {
        'cmd_buffer_size': cmd_buffer_size,
        'cmd_offset': cmd_offset,
        'api_version': api_version,
        'descriptor_heap_base': descriptor_heap_base,
        'submission_timestamp': submission_timestamp,
    }

def parse_commands(buffer_data: bytes, start_offset: int, size: int):
    """Parse command list from buffer."""
    current_offset = start_offset
    end_offset = start_offset + size

    print(f"\n" + "="*60)
    print(f"COMMAND LIST ({size} bytes at offset 0x{start_offset:x})")
    print("="*60)

    cmd_count = 0
    while current_offset < end_offset:
        if current_offset + VPU_CMD_HEADER_SIZE > len(buffer_data):
            print(f"\n⚠ Truncated at offset 0x{current_offset:x}")
            break

        cmd_type, cmd_size = struct.unpack('<HH',
                                        buffer_data[current_offset:current_offset + VPU_CMD_HEADER_SIZE])

        cmd_name, description = VPU_CMD_TYPE.get(cmd_type, (f'UNKNOWN_{cmd_type:04x}', 'Unknown command'))

        if current_offset + cmd_size > len(buffer_data):
            print(f"\n⚠ Command {cmd_name} truncated at offset 0x{current_offset:x}")
            print(f"   Expected {cmd_size} bytes, only {len(buffer_data) - current_offset} available")
            break

        cmd_data = buffer_data[current_offset:current_offset + cmd_size]

        print(f"\n--- Command {cmd_count} ---")
        print(f"Type:        0x{cmd_type:04x} - {cmd_name}")
        print(f"Description:  {description}")
        print(f"Size:        {cmd_size} bytes")
        print(f"Offset:      0x{current_offset:x}")
        print(f"Raw data:    {cmd_data[:min(32, len(cmd_data))].hex()}")

        # Parse specific command fields
        if cmd_type in (0x0101, 0x0102):  # FENCE
            if len(cmd_data) >= 24:
                reserved = struct.unpack('<I', cmd_data[4:8])[0]
                fence_offset = struct.unpack('<Q', cmd_data[8:16])[0]
                fence_value = struct.unpack('<Q', cmd_data[16:24])[0]
                print(f"Fence offset:  0x{fence_offset:#018x}")
                print(f"Fence value:   {fence_value}")
        elif cmd_type == 0x0306:  # INFERENCE_EXECUTE
            if len(cmd_data) >= 32:
                reserved = struct.unpack('<I', cmd_data[4:8])[0]
                inference_id = struct.unpack('<Q', cmd_data[8:16])[0]
                addr = struct.unpack('<Q', cmd_data[16:24])[0]
                width = struct.unpack('<I', cmd_data[24:28])[0]
                print(f"Inference ID:  0x{inference_id:#018x}")
                print(f"Host mapped:   0x{addr:#018x}")
                print(f"Width:         {width}")
        elif cmd_type == 0x0202:  # MEMORY_FILL
            if len(cmd_data) >= 32:
                reserved = struct.unpack('<I', cmd_data[4:8])[0]
                start_addr = struct.unpack('<Q', cmd_data[8:16])[0]
                fill_size = struct.unpack('<Q', cmd_data[16:24])[0]
                pattern = struct.unpack('<I', cmd_data[24:28])[0]
                print(f"Start address: 0x{start_addr:#018x}")
                print(f"Fill size:     {fill_size} bytes")
                print(f"Pattern:        0x{pattern:08x}")

        cmd_count += 1
        current_offset += cmd_size

    return cmd_count

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 demo_parse_vpu_job.py <vpu_job.json>")
        print("\nThis script demonstrates parsing VPU job binaries without protobuf compilation.")
        sys.exit(1)

    json_path = sys.argv[1]

    try:
        with open(json_path, 'r') as f:
            job_data = json.load(f)
    except Exception as e:
        print(f"Error loading JSON: {e}")
        sys.exit(1)

    print("="*60)
    print("VPU JOB ANALYSIS")
    print("="*60)
    print(f"File:         {json_path}")
    print(f"VPU FD:       {job_data.get('vpuFd')}")
    print(f"CmdQ ID:      {job_data.get('cmdq_id')}")
    print(f"Buffer count:  {job_data.get('buffer_count')}")

    if job_data.get('buffer_count', 0) == 0:
        print("\nNo buffers found in job!")
        return

    # Parse first buffer (command buffer)
    first_buf = job_data['buffers'][0]
    buffer_data = parse_hex_string(first_buf['data'])

    print(f"\n--- BUFFER 0 (Command Buffer) ---")
    print(f"Handle:      {first_buf['handle']}")
    print(f"Size:        {first_buf['size']} bytes")
    print(f"VPU Addr:    0x{first_buf.get('vpu_addr', '0')}")
    print(f"Mmap Offset: {first_buf['mmap_offset']}")

    # Parse command buffer structure
    print_section("CONTEXT SAVE AREA (first 64 bytes)", buffer_data[0:64])

    print_section("FENCE VALUE (next 8 bytes)", buffer_data[64:72])

    print_section("RESERVED (next 56 bytes)", buffer_data[72:128])

    # Parse header
    header_info = parse_cmd_buffer_header(buffer_data, offset=128)

    if header_info:
        # Parse commands
        cmd_list_offset = 128 + header_info['cmd_offset']
        parse_commands(buffer_data, cmd_list_offset, header_info['cmd_buffer_size'] - header_info['cmd_offset'])

    print("\n" + "="*60)
    print("ANYSIS COMPLETE")
    print("="*60)

if __name__ == '__main__':
    main()
