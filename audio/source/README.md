# Local Audio Library

Place the source WAV library in this directory:

```text
audio/source/
├── beds/
└── gestures/
```

The WAV files are intentionally excluded from Git because they are large licensed media assets. Their permanent IDs, expected relative paths, and technical metadata are recorded in `config/generator.xml`.

To validate a local checkout, restore the files at those exact paths and run:

```bash
hpr-audio validate
```

