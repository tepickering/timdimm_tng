import subprocess

import logging


class INDI_Device:
    """
    Wrapper for communicating with an INDI server via INDI's command-line tools

    Arguments
    ---------
    devname : str
        Name of the INDI device

    host : str (default: localhost)
        Hostname of the INDI server host computer

    port : int (default: 7624)
        Port the INDI server is using
    """

    def __init__(self, devname, host="localhost", port=7624, log=None):
        self.devname = devname
        self.host = host
        self.port = str(port)

        if log is None:
            self.log = logging.getLogger(f"{devname} at {host}:{port}")
            self.log.setLevel(logging.INFO)
        else:
            self.log = log

    def get_prop(self, property, key):
        """
        Use indi_getprop to get an INDI property

        Arguments
        ---------
        property : str
            INDI property of device to be queried

        key : str
            Which key of the property to query
        """
        cmd = ["indi_getprop", "-h", self.host, "-p", self.port]

        indi_str = f"{self.devname}.{property}.{key}"

        cmd.append(indi_str)

        try:
            p = subprocess.run(cmd, check=True, capture_output=True)
        except Exception as e:
            self.log.error(f"indi_getprop command failed: {e}")
            return e

        self.log.info(f"Get {indi_str} from {self.host}:{self.port}")

        value = p.stdout.decode().split("=")[1]

        return value

    def set_prop(self, property, key, value=None):
        """
        Use indi_setprop to set an INDI property

        Arguments
        ---------
        property : str
            INDI property of device to be configured

        key : str
            Which key of the property to configure

        value : str or float
            New value of the property key
        """
        cmd = ["indi_setprop", "-h", self.host, "-p", self.port]

        if value is not None:
            indi_str = f"{self.devname}.{property}.{key}={value}"
        else:
            indi_str = f"{self.devname}.{property}.{key}"

        cmd.append(indi_str)

        try:
            p = subprocess.run(cmd, check=True, capture_output=True)
        except Exception as e:
            self.log.error(f"indi_setprop command failed: {e}")
            return e

        self.log.info(f"Set {indi_str} on {self.host}:{self.port}")

        if len(p.stdout) > 0:
            self.log.info(p.stdout)
        if len(p.stderr) > 0:
            self.log.error(p.stderr)

        return p


class INDI_Camera(INDI_Device):
    """
    Provide higher-level interface to an INDI camera
    """

    def ccd_exposure(self, exptime):
        """
        Set exposure time for a single exposure

        Arguments
        ---------
        exptime : float
            Exposure time in seconds
        """
        self.set_prop("CCD_EXPOSURE", "CCD_EXPOSURE_VALUE", exptime)

    def stream_exposure(self, exptime):
        """
        Set exposure time to use while streaming video

        Arguments
        ---------
        exptime : float
            Exposure time in seconds
        """
        self.set_prop("STREAMING_EXPOSURE", "STREAMING_EXPOSURE_VALUE", exptime)

    def record_frames(self, nframes, savedir=None, filename=None):
        """
        Record a video nframes long

        Arguments
        ---------
        nframes : int
            Number of frames to record
        savedir : str or None
            (Optional) Directory to save video file to
        filename : str or None
            (Optional) Filename to save to
        """
        if savedir is not None:
            self.set_prop("RECORD_FILE", "RECORD_FILE_DIR", savedir)
        if filename is not None:
            self.set_prop("RECORD_FILE", "RECORD_FILE_NAME", filename)

        self.set_prop("RECORD_OPTIONS", "RECORD_FRAME_TOTAL", int(nframes))
        self.set_prop("RECORD_STREAM", "RECORD_FRAME_ON", "On")

    def record_duration(self, rectime, savedir=None, filename=None):
        """
        Record a video rectime seconds long

        Arguments
        ---------
        rectime : float
            Length of time in seconds to record for
        savedir : str or None
            Directory to save video file to
        filename : str or None
            Filename to save to
        """
        if savedir is not None:
            self.set_prop("RECORD_FILE", "RECORD_FILE_DIR", savedir)
        if filename is not None:
            self.set_prop("RECORD_FILE", "RECORD_FILE_NAME", filename)

        self.set_prop("RECORD_OPTIONS", "RECORD_DURATION", rectime)
        self.set_prop("RECORD_STREAM", "RECORD_DURATION_ON", "On")

    def ser_mode(self):
        """
        Configure camera to save files in SER format
        """
        self.set_prop("CCD_STREAM_RECORDER", "SER", "On")

    def ogv_mode(self):
        """
        Configure camera to save files in OGV format
        """
        self.set_prop("CCD_STREAM_RECORDER", "SER", "Off")

    def mjpeg_mode(self):
        """
        Configure camera to encode video using MJPEG
        """
        self.set_prop("CCD_STREAM_ENCODER", "MJPEG", "On")
        self.set_prop("CCD_STREAM_ENCODER", "RAW", "Off")

    def raw_mode(self):
        """
        Configure camera to use raw video encoding
        """
        self.set_prop("CCD_STREAM_ENCODER", "MJPEG", "Off")
        self.set_prop("CCD_STREAM_ENCODER", "RAW", "On")

    def set_filename(self, filename):
        """
        Configure filename for saved video
        """
        self.set_prop("RECORD_FILE", "RECORD_FILE_NAME", filename)

    def set_savedir(self, dirname):
        """
        Configure directory to save video files to
        """
        self.set_prop("RECORD_FILE", "RECORD_FILE_DIR", dirname)

    def set_stream_ROI(self, x, y, width, height):
        """
        Configure Region of Interest (ROI) to stream

        Arguments
        ---------
        x : int
            X position of the ROI
        y : int
            Y position of the ROI
        width : int
            Width of the ROI
        height : int
            Height of the ROI
        """
        self.set_prop("CCD_STREAM_FRAME", "X", int(x))
        self.set_prop("CCD_STREAM_FRAME", "Y", int(y))
        self.set_prop("CCD_STREAM_FRAME", "WIDTH", int(width))
        self.set_prop("CCD_STREAM_FRAME", "HEIGHT", int(height))

    def set_ROI(self, x, y, width, height):
        """
        Configure Region of Interest (ROI) on the detector

        Arguments
        ---------
        x : int
            X position of the ROI
        y : int
            Y position of the ROI
        width : int
            Width of the ROI
        height : int
            Height of the ROI
        """
        self.set_prop(
            "CCD_FRAME",
            f"X={int(x)};Y={int(y)};WIDTH={int(width)};HEIGHT={int(height)}",
        )
