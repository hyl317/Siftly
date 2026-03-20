# LOG-to-Rec.709 LUT Files

This directory contains 3D LUT (.cube) files used to convert LOG camera footage
to standard Rec.709 color before uploading to Twelve Labs for AI analysis.

Use **3D LUTs** with **33-point** grid size (33x33x33). The app uses ffmpeg's
`lut3d` filter, so 1D LUTs are not supported.

## Bundled LUTs (freely redistributable)

| File | Profile | Source |
|---|---|---|
| `dlog_to_rec709.cube` | DJI D-Log | DJI (Mavic 3) |
| `dlogm_to_rec709.cube` | DJI D-Log M | DJI (Mavic 3 Pro) |
| `vlog_to_rec709.cube` | Panasonic V-Log | Panasonic VariCam LUT Library |
| `flog_to_rec709.cube` | Fujifilm F-Log | Fujifilm X-T5 LUT Pack |
| `flog2_to_rec709.cube` | Fujifilm F-Log2 | Fujifilm X-T5 LUT Pack |
| `logc3_to_rec709.cube` | ARRI LogC3 | ARRI LogC3 LUT Package |
| `logc4_to_rec709.cube` | ARRI LogC4 | ARRI LogC4 LUT Package |

## LUTs you need to download yourself

These manufacturers restrict redistribution. Download the official 3D .cube
file (33-point grid) and either:
- Use the in-app "I'll provide the LUT" prompt to install it automatically, or
- Place it in this directory with the expected filename listed below.

### Sony S-Log3 → `slog3_to_rec709.cube`
1. Go to https://pro.sony/ue_US/technology/professional-video-lut-look-up-table
2. Download the "S-Log3 SGamut3.Cine to s709" 3D LUT (33-point)

### Canon C-Log2 → `clog2_to_rec709.cube`
1. Go to https://hk.canon/en/support/0200583202 (or your regional Canon site)
2. Download "Canon Lookup Table" zip
3. Find the 33-grid 3D LUT: `CinemaGamut_CanonLog2-to-BT709_WideDR_33_FF_Ver.2.0.cube`

### Canon C-Log3 → `clog3_to_rec709.cube`
1. Same download as above, or https://hk.canon/en/support/0200747702
2. Find the 33-grid 3D LUT for C-Log3 to BT.709

### Nikon N-Log → `nlog_to_rec709.cube`
1. Go to https://downloadcenter.nikonimglib.com/en/products/520/N-Log_3D_LUT.html
2. Download and run the installer for your platform
3. Find `N-Log_BT2020_to_REC709_BT1886_size_33.cube`
