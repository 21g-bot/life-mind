# Character assets are local-only

This directory is intentionally ignored by Git except for this file.

Put private character packs here, for example:

```text
assets/character/my-pet/
├── manifest.json
├── idle/frame_000.png
└── blink/frame_000.png
```

Run a local pack with:

```powershell
python -B run_pet.py --asset assets/character/my-pet
```

Do not force-add artwork unless you own it and explicitly want to publish it.
Fresh public checkouts use the generated, non-human demo character in
`.cache/demo-character/`.
