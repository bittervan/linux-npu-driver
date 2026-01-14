#!/usr/bin/env python3
"""
VPU Job Fuzzing Test Suite
Tests lifting and lowering of all captured VPU jobs.
"""

import sys
import os
import json
from pathlib import Path
import struct
from typing import Dict, List, Tuple
import time

# Add build directory to path for protobuf import
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir / 'build'))

try:
    import vpu_job_pb2
except ImportError:
    print("Error: vpu_job_pb2 not found. Please compile vpu_job.proto first:")
    print("  make proto")
    sys.exit(1)

# Import lift and lower functions
sys.path.insert(0, str(script_dir))

# Constants
VPU_HOST_PARSED_INFERENCE_SIZE = 384
VPU_CMD_HEADER_SIZE = 4

# Command type mapping
VPU_CMD_MAP = {
    0x0000: ('UNKNOWN', 'unknown'),
    0x0001: ('NOP', 'nop'),
    0x0100: ('TIMESTAMP', 'timestamp'),
    0x0101: ('FENCE_WAIT', 'fence'),
    0x0102: ('FENCE_SIGNAL', 'fence'),
    0x0103: ('BARRIER', 'barrier'),
    0x0202: ('MEMORY_FILL', 'memory_fill'),
    0x0302: ('COPY', 'copy'),
    0x0306: ('INFERENCE_EXECUTE', 'inference_execute'),
    0x0606: ('INFERENCE_EXECUTE', 'inference_execute'),  # Corrected from 0x0306
}

class VpuJobTester:
    """Test VPU job lifting and lowering."""

    def __init__(self, vpu_jobs_dir: str):
        # Convert to absolute path
        if vpu_jobs_dir.startswith('/') or (len(vpu_jobs_dir) > 1 and vpu_jobs_dir[1] == ':'):
            # Already absolute or Windows path
            self.vpu_jobs_dir = Path(vpu_jobs_dir)
        else:
            # Relative path, resolve from script directory
            self.vpu_jobs_dir = (Path(__file__).parent / vpu_jobs_dir).resolve()

        if not self.vpu_jobs_dir.exists():
            raise FileNotFoundError(f"vpu_jobs directory not found at {self.vpu_jobs_dir}")

        self.results = []

    def test_all_jobs(self, max_jobs = None, start_idx: int = 0) -> None:
        """Test all VPU job files."""
        job_files = sorted(self.vpu_jobs_dir.glob('*.json'))

        if max_jobs:
            end_idx = min(start_idx + max_jobs, len(job_files))
            job_files = job_files[start_idx:end_idx]

        print(f"\n=== VPU Job Fuzzing Test Suite ===")
        print(f"Testing {len(job_files)} jobs (files {start_idx} to {start_idx + len(job_files) - 1})\n")

        for idx, job_file in enumerate(job_files, 1):
            print(f"[{idx}] Testing {job_file.name}...", end=' ', flush=True)
            result = self.test_job(job_file)
            self.results.append(result)
            status = "PASS" if result['success'] else "FAIL"
            print(f"\r[{idx}] {status} {job_file.name}")

        self.print_summary()

    def test_job(self, job_file: Path) -> Dict:
        """Test a single VPU job file."""
        result = {
            'file': str(job_file),
            'success': False,
            'errors': [],
            'buffer_count': 0,
            'command_count': 0,
            'has_inference': False,
            'has_copy': False,
            'has_commands': [],
            'parsed_hpi': False,
            'roundtrip_ok': False,
            'parse_time': 0.0,
        }

        start_time = time.time()

        try:
            # Load JSON
            with open(job_file, 'r') as f:
                job_data = json.load(f)

            result['buffer_count'] = job_data.get('buffer_count', 0)

            # Parse commands from command buffer
            if result['buffer_count'] > 0:
                first_buffer = job_data.get('buffers', [{}])[0]
                buffer0_data = bytes.fromhex(first_buffer.get('data', ''))

                # DEBUG: Print buffer info
                if self.results:  # Only for first job
                    file_idx = len(self.results)
                    if file_idx == 1:  # Job 153
                        print(f"DEBUG: Buffer 0 size={len(buffer0_data)}")
                        print(f"DEBUG: First 100 bytes (hex): {buffer0_data[:100].hex()}")

                # Detect all commands in buffer
                commands_info = self._detect_commands(buffer0_data)
                result['command_count'] = len(commands_info)
                result['has_commands'] = [c['name'] for c in commands_info]

                # DEBUG: Print commands found
                if self.results and len(self.results) == 1:
                    print(f"DEBUG: Commands detected in Buffer 0: {len(commands_info)}")
                    for c in commands_info:
                        print(f"  - type=0x{c['type']:04x}, name={c['name']}, offset=0x{c['offset']:x}")

                if 'INFERENCE_EXECUTE' in result['has_commands']:
                    result['has_inference'] = True
                if 'COPY' in result['has_commands']:
                    result['has_copy'] = True

        except Exception as e:
            result['errors'].append(f"Processing failed: {e}")
            result['parse_time'] = time.time() - start_time

        return result

    def _detect_commands(self, buffer_data: bytes) -> List[Dict]:
        """Detect all commands in a buffer."""
        commands = []
        offset = 0

        while offset < len(buffer_data) - 4:
            # Try to read command header (type, size)
            try:
                cmd_type, cmd_size = struct.unpack('<HH', buffer_data[offset:offset + 4])
            except:
                print(f"DEBUG: Unpack failed at offset 0x{offset:x}")
                break

            if cmd_size == 0 or cmd_size > 512 or offset + cmd_size > len(buffer_data):
                break

            cmd_name = VPU_CMD_MAP.get(cmd_type, ('UNKNOWN', 'unknown'))
            commands.append({
                'type': cmd_type,
                'name': cmd_name[0],
                'size': cmd_size,
                'offset': offset,
            })

            offset += cmd_size

        return commands

    def print_summary(self):
        """Print test summary."""
        print(f"\n{'='*60}")
        print("Test Summary")
        print(f"{'='*60}")

        total = len(self.results)
        passed = sum(1 for r in self.results if r['success'])
        failed = total - passed

        print(f"Total tests: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Success rate: {passed/total*100:.1f}%")

        # Count different job types
        has_inference = sum(1 for r in self.results if r['has_inference'])
        has_copy = sum(1 for r in self.results if r['has_copy'])
        parsed_hpi = sum(1 for r in self.results if r['parsed_hpi'])

        print(f"\nJob Statistics:")
        print(f"  Jobs with INFERENCE_EXECUTE: {has_inference}")
        print(f"  Jobs with COPY command: {has_copy}")
        print(f"  Jobs with parsed Host Parsed Inference: {parsed_hpi}")

        # Count command types
        all_commands = []
        for r in self.results:
            all_commands.extend(r['has_commands'])

        from collections import Counter
        cmd_counter = Counter(all_commands)

        print(f"\nCommand frequency:")
        if cmd_counter:
            for cmd, count in cmd_counter.most_common():
                print(f"  {cmd}: {count}")
        else:
            print("  No commands detected")
        
        # Count unknown commands
        unknown_count = sum(1 for r in self.results 
                             for c in r['has_commands'] if c == 'UNKNOWN')
        if unknown_count > 0:
            print(f"  Unknown commands: {unknown_count}")

        # Average buffer counts
        avg_buffers = sum(r['buffer_count'] for r in self.results) / total if total > 0 else 0
        avg_commands = sum(r['command_count'] for r in self.results) / total if total > 0 else 0

        print(f"\nAverage per job:")
        print(f"  Buffers: {avg_buffers:.1f}")
        print(f"  Commands: {avg_commands:.1f}")

        # Show failures
        if failed > 0:
            print(f"\nFailed tests:")
            for r in self.results:
                if not r['success']:
                    print(f"  - {Path(r['file']).name}")
                    for err in r['errors']:
                        print(f"    {err}")

def main():
    # Get vpu_jobs directory (default to ../../vpu_jobs)
    vpu_jobs_dir = '../../vpu_jobs'
    max_jobs = None

    if len(sys.argv) > 1:
        vpu_jobs_dir = sys.argv[1]

    # Max jobs to test (optional)
    if len(sys.argv) > 2:
        try:
            max_jobs = int(sys.argv[2])
        except ValueError:
            max_jobs = None

    try:
        tester = VpuJobTester(vpu_jobs_dir)
        tester.test_all_jobs(max_jobs=max_jobs)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
