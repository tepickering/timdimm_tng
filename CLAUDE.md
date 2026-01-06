# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

timdimm_tng is a Python package for running portable atmospheric seeing monitors at SAAO (South African Astronomical Observatory) and MMTO (Multiple Mirror Telescope Observatory). It supports DIMM (Differential Image Motion Monitor) measurements via INDI protocol, SER video file capture/analysis, and FASS (Full Aperture Scintillation Sensing) turbulence profiling.

## Common Commands

```bash
# Environment setup (conda)
conda env create -f timdimm_env.yml
conda activate timdimm

# Install package in development mode
pip install -e .
pip install -e .[dev]      # With dev dependencies
pip install -e .[sdbus]    # With D-Bus support

# Run tests
pytest src/timdimm_tng/tests

# Code style check
flake8 src/timdimm_tng --count --max-line-length=132

# Or via tox
tox -e codestyle
```

## Console Entry Points

After installation, these commands are available:
- `timdimm` - Main GUI
- `timdimm_analyze` / `hdimm_analyze` - Analyze DIMM data from SER files
- `vid_capture` - Capture video via INDI
- `oxwagon` - OxWagon enclosure control
- `check_wx` - Check weather conditions
- `salt_wx`, `saao_io`, `gfz_wx`, `lco_wx`, `monet_wx` - Individual weather station queries

## Architecture

### Source Layout
```
src/timdimm_tng/
├── analyze_cube.py    # Core DIMM seeing calculations and image analysis
├── vid_capture.py     # INDI camera video capture
├── ox_wagon.py        # Serial protocol for OxWagon enclosure control
├── indi.py            # Wrapper around INDI CLI tools (indi_getprop/indi_setprop)
├── ser.py             # SER video file format parser
├── scheduler.py       # INDI/Ekos scheduler XML generation
├── timdimm_gui.py     # GUI entry point
├── locations.py       # MMTO and SAAO EarthLocation definitions
├── dbus/              # D-Bus interfaces for KDE/Ekos integration
├── wx/                # Weather monitoring (SALT, SAAO IO, GFZ, LCOGT, MONet)
├── templates/         # Ekos scheduler XML templates (.esl, .esq)
└── data/              # Star list catalogs (.ecsv)
```

### Key Modules

- **analyze_cube.py**: Image processing using scikit-image and photutils; calculates seeing via image moments and DIMM algorithms
- **ox_wagon.py**: Implements serial protocol to control dome enclosure (open/close/status)
- **wx/check_wx.py**: Aggregates weather from multiple sources (SALT + SAAO IO) to determine if conditions are safe
- **indi.py**: Uses subprocess to call INDI command-line tools; provides Pythonic wrapper
- **scheduler.py**: Generates Ekos scheduler jobs from star list catalogs using XML templates

### Data Flow
```
Camera/Enclosure/Weather → INDI/Serial/HTTP APIs → Python wrappers → Analysis/Scheduling → D-Bus/GUI
```

## Code Style

- Line length: 132 characters (configured in pyproject.toml and flake8)
- Python 3.9+ required (conda env uses 3.11+)
- Uses astropy units throughout for physical quantities
- Version managed automatically via setuptools_scm

## Observatory Locations

Defined in `locations.py`:
- MMTO: Arizona (-110:53:04.4, 31:41:19.6, 2600m)
- SAAO: South Africa (20:48:38.4, -32:22:33.6, 1798m)
