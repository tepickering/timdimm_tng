from pathlib import Path
import argparse
import warnings

from functools import partial
from multiprocessing import Pool, shared_memory
from multiprocessing.managers import SharedMemoryManager

import numpy as np

from skimage.transform import warp_polar, warp, PiecewiseAffineTransform
from skimage import filters
from skimage import measure

import matplotlib.pyplot as plt

import astropy
import astropy.units as u
from astropy import stats, visualization
from astropy.modeling import models, fitting
from astropy.time import TimezoneInfo

from photutils.segmentation import SourceFinder, make_2dgaussian_kernel, SourceCatalog
from photutils.aperture import ApertureStats, CircularAperture

from timdimm_tng.ser import load_ser_file

warnings.filterwarnings("ignore", module="erfa")


def moments(
    data,
    aperture_diameter=76.2 * u.mm,
    wavelength=0.5 * u.um,
    pixel_scale=0.93 * u.arcsec,
):
    """
    Returns (height, x, y, width_x, width_y)
    the gaussian parameters of a 2D distribution by calculating its
    moments

    Arguments
    ---------
    data : 2D ~numpy.ndarray
        2D image to analyze
    aperture_diameter : ~astropy.units.Quantity (default: 76.2 mm)
        Diameter of aperture used to obtain image
    wavelength : ~astropy.units.Quantity (default: 0.5 um)
        Wavelength of the observation
    pixel_scale : ~astropy.units.Quantity (default: 0.93 arcsec/pixel)
        Angle subtended by each pixel

    Returns
    -------
    (height, x, y, width_x, width_y) : tuple of floats
        Peak flux, X centroid, Y centroid, X sigma, Y sigma
    """
    total = data.sum()
    dx = pixel_scale.to(u.radian).value  # convert pixel scale to radians
    Y, X = np.indices(data.shape)
    x = (X * data).sum() / total
    y = (Y * data).sum() / total
    col = data[:, int(x)]
    width_x = np.sqrt(abs((np.arange(col.size) - y) ** 2 * col).sum() / col.sum())
    row = data[int(y), :]
    width_y = np.sqrt(abs((np.arange(row.size) - x) ** 2 * row).sum() / row.sum())
    height = data.max()
    strehl = (
        (height / total)
        * (4.0 / np.pi)
        * (wavelength / (aperture_diameter * dx)).decompose().value ** 2
    )
    return height, strehl, x, y, width_x, width_y


def seeing(
    sigma,
    baseline=143 * u.mm,
    aperture_diameter=76.2 * u.mm,
    wavelength=0.64 * u.um,
    pixel_scale=0.742 * u.arcsec,
    direction="longitudinal",
):
    """
    Calculate seeing from image motion variance, sigma, using the equations from
    Tokovinin (2002; https://www.jstor.org/stable/10.1086/342683). Numbers are for the
    MMTO's 3-aperture Hartmann mask on an LX200 with an ASI 432MM camera (9 um pixels;
    6400 A effective wavelength). For this system, 1.22 * lambda/D is 1.66 arcsec.

    Arguments
    ---------
    sigma : float
        Standard deviation of differential image motion in pixels
    baseline : ~astropy.units.Quantity (default: 143 mm)
        Distance between aperture centers
    aperture_diameter : ~astropy.units.Quantity (default 76.2 mm)
        Diameter of DIMM apertures
    wavelength : ~astropy.units.Quantity (default: 0.64 um)
        Effective wavelength of observation (default for ZWO ASI432MM)
    pixel_scale : ~astropy.units.Quantity (default: 0.742 arcsec/pixel)
        Angle subtended by each pixel (default is for 9 um pixels and 2500 mm focal length)
    """
    b = (baseline / aperture_diameter).decompose().value
    sigma = sigma * pixel_scale.to(u.radian).value  # convert stddev to radians
    variance = sigma**2.0
    k = {}
    k["longitudinal"] = 0.364 * (
        1.0 - 0.532 * b ** (-1.0 / 3.0) - 0.024 * b ** (-7.0 / 3.0)
    )
    k["transverse"] = 0.364 * (
        1.0 - 0.798 * b ** (-1.0 / 3.0) + 0.018 * b ** (-7.0 / 3.0)
    )

    if direction not in k:
        raise ValueError(f"Valid motion directions are {' and '.join(k.keys())}")

    seeing = (
        0.98
        * ((aperture_diameter / wavelength).decompose().value ** 0.2)
        * ((variance / k[direction]) ** 0.6)
        * u.radian
    )
    return seeing.to(u.arcsec)


def massdimm_seeing(sigma):
    """
    Calculate seeing for an ASI432MM camera on an LX200 attached to the MASSDIMM instrument
    """
    return seeing(sigma, baseline=170 * u.mm, aperture_diameter=70 * u.mm)


def timdimm_seeing(sigma):
    """
    Calculate seeing for the new timDIMM configuration with the old SAAO DIMM mask
    and an ASI432MM camera
    """
    return seeing(sigma, baseline=200 * u.mm, aperture_diameter=50 * u.mm)


def find_apertures(
    data, threshold=15.0, plot=False, ap_size=7, brightest=3, std=None, deblend=True
):
    """
    Use DAOStarFinder() to find and centroid star images from each DIMM aperture.

    Parameters
    ----------
    data : FITS filename or 2D ~numpy.ndarray
        Reference image to determine aperture positions
    threshold : float (default: 15.0)
        DAOfind threshold in units of the standard deviation of the image
    plot: bool (default: False)
        Toggle plotting of the reference image and overlayed apertures
    ap_size : float (default: 7)
        Radius of plotted apertures in pixels
    brightest : int (default: 3)
        Number of brightest stars to use for aperture positions
    std : float or None (default: None)
        Standard deviation of image statistics, calculate if None
    """
    if std is None:
        mean, median, std = stats.sigma_clipped_stats(data, sigma=3.0, maxiters=5)

    data = data - mean
    threshold = threshold * std
    kernel = make_2dgaussian_kernel(5, size=15)
    convolved_data = astropy.convolution.convolve(data, kernel)
    finder = SourceFinder(npixels=15, deblend=deblend, progress_bar=False)
    segment_map = finder(convolved_data, threshold)
    t = SourceCatalog(data, segment_map, convolved_data=convolved_data).to_table()
    t.sort("max_value")
    stars = t[-brightest:]
    stars.sort("xcentroid")

    if stars is None:
        raise Exception("No stars detected in image")

    positions = list(zip(stars["xcentroid"], stars["ycentroid"]))
    apertures = CircularAperture(positions, r=ap_size)

    fig = None
    if plot:
        fig, ax = plt.subplots()
        fig.set_label("DIMM Apertures")
        im, _ = visualization.imshow_norm(
            data, ax, origin="lower", stretch=visualization.LogStretch()
        )
        fig.colorbar(im)
        apertures.plot(color="red", lw=1.5, alpha=0.5, axes=ax)
    return apertures, fig


def hdimm_calc(data, aps):
    """
    Calculate longitudinal distance for each baseline in the 3-aperture Hartmann-DIMM mask

    Arguments
    ---------
    data : 2D numpy.ndarray image
        Image frame to perform centroids on

    aps : ~photutils.aperture.CircularAperture
        Aperture positions
    """
    overlapped = False
    ap_stats = ApertureStats(data, aps)
    ap_pos = ap_stats.centroid
    base1 = ap_pos[1] - ap_pos[0]
    base2 = ap_pos[2] - ap_pos[0]
    base3 = ap_pos[2] - ap_pos[1]
    d_base1 = np.sqrt(np.dot(base1.T, base1))
    d_base2 = np.sqrt(np.dot(base2.T, base2))
    d_base3 = np.sqrt(np.dot(base3.T, base3))

    for b in d_base1, d_base2, d_base3:
        if b < 0.5 * aps.r:
            overlapped = True

    if (
        np.isfinite(ap_pos).all()
        and len(ap_pos) == 3
        and np.all(ap_stats.sum > 0)
        and not overlapped
    ):
        new_aps = CircularAperture(ap_pos, aps.r)
    else:
        try:
            new_aps, _ = find_apertures(
                data, brightest=3, ap_size=aps.r, deblend=True, plot=False
            )
            ap_stats = ApertureStats(data, new_aps)
            ap_pos = ap_stats.centroid
            base1 = ap_pos[1] - ap_pos[0]
            base2 = ap_pos[2] - ap_pos[0]
            base3 = ap_pos[2] - ap_pos[1]
            d_base1 = np.sqrt(np.dot(base1.T, base1))
            d_base2 = np.sqrt(np.dot(base2.T, base2))
            d_base3 = np.sqrt(np.dot(base3.T, base3))
        except Exception as _:
            return None

    if not np.isfinite(ap_pos).all() or len(ap_pos) != 3 or np.any(ap_stats.sum < 0):
        # print(f"Bad centroiding: {ap_pos}")
        return None

    return new_aps, [d_base1, d_base2, d_base3], ap_stats.sum


def dimm_calc(data, aps):
    """
    Calculate longitudinal distance between two spots creatded by a DIMM mask

    Arguments
    ---------
    data : 2D numpy.ndarray image
        Image frame to perform centroids on

    aps : ~photutils.aperture.CircularAperture
        Aperture positions
    """
    ap_stats = ApertureStats(data, aps)
    ap_pos = ap_stats.centroid
    if np.isfinite(ap_pos).all() and len(ap_pos) == 2 and np.all(ap_stats.sum > 0):
        new_aps = CircularAperture(ap_pos, aps.r)
    else:
        try:
            new_aps, _ = find_apertures(data, brightest=2, threshold=7, ap_size=aps.r, plot=False)
            ap_stats = ApertureStats(data, new_aps)
            ap_pos = ap_stats.centroid
        except Exception as _:
            return None

    if not np.isfinite(ap_pos).all() or len(ap_pos) != 2 or np.any(ap_stats.sum < 0):
        # print(f"Bad centroiding: {ap_pos}")
        return None

    baseline = ap_pos[1] - ap_pos[0]
    dist_baseline = np.sqrt(np.dot(baseline.T, baseline))
    return new_aps, [dist_baseline], ap_stats.sum


def analyze_dimm_cube(
    filename,
    airmass=1.0,
    seeing_func=timdimm_seeing,
    napertures=2,
    ap_size=None,
    plot=False,
):
    """
    Analyze an SER format data cube of DIMM observations and calculate the seeing from the
    differential motion along the longitudinal axis of each baseline.

    Arguments
    ---------
    filename : str or ~pathlib.Path
        Filename of the SER data cube to analyze
    airmass : float (default: 1.0)
        Airmass of the seeing observation
    seeing : function (default: timdimm_seeing)
        Function to use for seeing calculation
    napertures : int (default: 2)
        Number of apertures in the DIMM mask
    ap_size : int (default: None)
        Override the default ap_size for dimm (11) or hdimm (7)
    plot : bool (default: False)
        Toggle plotting of the aperture positions
    """
    cube = load_ser_file(Path(filename))

    nframes = cube["data"].shape[0]

    if ap_size is None:
        if napertures == 2:
            ap_size = 11
        else:
            ap_size = 15

    apertures, fig = find_apertures(
        np.mean(cube["data"][:5], axis=0),
        brightest=napertures,
        ap_size=ap_size,
        plot=plot,
    )

    baselines = []
    positions = []
    fluxes = []
    nbad = 0

    frame_meds = np.median(cube["data"], axis=(1, 2))

    for i in range(nframes):
        frame = cube["data"][i, :, :] - frame_meds[i]

        if napertures == 2:
            dimm_meas = dimm_calc(frame, apertures)
        else:
            dimm_meas = hdimm_calc(frame, apertures)

        if dimm_meas is not None:
            apertures, ap_distances, ap_fluxes = dimm_meas
            baselines.append(ap_distances)
            positions.append(apertures.positions.mean(axis=0))
            fluxes.append(ap_fluxes)
        else:
            nbad += 1

        if nbad > 100:
            raise Exception("Hit 100 bad frame limit.")

    baselines = np.array(baselines).transpose()
    positions = np.array(positions).transpose()

    seeing_vals = []
    for baseline in baselines:
        _, _, baseline_std = stats.sigma_clipped_stats(baseline, sigma=10, maxiters=10)
        # baseline_std = np.std(baseline)
        seeing_vals.append(seeing_func(baseline_std) / airmass**0.6)

    ave_seeing = u.Quantity(seeing_vals).mean()

    return {
        "seeing": ave_seeing,
        "raw_seeing": seeing_vals,
        "baseline_lengths": baselines,
        "aperture_positions": positions,
        "aperture_fluxes": fluxes,
        "frame_times": cube["frame_times"],
        "N_bad": nbad,
        "aperture_plot": fig,
    }


def process_fass_image(image, background_box_size=15, width_cut=0.1):
    """
    Process FASS image to measure background, image statistics, pupil center, and pupil width

    Parameters
    ----------
    image : np.ndarray
        Raw image to process
    background_box_size : int (default: 15)
        Size of the box to use for background estimation. Uses the four corners of the image.
    width_cut : float (default: 0.1)
        Fraction of the maximum pixel value to use for determining the width of the pupil.

    Returns
    -------
    proc_image : np.ndarray
        Background subtracted image
    bkg_mean : float
        Mean background value
    bkg_median : float
        Median background value
    bkg_std : float
        Standard deviation in the background regions
    x : float
        X coordinate of the pupil center
    y : float
        Y coordinate of the pupil center
    width : float
        Width of the pupil
    """
    ul = image[:background_box_size, :background_box_size]
    ll = image[-background_box_size:, :background_box_size]
    ur = image[:background_box_size, -background_box_size:]
    lr = image[-background_box_size:, -background_box_size:]
    background = np.vstack([ul, ll, ur, lr])
    bkg_mean = np.mean(background)
    bkg_median = np.median(background)
    bkg_std = np.std(background)
    proc_image = image.copy() - bkg_median

    Y, X = np.indices(proc_image.shape)
    proc_sum = proc_image.sum()
    x = (X * proc_image).sum() / proc_sum
    y = (Y * proc_image).sum() / proc_sum

    x_sum = proc_image.sum(axis=0)
    y_sum = proc_image.sum(axis=1)

    width_x = np.where(x_sum > width_cut * x_sum.max())[0].size
    width_y = np.where(y_sum > width_cut * y_sum.max())[0].size

    width = (width_x + width_y) / 2
    return proc_image, bkg_mean, bkg_median, bkg_std, x, y, width


def init_fass_cube(image_cube, n_frames=500):
    """
    Average first n_frames of the image cube to determine the
    pupil size and initial pupil center position.

    Parameters
    ----------
    image_cube : np.ndarray
        Image cube to process
    n_frames : int (default: 500)
        Number of frames to average

    Returns
    -------
    proc_image : np.ndarray
        Background subtracted, coadded first n_frames of image_cube
    x : float
        X coordinate of the pupil center
    y : float
        Y coordinate of the pupil center
    width : float
        Width of the pupil
    """
    image = image_cube[:n_frames, :, :].mean(axis=0)
    proc_image, _, _, _, x, y, width = process_fass_image(image)
    return proc_image, x, y, width


def _process_slice_func(
    index,
    x0=0,
    y0=0,
    radius=100,
    input_dtype=np.float32,
    input_cube_shape=(1000, 100, 100),
    output_cube_shape=(1000, 100, 100),
    slice_shape=(100, 100),
    input_key=None,
    output_key=None,
    center_gain=0.1,
):
    """
    Process a slice of a FASS cube to unwrap polar coordinates to a cartesian grid
    of radius vs azimuth.

    Parameters
    ----------
    index : int
        Index of the cube to process
    x0 : float
        Initial guess for the pupil center x coordinate
    y0 : float
        Initial guess for the pupil center y coordinate
    radius : float
        Pupil radius to pass to warp_polar()
    input_dtype : np.dtype
        dtype of the input cube
    input_cube_shape : tuple
        Shape of the input cube
    output_cube_shape : tuple
        Shape of the output cube
    slice_shape : tuple
        Shape of a slice in the output cube
    input_key : str
        Name of the shared memory block containing the input cube
    output_key : str
        Name of the shared memory block containing the output cube
    center_gain : float
        Gain to use for updating the pupil center position
    """
    input_shm = shared_memory.SharedMemory(name=input_key)
    output_shm = shared_memory.SharedMemory(name=output_key)
    input_cube = np.ndarray(input_cube_shape, dtype=input_dtype, buffer=input_shm.buf)
    output_cube = np.ndarray(output_cube_shape, dtype=np.float32, buffer=output_shm.buf)
    image = input_cube[index, :, :]

    proc_image, _, _, _, x, y, _ = process_fass_image(image)
    x0 = x0 + center_gain * (x - x0)
    y0 = y0 + center_gain * (y - y0)

    unwrapped = warp_polar(
        proc_image,
        output_shape=slice_shape,
        center=(x0, y0),
        radius=radius,
        scaling="linear",
        preserve_range=True,
    )
    # recast output as float32. memory savings/performance
    # worth the small loss of precision.
    output_cube[index, :, :] = unwrapped.astype(np.float32)


def _rectify_slice(
    index,
    tform=None,
    input_key=None,
    input_dtype=np.float32,
    input_shape=(1000, 100, 100),
):
    input_shm = shared_memory.SharedMemory(name=input_key)
    input_cube = np.ndarray(input_shape, dtype=input_dtype, buffer=input_shm.buf)
    imslice = input_cube[index, :, :]
    rect_slice = warp(imslice, tform, output_shape=input_shape[1:], preserve_range=True)
    input_cube[index, :, :] = rect_slice.astype(input_dtype)


def unwrap_fass_cube(image_cube, center_gain=0.1, radial_pad=10, oversample=2, nproc=8):
    """
    Unwrap FASS image cube to polar coordinates.

    Parameters
    ----------
    image_cube : np.ndarray
        Image cube to unwrap
    center_gain : float (default: 0.1)
        Gain factor to use for centering the pupil
    radial_pad : int (default: 20)
        Number of pixels to pad the radial dimension
    oversample : int (default: 2)
        Oversampling factor to use for the unwrapping
    nproc : int (default: 8)
        Number of processes to use for parallel processing

    Returns
    -------
    unwrapped_cube : np.ndarray
        Unwrapped image cube
    """
    _, x, y, width = init_fass_cube(image_cube)
    x0 = x
    y0 = y
    radius = width / 2 + radial_pad

    with SharedMemoryManager() as _:
        input_shm = shared_memory.SharedMemory(create=True, size=image_cube.nbytes)
        input_dtype = image_cube.dtype
        input_shm_cube = np.ndarray(
            image_cube.shape, dtype=input_dtype, buffer=input_shm.buf
        )
        input_shm_cube[:] = image_cube[:]
        output_slice_shape = (
            int(2 * np.pi * oversample * radius),
            int(oversample * radius),
        )
        output_cube_shape = (image_cube.shape[0],) + output_slice_shape
        output_size = (
            image_cube.shape[0] * output_slice_shape[0] * output_slice_shape[1] * 4
        )  # we'll use float32 outputs
        output_shm = shared_memory.SharedMemory(create=True, size=output_size)
        unwrapped_cube = np.ndarray(
            output_cube_shape, dtype=np.float32, buffer=output_shm.buf
        )
        returned_cube = np.ndarray(output_cube_shape, dtype=np.float32)
        with Pool(processes=nproc) as pool:
            proc_slice = partial(
                _process_slice_func,
                x0=x0,
                y0=y0,
                radius=radius,
                input_dtype=input_dtype,
                input_cube_shape=image_cube.shape,
                output_cube_shape=output_cube_shape,
                slice_shape=output_slice_shape,
                input_key=input_shm.name,
                output_key=output_shm.name,
                center_gain=center_gain,
            )
            pool.map(proc_slice, range(image_cube.shape[0]))
            # copy data out of shared memory before closing
            returned_cube[:] = unwrapped_cube[:]
    return returned_cube


def rectify_fass_cube(
    image_cube, smooth_sigma=4, contour_level=0.3, contour_degree=5, nproc=8
):
    stacked = image_cube.mean(axis=0)
    smoothed = filters.gaussian(stacked, sigma=smooth_sigma)
    contours = measure.find_contours(smoothed, contour_level * smoothed.max())
    pup_inner = np.mean(contours[0][:, 1])
    pup_outer = np.mean(contours[1][:, 1])

    fitter = fitting.LinearLSQFitter()
    contour_model = models.Legendre1D(degree=contour_degree)
    contour_inner = fitter(contour_model, contours[0][:, 0], contours[0][:, 1])
    contour_outer = fitter(contour_model, contours[1][:, 0], contours[1][:, 1])

    y = np.arange(stacked.shape[0])
    src_inner = np.array([pup_inner * np.ones(stacked.shape[0]), y]).T
    src_outer = np.array([pup_outer * np.ones(stacked.shape[0]), y]).T
    src = np.vstack([src_inner, src_outer])

    dst_inner = np.array([contour_inner(y), y]).T
    dst_outer = np.array([contour_outer(y), y]).T
    dst = np.vstack([dst_inner, dst_outer])

    tform = PiecewiseAffineTransform()
    tform.estimate(src, dst)

    flat_image = warp(stacked, tform, output_shape=stacked.shape)

    returned_cube = np.ndarray(image_cube.shape, dtype=np.float32)

    with SharedMemoryManager() as _:
        input_shm = shared_memory.SharedMemory(create=True, size=image_cube.nbytes)
        input_dtype = image_cube.dtype
        input_shm_cube = np.ndarray(
            image_cube.shape, dtype=input_dtype, buffer=input_shm.buf
        )
        input_shm_cube[:] = image_cube[:]
        with Pool(processes=nproc) as pool:
            proc_slice = partial(
                _rectify_slice,
                tform=tform,
                input_key=input_shm.name,
                input_dtype=input_dtype,
                input_shape=image_cube.shape,
            )
            pool.map(proc_slice, range(image_cube.shape[0]))
            # copy data out of shared memory before closing
            returned_cube[:] = input_shm_cube[:]

    return returned_cube, flat_image


def timdimm_analyze():
    """
    Set up command-line interface to analyze timDIMM datacubes
    """
    parser = argparse.ArgumentParser(
        description="Utility for analyzing timDIMM data cubes"
    )

    parser.add_argument(
        "-f",
        "--filename",
        metavar="<filename>",
        help="Filename of SER data cube to analyze",
    )

    parser.add_argument(
        "-a",
        "--airmass",
        metavar="<airmass>",
        help="Airmass of observation",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()

    results = analyze_dimm_cube(args.filename, airmass=args.airmass, plot=True)

    print(f"Seeing: {results['seeing']:.2f}")
    with open("seeing.txt", "w") as f:
        print(f"{results['seeing'].value:.2f}", file=f)
        tobs = results["frame_times"][-1].to_datetime(timezone=TimezoneInfo(2 * u.hour))
        print(tobs, file=f)

    results["aperture_plot"].savefig("apertures.png")

    return 0


def hdimm_analyze():
    """
    Set up command-line interface to analyze 3-aperture HDIMM datacubes
    """
    parser = argparse.ArgumentParser(
        description="Utility for analyzing HDIMM data cubes"
    )

    parser.add_argument(
        "-f",
        "--filename",
        metavar="<filename>",
        help="Filename of SER data cube to analyze",
    )

    parser.add_argument(
        "-a",
        "--airmass",
        metavar="<airmass>",
        help="Airmass of observation",
        type=float,
        default=1.0,
    )

    args = parser.parse_args()

    results = analyze_dimm_cube(
        args.filename, airmass=args.airmass, seeing_func=seeing, napertures=3, plot=True
    )

    print(f"Average Seeing: {results['seeing']:.2f}")
    print(f"    Baseline 1: {results['raw_seeing'][0]:.2f}")
    print(f"    Baseline 2: {results['raw_seeing'][1]:.2f}")
    print(f"    Baseline 3: {results['raw_seeing'][2]:.2f}")
    print(f"         N bad: {results['N_bad']}")

    results["aperture_plot"].savefig("apertures.png")

    return 0
