# Combined image licensing and attribution

`Dockerfile.combined` creates a free, non-monetized evaluation image containing
separately licensed programs. The image is not endorsed by the WanGP authors.

## Components

- **nodetool-wan2gp**: AGPL-3.0-or-later. The corresponding source is this
  repository at the revision used as the Docker build context. In the image
  that is the entrypoint, the healthcheck and the token proxy.
- **WanGP / Wan2GP**: WanGP Community License 2.0, pinned by `WANGP_COMMIT`.
  Its complete source, `LICENSE.txt`, notices, and bundled
  `docs/third_party_licenses` directory remain at `/opt/Wan2GP` in the image.
  No WanGP source modifications are made by this Dockerfile.
- **mmgp**: vendored by WanGP in `/opt/Wan2GP/mmgp` and licensed under the
  WanGP Community License 2.0, as `/opt/Wan2GP/mmgp/LICENSE.md` states.
- **Python dependencies**: PyTorch and the packages in WanGP's
  `requirements.txt`, installed from their package indexes with their own
  licenses and metadata under `/opt/wan2gp-venv`.
- **Models, weights, datasets, and runtime downloads**: not included in the
  image. Each retains its own license, which the user must review before use or
  redistribution.

No NodeTool code is in the image. NodeTool connects to it over the network.

## Use restriction

This combined image is for free, non-monetized use. Do not sell it,
white-label it, embed it in a paid product, or provide paid, sponsored,
ad-supported, SaaS, hosted, managed, API, OEM, marketplace, or otherwise
monetized access without all necessary written licenses.

Preserve this document and every license and notice included in the image when
redistributing it. If you change WanGP, clearly describe the modification and
its date as required by the WanGP Community License 2.0.
