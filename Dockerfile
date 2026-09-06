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
# CORE_IMAGE: the locally-built `nodetool-core:local`, or a published
#   ghcr.io/nodetool-ai/nodetool:<tag>.
ARG CORE_IMAGE=nodetool-core:local
FROM ${CORE_IMAGE}

USER root

# Install this pack from the build context on top of core.
COPY . /tmp/nodetool-wan2gp
RUN uv pip install \
        --python $VIRTUAL_ENV \
        --index-url https://pypi.org/simple \
        /tmp/nodetool-wan2gp \
    && rm -rf /tmp/nodetool-wan2gp /root/.cache/uv /root/.cache/pip /tmp/* /var/tmp/*

# EXPOSE 7777, HEALTHCHECK, and CMD are all inherited from the core image.
