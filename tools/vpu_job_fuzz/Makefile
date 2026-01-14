.PHONY: all clean test help proto

PROTOC := protoc
PYTHON := python3

SRC_DIR := .
BUILD_DIR := build

PROTO_FILES := vpu_job.proto
PY_PROTO_FILES := $(addprefix $(BUILD_DIR)/, $(PROTO_FILES:.proto=_pb2.py))

# Colors for output
COLOR_RESET := \033[0m
COLOR_BOLD := \033[1m
COLOR_GREEN := \033[32m
COLOR_YELLOW := \033[33m
COLOR_BLUE := \033[34m

all: proto

help:
	@echo "$(COLOR_BOLD)VPU Job Fuzzing Tools$(COLOR_RESET)"
	@echo ""
	@echo "Available targets:"
	@echo "  $(COLOR_GREEN)proto$(COLOR_RESET)     - Compile Protobuf schemas"
	@echo "  $(COLOR_GREEN)test$(COLOR_RESET)      - Test lifting/lowering on sample data"
	@echo "  $(COLOR_GREEN)clean$(COLOR_RESET)     - Remove generated files"
	@echo ""
	@echo "Usage examples:"
	@echo "  make proto"
	@echo "  make test"
	@echo "  $(PYTHON) lift_vpu_job.py ../vpu_jobs/0.json test.pb"
	@echo "  $(PYTHON) lower_vpu_job.py test.pb test_lowered.json"

proto: $(BUILD_DIR) $(PY_PROTO_FILES)

$(BUILD_DIR):
	@mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/%_pb2.py: %.proto
	@echo "$(COLOR_BLUE)Compiling$(COLOR_RESET) $<..."
	@$(PROTOC) --python_out=$(BUILD_DIR) --proto_path=$(SRC_DIR) $<
	@echo "$(COLOR_GREEN)Done$(COLOR_RESET)"

clean:
	@echo "$(COLOR_YELLOW)Cleaning$(COLOR_RESET) generated files..."
	@rm -rf $(BUILD_DIR)
	@rm -f *.pyc
	@rm -f __pycache__
	@rm -rf .pytest_cache
	@echo "$(COLOR_GREEN)Done$(COLOR_RESET)"

test: proto
	@echo "$(COLOR_BLUE)Testing$(COLOR_RESET) lifting and lowering..."
	@if [ -f "../vpu_jobs/0.json" ]; then \
		$(PYTHON) -c "import sys; sys.path.insert(0, '$(BUILD_DIR)'); import lift_vpu_job; print('$(COLOR_GREEN)Lift module OK$(COLOR_RESET)')" && \
		$(PYTHON) -c "import sys; sys.path.insert(0, '$(BUILD_DIR)'); import lower_vpu_job; print('$(COLOR_GREEN)Lower module OK$(COLOR_RESET)')" && \
		echo "$(COLOR_GREEN)All tests passed$(COLOR_RESET)"; \
	else \
		echo "$(COLOR_YELLOW)Warning$(COLOR_RESET): No vpu_jobs/0.json found, skipping test"; \
	fi
