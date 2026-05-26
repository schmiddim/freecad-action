FROM condaforge/miniforge3:latest AS builder

# Note: Alpine Linux is not used because FreeCAD is not available in Alpine repos
# FreeCAD requires conda-forge or Debian/Ubuntu packages
# This multi-stage build minimizes the final image size (~600MB instead of ~2GB)

# Install FreeCAD and dependencies into a separate environment
RUN mamba create -n freecad -y --quiet \
        python=3.12 \
        freecad \
        pyyaml \
        jinja2 \
        trimesh \
        matplotlib \
        scipy \
        pillow \
    && mamba clean -afy

# --- Runtime stage: only the conda environment, no package manager overhead ---
FROM debian:bookworm-slim

# OCI Labels for GHCR package linking
LABEL org.opencontainers.image.source="https://github.com/schmiddim/freecad-action"
LABEL org.opencontainers.image.description="FreeCAD export container for CAD Gallery"
LABEL org.opencontainers.image.licenses="MIT"

# Copy the conda environment from builder
COPY --from=builder /opt/conda/envs/freecad /opt/freecad

# Add required runtime libraries and OpenSCAD for fast thumbnail rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libgl1-mesa-dri \
        libgl1-mesa-glx \
        libglib2.0-0 \
        libxmu6 \
        libxi6 \
        libxrender1 \
        libxrandr2 \
        openscad \
        xvfb \
        xauth \
        mesa-utils \
        locales \
    && rm -rf /var/lib/apt/lists/* \
    && echo "en_US.UTF-8 UTF-8" > /etc/locale.gen \
    && locale-gen

ENV PATH="/opt/freecad/bin:$PATH" \
    LD_LIBRARY_PATH="/opt/freecad/lib:$LD_LIBRARY_PATH" \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8

WORKDIR /workspace

ENTRYPOINT ["freecadcmd"]
