# Custom note skins

The built-in skins (`arrows`, `circles`, `bars`) are drawn in code, so they stay crisp at any resolution. To use your own art for a skin, make a folder named after it and drop PNGs in:

```
assets/skins/arrows/
    note_left.png
    note_down.png
    note_up.png
    note_right.png
    note_center.png              # middle lane of 5K / 7K
    receptor_left.png            # idle receptor (same names for every direction)
    receptor_left_pressed.png    # while the key is held
```

* Any file you leave out falls back to the procedural sprite, so you can replace just the notes and keep the receptors.
* Images are scaled to fit the lane width (Settings → Lane width), keeping their aspect ratio. Square images about 256×256 work well.
* Lane directions per key count are set in `data/theme.json` (`lane_directions`), and the colours there are used for effects.
