# Figure fonts

The figures use Inter. The [GPUI Kit web gallery](https://github.com/longbridge/gpui-kit/blob/4c7f1350331562436df868c55ac33bebc4c6406c/crates/story-web/src/lib.rs#L30-L34) uses the same font family.
The package includes regular and semibold files. It loads these files before it
draws text. No font download or system installation is necessary.

The internal family name is `Inter Variable`. These files are static instances
of the variable font. The regular weight is 400. The semibold weight is 600.
Both files use an optical size of 14. Optical size adjusts letter shapes for
the text size.

## Source and license

Source: [Inter version 4.001](https://github.com/rsms/inter/blob/353b61b9f4430d5f420d56605a6e7993e0941470/docs/font-files/InterVariable.ttf).
Source commit: `353b61b9f4430d5f420d56605a6e7993e0941470`.

Copyright (c) 2016 The Inter Project Authors.
The font files use the [SIL Open Font License 1.1](OFL.txt).
The project's MIT License does not replace this font license.

## Make the font files again

Prerequisites: `curl`, `uv`, and Python 3.11 or later.
Run the commands in a temporary directory.

1. Get the source font:

   ```bash
   curl -fL https://raw.githubusercontent.com/rsms/inter/353b61b9f4430d5f420d56605a6e7993e0941470/docs/font-files/InterVariable.ttf -o InterVariable.ttf
   ```

2. Make the regular file:

   ```bash
   uv run --with fonttools==4.63.0 python -m fontTools.varLib.instancer InterVariable.ttf opsz=14 wght=400 --update-name-table --no-recalc-timestamp -o Inter-Regular.ttf
   ```

3. Make the semibold file:

   ```bash
   uv run --with fonttools==4.63.0 python -m fontTools.varLib.instancer InterVariable.ttf opsz=14 wght=600 --update-name-table --no-recalc-timestamp -o Inter-SemiBold.ttf
   ```

4. Check the SHA-256 file hashes:

   ```bash
   shasum -a 256 InterVariable.ttf Inter-Regular.ttf Inter-SemiBold.ttf
   ```

| File | SHA-256 |
| --- | --- |
| `InterVariable.ttf` | `4989b125924991b90d05b2d16e0e388c48f7d5bb8b30539bbf9c755278d0ccaf` |
| `Inter-Regular.ttf` | `a2781df42d8ec0e76ab11f1287e1114f0e0f2692879a765654b6563ce909a172` |
| `Inter-SemiBold.ttf` | `4dd6b0dfcf1333bdb9ced889731cf66ae7740084d9c23a948ee4fd194b0cd428` |

FontTools is necessary only to make these files again.
The forecast does not use FontTools to prepare fonts at runtime.
