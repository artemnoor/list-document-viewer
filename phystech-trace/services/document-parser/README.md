# Document Parser service

This service packages the existing Python API from the repository's `backend/` directory. Its OCR, Docling, native Office parsing, provenance, page rendering, retry, and review behavior remains in the original implementation.

Run from the repository root with `python backend/server.py`. The Compose image uses this directory's Dockerfile and mounts persistent volumes for parser uploads and OCR models.

The API binds to loopback by default for the existing local viewer. Set `BIND_HOST=0.0.0.0` when running it in a container. `GET /health`, `GET /docs`, and `GET /openapi.json` expose service health and Swagger.
