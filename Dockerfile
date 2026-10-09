# Layer the Wan2GP node pack on top of the core worker image.
#
# Rationale: this pack adds three pure-Python modules and two small dependencies
# on top of nodetool-core. `python -m nodetool.worker` comes from the inherited
# nodetool-core dependency, so EXPOSE 7777, HEALTHCHECK, and CMD are all
# inherited from the core image.
#
# No GPU strategy, because this image runs no model. Wan2GP itself stays outside
# the image: it is proprietary and its memory manager `mmgp` is
# non-commercial-only, so the pack only speaks MCP over HTTP to a Wan2GP the
# user runs. See NOTICE.md. Point the container at that server with
# WAN2GP_MCP_URL, and note that 127.0.0.1 inside a container is the container.
#
# CORE_IMAGE: the published NodeTool Python worker image
#   (ghcr.io/nodetool-ai/nodetool-worker:<version>, built from nodetool-core's
#   Dockerfile), or a local build of that Dockerfile. It is micromamba-based:
#   Python lives in $VIRTUAL_ENV (/opt/conda) and uv is on PATH. Do not use
#   ghcr.io/nodetool-ai/nodetool, which is the TypeScript server image.
ARG CORE_IMAGE=ghcr.io/nodetool-ai/nodetool-worker:0.8.1
FROM ${CORE_IMAGE}

USER root

# Install this pack from the build context into the worker's environment.
COPY . /tmp/nodetool-wan2gp
RUN test -x "$VIRTUAL_ENV/bin/python" \
    && uv pip install \
        --python "$VIRTUAL_ENV" \
        --index-url https://pypi.org/simple \
        /tmp/nodetool-wan2gp \
    && rm -rf /tmp/nodetool-wan2gp /root/.cache/uv /root/.cache/pip /tmp/* /var/tmp/*

# EXPOSE 7777, HEALTHCHECK, and CMD are all inherited from the core image.
