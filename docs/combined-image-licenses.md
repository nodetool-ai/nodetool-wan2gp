# Combined image licensing and attribution

`Dockerfile.combined` creates a free, non-monetized evaluation image containing
separately licensed programs. The image is not endorsed by the WanGP authors.

## Components

- **nodetool-wan2gp**: AGPL-3.0-or-later. The corresponding source is this
  repository at the revision used as the Docker build context.
- **NodeTool**: AGPL-3.0-or-later. Its source and notices are provided by the
  `CORE_IMAGE` named in the build provenance.
- **WanGP / Wan2GP**: WanGP Community License 2.0, pinned by
  `WANGP_COMMIT`. Its complete source, license, notices, and bundled
  `docs/third_party_licenses` directory remain at `/opt/Wan2GP` in the image.
  No WanGP source modifications are made by this Dockerfile.
- **NodeTool worker adapter support**: pinned by `NODETOOL_CORE_COMMIT`. The
  source revision is fetched from the public nodetool-core repository during
  the build and is not modified in the image.
- **mmgp**: non-commercial use with attribution, pinned by `MMGP_COMMIT` and
  installed at the version required by WanGP. Its license and attribution are
  copied to `/opt/licenses/mmgp`.
- **Models, weights, datasets, and runtime downloads**: not included in the
  image. Each retains its own license, which the user must review before use or
  redistribution.

## Use restriction

This combined image is for free, non-monetized use. Do not sell it,
white-label it, embed it in a paid product, or provide paid, sponsored,
ad-supported, SaaS, hosted, managed, API, OEM, marketplace, or otherwise
monetized access without all necessary written licenses.

Preserve this document and every license and notice included in the image when
redistributing it. If you change WanGP, clearly describe the modification and
its date as required by the WanGP Community License 2.0.
