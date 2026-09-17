# Model storage

Model binaries are intentionally excluded from Git.

```text
models/
└── detection/
    ├── yolo11n.pt
    ├── yolo11s.pt
    └── yolo11m.pt
```

The active weight path is configured by `detection.model` in `config.yaml`.
Ultralytics may download a missing standard weight when given a model name, but keeping explicit
local weights here makes runtime behavior reproducible.
