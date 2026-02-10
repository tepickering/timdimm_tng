# timdimm_tng -- Software for running the SAAO's timDIMM and MMTO portable seeing monitor

This package provides a clean start to support the updated SAAO timDIMM and the MMTO portable seeing monitor.
It supports taking DIMM measurements via the INDI protocol. The data is taken by saving video stream data
into SER files and then analyzing them to extract the seeing and other parameters. Full turbulence profile
measurements are prototyped here as well using the Full Aperture Scintillation Sensing (FASS) approach.
