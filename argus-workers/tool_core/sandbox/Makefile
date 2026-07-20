# tool_core/sandbox/Makefile
# Build and push helpers for the sandbox Docker image.

IMAGE_NAME ?= argus-sandbox
IMAGE_TAG ?= latest
REGISTRY ?= ghcr.io/argus-org

.PHONY: build push clean test

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

tag:
	docker tag $(IMAGE_NAME):$(IMAGE_TAG) $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

push: tag
	docker push $(REGISTRY)/$(IMAGE_NAME):$(IMAGE_TAG)

test:
	pytest ../../tests/test_sandbox.py -v --timeout=60

# Build and run a quick smoke test
smoke: build
	@echo "Running smoke test..."
	@echo '{"command": ["echo", "hello"], "timeout": 10}' | docker run --rm -i $(IMAGE_NAME):$(IMAGE_TAG)
	@echo "Smoke test complete"

clean:
	-docker rmi $(IMAGE_NAME):$(IMAGE_TAG) 2>/dev/null || true
